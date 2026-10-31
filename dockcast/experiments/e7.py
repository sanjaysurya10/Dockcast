"""E7 — feature-group ablation at +60, with oracle weather (PRD 14 E7, RQ7, M11).

``make backtest E=E7``. One ``lgbm_global`` with every feature group (``full``: the v1 groups,
spatial at 600 m from E4, in-fold E3 cluster one-hot, **oracle weather**) is compared with eight
retrained copies, each without one group (``no_<group>``). Same folds, LightGBM defaults and
early stopping as E1; +60 only and all 8 folds (owner decision 2026-10-31). Forecast weather does
not exist for the Format B test weeks, so the forecast-vs-oracle gap is deferred (PRD 23).

Writes MLflow (experiment ``E7``), ``backtest_results``, the E7 section of
``reports/experiments.md`` and ``reports/figures/e7_ablation.png``.
"""

import argparse
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import mlflow
import numpy as np
import pandas as pd
import structlog
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from dockcast.db.engine import make_engine
from dockcast.evaluation.backtest import FoldOutcome, score_fold, summarise
from dockcast.evaluation.reports import (
    REPORTS,
    generated_line,
    git_commit,
    replace_section,
    store_results,
)
from dockcast.evaluation.splits import Fold
from dockcast.evaluation.training import FoldData, prepare_fold
from dockcast.experiments.e1 import b_span, default_folds, reference_tables
from dockcast.experiments.e2 import cluster_groups
from dockcast.experiments.e2b import attach_clusters
from dockcast.experiments.e3 import GRID, INK, MUTED, SERIES, SURFACE
from dockcast.experiments.e4 import latest_run, score_all
from dockcast.features.registry import FEATURE_GROUPS
from dockcast.features.spatial import spatial_columns
from dockcast.features.weather import WEATHER_COLUMNS, load_observed_weather, oracle_weather
from dockcast.models.base import Forecaster
from dockcast.models.baselines import Persistence
from dockcast.models.lgbm_quantile import LgbmQuantile
from dockcast.quality.gaps import Gap, load_gaps
from dockcast.targets.regression import load_panel
from dockcast.tracking import setup_mlflow

log = structlog.get_logger(job="e7")
EXPERIMENT = "E7"
FIGURES = REPORTS / "figures"
HORIZON = 60
RADIUS_M = 600.0
SLICES = ("rush_hour", "weekend", "capacity_band", "rebalance", "cluster")


def cluster_columns(n_clusters: int) -> list[str]:
    """One-hot column names for ``n_clusters`` E3 clusters."""
    return [f"cluster_{c}" for c in range(n_clusters)]


def ablation_groups(n_clusters: int) -> dict[str, list[str]]:
    """Every E7 feature group (PRD 10.8): the v1 groups plus spatial, cluster and weather."""
    return {
        **FEATURE_GROUPS,
        "spatial": spatial_columns(RADIUS_M),
        "cluster": cluster_columns(n_clusters),
        "weather": WEATHER_COLUMNS,
    }


def variants(groups: Mapping[str, Sequence[str]]) -> dict[str, list[str]]:
    """``full`` (every group) and ``no_<group>`` (one group removed), in a stable order."""
    out = {"full": [c for cols in groups.values() for c in cols]}
    for name in groups:
        out[f"no_{name}"] = [c for g, cols in groups.items() if g != name for c in cols]
    return out


def add_cluster_onehot(
    rows: pd.DataFrame, assignment: Mapping[int, int], n_clusters: int
) -> pd.DataFrame:
    """One-hot in-fold cluster columns (all zero for a station without a label)."""
    cluster = rows["station_key"].map(assignment)
    out = rows.copy()
    for c, column in enumerate(cluster_columns(n_clusters)):
        out[column] = (cluster == c).astype(float)
    return out


def make_models(columns: Mapping[str, Sequence[str]], stations: Sequence[int]) -> list[Forecaster]:
    """Persistence (MASE denominator) and one ``lgbm_<variant>`` per variant."""
    models: list[Forecaster] = [Persistence()]
    for name, cols in columns.items():
        model = LgbmQuantile(list(cols), stations, num_threads=10)
        model.name = f"lgbm_{name}"
        models.append(model)
    return models


def run(
    engine: Engine,
    folds: Sequence[Fold],
    gaps: Sequence[Gap],
    labels: pd.DataFrame,
    columns: Mapping[str, Sequence[str]],
    n_clusters: int,
) -> list[FoldOutcome]:
    """Train and score every variant on every fold at :data:`HORIZON`."""
    data_start, _ = b_span(engine)
    calendar, info = reference_tables(engine)
    end = max(f.test_end for f in folds)
    full_panel = load_panel(engine, data_start, end)
    weather = load_observed_weather(engine, data_start, end + pd.Timedelta(hours=3))
    outcomes: list[FoldOutcome] = []
    for fold in folds:
        started = time.monotonic()
        panel = full_panel[full_panel["state_ts"] <= pd.Timestamp(fold.test_end)]
        stations = sorted(int(s) for s in panel["station_key"].unique())
        data = prepare_fold(
            panel, fold, HORIZON, gaps, calendar, info, data_start, neighbour_radii=(RADIUS_M,)
        )
        assignment = cluster_groups(labels, fold.fold)
        data = FoldData(
            *(
                oracle_weather(add_cluster_onehot(part, assignment, n_clusters), weather)
                for part in (data.train, data.valid, data.test)
            )
        )
        outcome = score_fold(data, fold, HORIZON, make_models(columns, stations), [])
        outcome.scored["fold"], outcome.scored["horizon_min"] = fold.fold, HORIZON
        outcomes.append(outcome)
        log.info(
            "fold_scored",
            fold=fold.fold,
            common=outcome.rows_common,
            seconds=round(time.monotonic() - started),
        )
        del panel, data
    return outcomes


def ablation_table(results: pd.DataFrame, names: Sequence[str]) -> pd.DataFrame:
    """ΔMAE and Δcoverage (``no_<group>`` - ``full``) per group, over folds, on all rows.

    Returns:
        One row per group: ``delta_mae`` mean, ``delta_min``, ``delta_max``, ``hurts`` (folds
        where removing the group raised MAE), ``delta_coverage`` mean.
    """
    part = results[(results.slice_kind == "overall") & (results.slice_value == "all")]
    mae = part.pivot_table(index="fold", columns="model_name", values="mae")
    cov = part.pivot_table(index="fold", columns="model_name", values="coverage_80")
    rows = []
    for name in names:
        if not name.startswith("lgbm_no_"):
            continue
        delta = mae[name] - mae["lgbm_full"]
        rows.append(
            {
                "group": name.removeprefix("lgbm_no_"),
                "delta_mae": float(delta.mean()),
                "delta_min": float(delta.min()),
                "delta_max": float(delta.max()),
                "hurts": int((delta > 0).sum()),
                "delta_coverage": float((cov[name] - cov["lgbm_full"]).mean()),
            }
        )
    return pd.DataFrame(rows).sort_values("delta_mae", ascending=False).reset_index(drop=True)


def plot_ablation(table: pd.DataFrame, path: Path) -> None:
    """ΔMAE when each group is removed, with the fold range as whiskers."""
    order = table.sort_values("delta_mae")
    y = np.arange(len(order))
    fig, ax = plt.subplots(figsize=(8, 0.5 * len(order) + 1.2), facecolor=SURFACE)
    ax.barh(y, order["delta_mae"], height=0.6, color=SERIES[0])
    ax.errorbar(
        order["delta_mae"],
        y,
        xerr=[order["delta_mae"] - order["delta_min"], order["delta_max"] - order["delta_mae"]],
        fmt="none",
        ecolor=INK,
        elinewidth=1,
        capsize=3,
    )
    for yi, value in zip(y, order["delta_mae"], strict=True):
        ax.annotate(
            f"{value:+.3f}",
            (max(value, 0), yi),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
            fontsize=8,
            color=INK,
        )
    ax.axvline(0, color=MUTED, lw=1)
    ax.set_yticks(y)
    ax.set_yticklabels(order["group"], color=INK)
    ax.set_xlabel("ΔMAE at +60 when the group is removed (bikes; > 0 = group helps)", color=MUTED)
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


def render_section(
    run_id: str,
    e3_run: str,
    folds: Sequence[Fold],
    results: pd.DataFrame,
    table: pd.DataFrame,
    groups: Mapping[str, Sequence[str]],
) -> str:
    """The E7 section of ``reports/experiments.md``."""
    summary = summarise(results)
    n_folds = len(folds)
    lines = [
        "## E7 — Feature-group ablation (+60, oracle weather)",
        "",
        generated_line(run_id, folds[0].test_start, folds[-1].test_end),
        "",
        "`lgbm_full` = `lgbm_global` with every feature group: the v1 groups, spatial "
        f"(E4, {int(RADIUS_M)} m), the in-fold E3 cluster as one-hot (E3 run `{e3_run}`) and "
        "**oracle weather** (observed Dublin Airport weather in the hour containing the target "
        "bucket: not available at prediction time, so its effect is an upper bound). Each "
        "`lgbm_no_<group>` is retrained without one group, with the same folds, LightGBM "
        "defaults and early stopping. +60 only, all 8 folds (owner decision 2026-10-31). "
        "Forecast weather does not exist for these test weeks; the forecast-vs-oracle gap is "
        "deferred to collector data. Groups: "
        + "; ".join(f"`{g}` ({len(cols)})" for g, cols in groups.items())
        + ".",
        "",
        "| model | MAE | ± | MASE | bias | coverage P10-P90 | width | rows |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rec in summary.to_dict("records"):
        cov = "—" if pd.isna(rec["coverage_80"]) else f"{float(rec['coverage_80']):.3f}"
        width = "—" if pd.isna(rec["interval_width"]) else f"{float(rec['interval_width']):.2f}"
        lines.append(
            f"| {rec['model_name']} | {float(rec['mae']):.3f} | {float(rec['mae_std']):.3f} | "
            f"{float(rec['mase']):.3f} | {float(rec['bias']):+.3f} | {cov} | {width} | "
            f"{rec['n']} |"
        )
    lines += [
        "",
        "Removing one group (ΔMAE = `lgbm_no_<group>` - `lgbm_full`, bikes; positive = the "
        "group helps):",
        "",
        "| group removed | ΔMAE mean | fold range | folds worse without it | Δcoverage |",
        "|---|---:|---:|---:|---:|",
    ]
    for rec in table.to_dict("records"):
        label = f"{rec['group']} (oracle)" if rec["group"] == "weather" else rec["group"]
        lines.append(
            f"| {label} | {rec['delta_mae']:+.3f} | {rec['delta_min']:+.3f} to "
            f"{rec['delta_max']:+.3f} | {rec['hurts']}/{n_folds} | {rec['delta_coverage']:+.3f} |"
        )
    lines += [
        "",
        "![ΔMAE when each feature group is removed](figures/e7_ablation.png)",
        "",
        "ΔMAE by slice, mean over folds (columns: group removed):",
        "",
        "| slice | value | MAE full | " + " | ".join(table["group"]) + " |",
        "|---|---|---:|" + "---:|" * len(table) + "",
    ]
    mae = results.groupby(["slice_kind", "slice_value", "model_name"])["mae"].mean()
    for kind in SLICES:
        values = sorted({v for (k, v, _) in mae.index if k == kind})
        for value in values:
            base = float(mae[(kind, value, "lgbm_full")])
            deltas = [
                f"{float(mae[(kind, value, f'lgbm_no_{g}')]) - base:+.3f}" for g in table["group"]
            ]
            lines.append(f"| {kind} | {value} | {base:.3f} | " + " | ".join(deltas) + " |")
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    """``make backtest E=E7`` (``--folds N`` for timing runs)."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--folds", type=int, default=None)
    args = parser.parse_args(argv)
    engine = make_engine()
    with Session(engine) as session:
        gaps = load_gaps(session)
    folds = default_folds(engine, gaps)
    if args.folds:
        folds = folds[-args.folds :]
    setup_mlflow("E3")
    e3_run, e3_file = latest_run("E3", "fold_labels_file")
    labels = pd.read_parquet(e3_file)
    n_clusters = int(labels["cluster_id"].max()) + 1
    groups = ablation_groups(n_clusters)
    columns = variants(groups)
    names = ["persistence", *(f"lgbm_{v}" for v in columns)]
    setup_mlflow(EXPERIMENT)
    with mlflow.start_run(run_name="e7") as active:
        run_id = active.info.run_id
        mlflow.log_params(
            {
                "models": ",".join(names),
                "horizons": str(HORIZON),
                "n_folds": len(folds),
                "radius_m": RADIUS_M,
                "weather": "oracle (observed, hour containing the target)",
                "cluster_e3_run": e3_run,
                "git_commit": git_commit(),
                "data_source": "hist_b",
            }
        )
        outcomes = run(engine, folds, gaps, labels, columns, n_clusters)
        scored = pd.concat([o.scored for o in outcomes], ignore_index=True)
        merged = attach_clusters(scored, labels)
        results = score_all(merged, names, extra=("cluster",))
        table = ablation_table(results, names)
        for rec in summarise(results).to_dict("records"):
            mlflow.log_metric(f"mae_{rec['model_name']}_h{HORIZON}", float(rec["mae"]))
        for rec in table.to_dict("records"):
            mlflow.log_metric(f"delta_mae_no_{rec['group']}", float(rec["delta_mae"]))
        mlflow.log_metric("rows_scored", len(merged))
        mlflow.log_text(results.to_csv(index=False), "results.csv")
        mlflow.log_text(table.to_csv(index=False), "ablation.csv")
        stored = store_results(engine, run_id, EXPERIMENT, results)
    if args.folds is None:
        plot_ablation(table, FIGURES / "e7_ablation.png")
        section = render_section(run_id, e3_run, folds, results, table, groups)
        replace_section(REPORTS / "experiments.md", EXPERIMENT, section)
    log.info("e7_done", run_id=run_id, rows=len(merged), results_rows=stored)


if __name__ == "__main__":
    main()
