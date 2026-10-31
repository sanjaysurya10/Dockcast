"""E2 — one global model vs per-station vs per-cluster models, plus Prophet (PRD 12.2, 14, M9).

``make backtest E=E2``. Every LightGBM uses the E1 features, defaults and early stopping:

- ``lgbm_global``: read from the E1 predictions file (deterministic, M6), as in E4;
- ``lgbm_per_station``: one model per station, trained on that station's rows only;
- ``lgbm_per_cluster``: one model per E3 cluster, clusters fitted before each fold (E3 fold
  labels), station kept as a categorical inside the cluster;
- ``prophet_station``: per station, daily + weekly seasonality and public holidays, fitted once
  per fold on hourly observed states before ``train_end`` (horizon-independent).

Low-data stations (PRD 14 E2): per fold and horizon, the quarter of stations with the fewest
training rows. Everything is scored on rows common to E1 and E2. Writes MLflow (experiment
``E2``), ``backtest_results``, ``data/processed/e2_predictions_<run>.parquet``, the E2 section of
``reports/experiments.md`` and ``reports/figures/e2_low_data.png``.
"""

import argparse
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
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

from dockcast.config import get_env_settings, load_project_config
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
from dockcast.evaluation.training import prepare_fold
from dockcast.experiments.e1 import b_span, default_folds, reference_tables
from dockcast.experiments.e3 import GRID, INK, MUTED, SERIES, SURFACE
from dockcast.experiments.e4 import KEYS, attach_baseline, latest_run, score_all
from dockcast.features.matrix import feature_columns
from dockcast.models.base import Forecaster
from dockcast.models.baselines import Persistence
from dockcast.models.partitioned import PartitionedLgbm
from dockcast.models.prophet_model import ProphetStation
from dockcast.quality.gaps import Gap, load_gaps
from dockcast.targets.regression import load_panel
from dockcast.tracking import setup_mlflow

log = structlog.get_logger(job="e2")
EXPERIMENT = "E2"
FIGURES = REPORTS / "figures"
LOW_DATA_SHARE = 0.25
MODELS = ["persistence", "lgbm_global", "lgbm_per_station", "lgbm_per_cluster", "prophet_station"]
COMPARED = MODELS[2:]
SLICES = ("rush_hour", "weekend", "capacity_band", "rebalance", "cluster", "data_amount")


@dataclass(frozen=True)
class LowData:
    """Training-row counts behind the low-data split for one fold and horizon."""

    fold: int
    horizon_min: int
    stations: int
    low: int
    low_max_rows: int
    rest_min_rows: int


def low_data_stations(train: pd.DataFrame, share: float = LOW_DATA_SHARE) -> list[int]:
    """The ``share`` of stations with the fewest training rows (ties broken by station key).

    Args:
        train: Training rows with ``station_key``.
        share: Fraction of stations to mark.

    Returns:
        Station keys, fewest rows first.
    """
    counts = train.groupby("station_key").size().rename("n").reset_index()
    counts = counts.sort_values(["n", "station_key"], kind="stable")
    n_low = math.ceil(len(counts) * share)
    return [int(s) for s in counts["station_key"].head(n_low)]


def low_data_summary(train: pd.DataFrame, low: Sequence[int], fold: int, horizon: int) -> LowData:
    """Row counts of the low-data split, for the report."""
    counts = train.groupby("station_key").size()
    is_low = counts.index.isin(list(low))
    return LowData(
        fold,
        horizon,
        len(counts),
        int(is_low.sum()),
        int(counts[is_low].max()),
        int(counts[~is_low].min()),
    )


def cluster_groups(labels: pd.DataFrame, fold: int) -> dict[int, int]:
    """Station -> E3 cluster fitted before ``fold``."""
    part = labels[labels["fold"] == fold]
    return {int(s): int(c) for s, c in zip(part["station_key"], part["cluster_id"], strict=True)}


def make_models(
    groups: dict[int, int], stations: Sequence[int], prophet: ProphetStation
) -> list[Forecaster]:
    """Persistence (MASE denominator), the two partitioned LightGBMs and Prophet."""
    cols = feature_columns()
    return [
        Persistence(),
        PartitionedLgbm("lgbm_per_station", cols, {s: s for s in stations}, n_jobs=10),
        PartitionedLgbm("lgbm_per_cluster", cols, groups, n_jobs=4, threads_per_model=3),
        prophet,
    ]


def run(
    engine: Engine,
    folds: Sequence[Fold],
    gaps: Sequence[Gap],
    horizons: Sequence[int],
    labels: pd.DataFrame,
) -> tuple[list[FoldOutcome], list[LowData]]:
    """Train and score every fold and horizon."""
    data_start, _ = b_span(engine)
    calendar, info = reference_tables(engine)
    holidays = [
        d for d, h in zip(calendar["date"], calendar["is_public_holiday"], strict=True) if h
    ]
    full_panel = load_panel(engine, data_start, max(f.test_end for f in folds))
    outcomes: list[FoldOutcome] = []
    low_info: list[LowData] = []
    for fold in folds:
        panel = full_panel[full_panel["state_ts"] <= pd.Timestamp(fold.test_end)]
        stations = sorted(int(s) for s in panel["station_key"].unique())
        started = time.monotonic()
        prophet = ProphetStation(holidays).fit_states(panel, pd.Timestamp(fold.train_end))
        log.info("prophet_fitted", fold=fold.fold, seconds=round(time.monotonic() - started))
        for horizon in horizons:
            started = time.monotonic()
            data = prepare_fold(panel, fold, horizon, gaps, calendar, info, data_start)
            low = low_data_stations(data.train)
            low_info.append(low_data_summary(data.train, low, fold.fold, horizon))
            models = make_models(cluster_groups(labels, fold.fold), stations, prophet)
            outcome = score_fold(data, fold, horizon, models, feature_columns())
            scored = outcome.scored
            scored["fold"], scored["horizon_min"] = fold.fold, horizon
            scored["data_amount"] = np.where(scored["station_key"].isin(low), "low", "rest")
            outcomes.append(outcome)
            log.info(
                "fold_scored",
                fold=fold.fold,
                horizon=horizon,
                common=outcome.rows_common,
                seconds=round(time.monotonic() - started),
            )
        del panel
    return outcomes, low_info


def fold_wins(results: pd.DataFrame, kind: str, value: str) -> pd.DataFrame:
    """Folds where each compared model beats ``lgbm_global`` on one slice, per horizon."""
    part = results[(results.slice_kind == kind) & (results.slice_value == value)]
    mae = part.pivot_table(index=["horizon_min", "fold"], columns="model_name", values="mae")
    wins = {m: (mae[m] < mae["lgbm_global"]).groupby(level=0).sum() for m in COMPARED}
    return pd.DataFrame(wins).astype(int)


def slice_mae(results: pd.DataFrame, kind: str, value: str) -> pd.DataFrame:
    """Mean MAE over folds per horizon and model on one slice."""
    part = results[(results.slice_kind == kind) & (results.slice_value == value)]
    return part.groupby(["horizon_min", "model_name"])["mae"].mean().unstack()


def plot_low_data(results: pd.DataFrame, path: Path) -> None:
    """MAE per model on all stations vs low-data stations, one panel per horizon."""
    all_mae = slice_mae(results, "overall", "all")
    low_mae = slice_mae(results, "data_amount", "low")
    horizons = list(all_mae.index)
    fig, axes = plt.subplots(1, len(horizons), figsize=(12, 4.2), facecolor=SURFACE)
    axes = np.atleast_1d(axes)
    x = np.arange(len(MODELS))
    width = 0.38
    for ax, h in zip(axes, horizons, strict=True):
        for offset, frame, label, color in (
            (-width / 2, all_mae, "All stations", SERIES[0]),
            (width / 2, low_mae, "Low-data stations (bottom quarter)", SERIES[1]),
        ):
            values = frame.loc[h, MODELS].to_numpy(dtype=float)
            bars = ax.bar(x + offset, values, width - 0.04, color=color, label=label)
            ax.bar_label(bars, fmt="%.2f", fontsize=7, color=INK, padding=2)
        ax.set_title(f"+{h} min", color=INK, fontsize=12, loc="left")
        ax.set_xticks(x)
        ax.set_xticklabels([m.replace("_", "\n", 1) for m in MODELS], fontsize=8, color=MUTED)
        ax.grid(axis="y", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(colors=MUTED, length=0)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
    axes[0].set_ylabel("MAE (bikes), mean over folds", color=MUTED)
    axes[-1].legend(frameon=False, fontsize=9, labelcolor=INK, loc="upper left")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


def _fmt(value: float) -> str:
    return "—" if pd.isna(value) else f"{value:.3f}"


def render_section(
    run_id: str,
    e1_run: str,
    e3_run: str,
    folds: Sequence[Fold],
    results: pd.DataFrame,
    low_info: Sequence[LowData],
) -> str:
    """The E2 section of ``reports/experiments.md``."""
    summary = summarise(results)
    low_rows = pd.DataFrame([vars(r) for r in low_info])
    lines = [
        "## E2 — Global vs per-station vs per-cluster models, and Prophet",
        "",
        generated_line(run_id, folds[0].test_start, folds[-1].test_end),
        "",
        f"`lgbm_global` = E1 run `{e1_run}` (same folds, rows and training). `lgbm_per_station` "
        "and `lgbm_per_cluster` use the same features, LightGBM defaults and early stopping, "
        "trained on one station's or one cluster's rows; clusters from E3 run "
        f"`{e3_run}`, fitted before each fold. `prophet_station`: per station, daily + weekly "
        "seasonality and public holidays, fitted once per fold on hourly observed states before "
        "the training end, so it does not see the state at the issue time; P10-P90 is "
        "Prophet's 80% interval. All stations were run (the full run was under the 2 h limit "
        "of PRD 12.2). Scored on rows common to E1 and E2. **No weather.**",
        "",
        "| horizon | model | MAE | ± | MASE | bias | coverage P10-P90 | width | rows |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rec in summary.to_dict("records"):
        cov = "—" if pd.isna(rec["coverage_80"]) else f"{float(rec['coverage_80']):.3f}"
        width = "—" if pd.isna(rec["interval_width"]) else f"{float(rec['interval_width']):.2f}"
        lines.append(
            f"| +{rec['horizon_min']} | {rec['model_name']} | {float(rec['mae']):.3f} | "
            f"{float(rec['mae_std']):.3f} | {float(rec['mase']):.3f} | "
            f"{float(rec['bias']):+.3f} | {cov} | {width} | {rec['n']} |"
        )
    lines += [
        "",
        "Low-data stations: per fold and horizon, the "
        f"{int(LOW_DATA_SHARE * 100)}% of stations with the fewest training rows "
        f"({int(low_rows['low'].min())}-{int(low_rows['low'].max())} of "
        f"{int(low_rows['stations'].max())} stations). Across folds and horizons they have at "
        f"most {int(low_rows['low_max_rows'].max())} training rows; the other stations have at "
        f"least {int(low_rows['rest_min_rows'].min())}.",
        "",
        "MAE by data amount, mean over folds (folds where the model beats `lgbm_global` on that "
        "slice in brackets):",
        "",
        "| horizon | model | all stations | low-data | rest |",
        "|---:|---|---:|---:|---:|",
    ]
    all_mae = slice_mae(results, "overall", "all")
    low_mae = slice_mae(results, "data_amount", "low")
    rest_mae = slice_mae(results, "data_amount", "rest")
    wins = {
        "all": fold_wins(results, "overall", "all"),
        "low": fold_wins(results, "data_amount", "low"),
        "rest": fold_wins(results, "data_amount", "rest"),
    }
    n_folds = len(folds)
    for h in all_mae.index:
        for m in MODELS[1:]:
            cells = []
            for key, frame in (("all", all_mae), ("low", low_mae), ("rest", rest_mae)):
                text = _fmt(float(frame.loc[h, m]))
                if m in COMPARED:
                    text += f" ({int(wins[key].loc[h, m])}/{n_folds})"
                cells.append(text)
            lines.append(f"| +{h} | {m} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "![MAE on all stations and on low-data stations](figures/e2_low_data.png)",
        "",
        "ΔMAE (model - `lgbm_global`, bikes; negative = better) by slice, mean over folds:",
        "",
        "| horizon | slice | value | MAE global | Δ per-station | Δ per-cluster | Δ Prophet |",
        "|---:|---|---|---:|---:|---:|---:|",
    ]
    mae = results.groupby(["horizon_min", "slice_kind", "slice_value", "model_name"])["mae"].mean()
    for h in sorted(results.horizon_min.unique()):
        for kind in SLICES:
            values = sorted({v for (hh, k, v, _) in mae.index if hh == h and k == kind})
            for value in values:
                base = float(mae[(h, kind, value, "lgbm_global")])
                deltas = [f"{float(mae[(h, kind, value, m)]) - base:+.3f}" for m in COMPARED]
                lines.append(
                    f"| +{h} | {kind} | {value} | {base:.3f} | " + " | ".join(deltas) + " |"
                )
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    """``make backtest E=E2`` (``--folds N``, ``--horizons`` for timing runs)."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--folds", type=int, default=None)
    parser.add_argument("--horizons", type=str, default=None, help="e.g. 60 or 30,60")
    args = parser.parse_args(argv)
    cfg = load_project_config()
    engine = make_engine()
    with Session(engine) as session:
        gaps = load_gaps(session)
    folds = default_folds(engine, gaps)
    if args.folds:
        folds = folds[-args.folds :]
    horizons = (
        [int(h) for h in args.horizons.split(",")] if args.horizons else cfg.forecast.horizons_min
    )
    setup_mlflow("E1")
    e1_run, e1_file = latest_run("E1", "predictions_file")
    setup_mlflow("E3")
    e3_run, e3_file = latest_run("E3", "fold_labels_file")
    labels = pd.read_parquet(e3_file)
    setup_mlflow(EXPERIMENT)
    commit = git_commit()
    with mlflow.start_run(run_name="e2") as active:
        run_id = active.info.run_id
        mlflow.log_params(
            {
                "models": ",".join(MODELS),
                "horizons": ",".join(map(str, horizons)),
                "n_folds": len(folds),
                "low_data_share": LOW_DATA_SHARE,
                "baseline_e1_run": e1_run,
                "cluster_e3_run": e3_run,
                "git_commit": commit,
                "data_source": "hist_b",
            }
        )
        outcomes, low_info = run(engine, folds, gaps, horizons, labels)
        scored = pd.concat([o.scored for o in outcomes], ignore_index=True)
        merged = attach_baseline(scored, pd.read_parquet(e1_file), labels)
        results = score_all(merged, MODELS, extra=("cluster", "data_amount"))
        for rec in summarise(results).to_dict("records"):
            key = f"{rec['model_name']}_h{rec['horizon_min']}"
            mlflow.log_metric(f"mae_{key}", float(rec["mae"]))
            if not pd.isna(rec["coverage_80"]):
                mlflow.log_metric(f"coverage80_{key}", float(rec["coverage_80"]))
        mlflow.log_metric("rows_merged", len(merged))
        mlflow.log_metric("rows_e2_common", len(scored))
        mlflow.log_text(results.to_csv(index=False), "results.csv")
        mlflow.log_text(
            pd.DataFrame([vars(r) for r in low_info]).to_csv(index=False), "low_data.csv"
        )
        keep = [c for c in merged.columns if c.startswith(("pred_", "p10_", "p90_"))]
        path = get_env_settings().data_dir / "processed" / f"e2_predictions_{run_id}.parquet"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        merged[[*KEYS, "y", "cluster", "data_amount", *keep]].to_parquet(path, index=False)
        mlflow.log_param("predictions_file", str(path))
        stored = store_results(engine, run_id, EXPERIMENT, results)
    if args.folds is None and args.horizons is None:
        figure = FIGURES / "e2_low_data.png"
        plot_low_data(results, figure)
        section = render_section(run_id, e1_run, e3_run, folds, results, low_info)
        replace_section(REPORTS / "experiments.md", EXPERIMENT, section)
    log.info("e2_done", run_id=run_id, rows=len(merged), results_rows=stored)


if __name__ == "__main__":
    main()
