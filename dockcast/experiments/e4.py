"""E4 — spatial features (PRD 10.5, 14): model A (no spatial) vs B (+spatial) at several radii.

``make backtest E=E4``. Model B is ``lgbm_global`` with the v1 features plus the PRD 10.5
neighbour features for one radius (``lgbm_spatial_<r>``), trained exactly like E1 (same folds,
rows, early stopping, seed). Model A is the E1 ``lgbm_global`` prediction for the same rows, read
from the E1 predictions file (E1 is deterministic: reruns at different commits matched to the
last digit, M6). Every model is scored on rows common to E1 and E4. Slices include the E3
cluster of each station, fitted in-fold. Writes MLflow (experiment ``E4``),
``backtest_results``, ``data/processed/e4_predictions_<run>.parquet`` and the E4 section of
``reports/experiments.md``.
"""

import argparse
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

import mlflow
import pandas as pd
import structlog
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from dockcast.config import get_env_settings, load_project_config
from dockcast.db.engine import make_engine
from dockcast.evaluation.backtest import FoldOutcome, score_fold, score_slices, summarise
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
from dockcast.features.matrix import feature_columns
from dockcast.features.spatial import spatial_columns
from dockcast.models.base import Forecaster
from dockcast.models.baselines import Persistence
from dockcast.models.lgbm_quantile import LgbmQuantile
from dockcast.quality.gaps import Gap, load_gaps
from dockcast.targets.regression import load_panel
from dockcast.tracking import setup_mlflow

log = structlog.get_logger(job="e4")
EXPERIMENT = "E4"
KEYS = ["station_key", "issued_at", "horizon_min", "fold"]
SLICES = ("rush_hour", "weekend", "capacity_band", "rebalance", "cluster")
A_COLUMNS = ["pred_lgbm_global", "p10_lgbm_global", "p90_lgbm_global"]


def model_name(radius_m: float) -> str:
    """Name of model B for one radius."""
    return f"lgbm_spatial_{int(radius_m)}"


def latest_run(experiment: str, param: str) -> tuple[str, str]:
    """Latest finished full (8-fold) run of ``experiment`` that logged ``param``.

    Returns:
        Run id and the value of ``param``.
    """
    runs = mlflow.search_runs(
        experiment_names=[experiment],
        filter_string="attributes.status = 'FINISHED'",
        order_by=["start_time DESC"],
        output_format="pandas",
    )
    assert isinstance(runs, pd.DataFrame)
    column = f"params.{param}"
    if column not in runs:
        raise LookupError(f"no {experiment} run logged {param}")
    full = runs[runs[column].notna()]
    if "params.n_folds" in full:
        full = full[full["params.n_folds"].fillna("8") == "8"]
    if full.empty:
        raise LookupError(f"no finished {experiment} run with {param}")
    return str(full.iloc[0]["run_id"]), str(full.iloc[0][column])


def make_models(stations: Sequence[int], radii: Sequence[float]) -> list[Forecaster]:
    """Persistence (MASE denominator) and one spatial LightGBM per radius."""
    base = feature_columns()
    models: list[Forecaster] = [Persistence()]
    for radius in radii:
        model = LgbmQuantile([*base, *spatial_columns(radius)], stations, num_threads=10)
        model.name = model_name(radius)
        models.append(model)
    return models


def run(
    engine: Engine,
    folds: Sequence[Fold],
    gaps: Sequence[Gap],
    radii: Mapping[int, Sequence[float]],
    k: int,
) -> list[FoldOutcome]:
    """Train and score model B for every fold, horizon and that horizon's radii."""
    data_start, _ = b_span(engine)
    calendar, info = reference_tables(engine)
    full_panel = load_panel(engine, data_start, max(f.test_end for f in folds))
    outcomes: list[FoldOutcome] = []
    for fold in folds:
        panel = full_panel[full_panel["state_ts"] <= pd.Timestamp(fold.test_end)]
        stations = sorted(int(s) for s in panel["station_key"].unique())
        for horizon, horizon_radii in radii.items():
            started = time.monotonic()
            data = prepare_fold(
                panel, fold, horizon, gaps, calendar, info, data_start, horizon_radii, k
            )
            models = make_models(stations, horizon_radii)
            cols = sorted({c for m in models for c in getattr(m, "features", [])})
            outcome = score_fold(data, fold, horizon, models, cols)
            outcome.scored["fold"], outcome.scored["horizon_min"] = fold.fold, horizon
            outcomes.append(outcome)
            log.info(
                "fold_scored",
                fold=fold.fold,
                horizon=horizon,
                common=outcome.rows_common,
                seconds=round(time.monotonic() - started),
            )
        del panel
    return outcomes


def attach_baseline(scored: pd.DataFrame, e1: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Join E1 ``lgbm_global`` (model A) and in-fold E3 clusters onto E4 rows.

    Args:
        scored: E4 common rows with ``KEYS``, ``y`` and slice columns.
        e1: E1 predictions with ``KEYS``, ``y`` and :data:`A_COLUMNS`.
        labels: E3 fold labels ``station_key, cluster_id, fold``.

    Returns:
        Rows present in both runs, with model A columns and a ``cluster`` slice.

    Raises:
        ValueError: If the two runs disagree on a target value.
    """
    merged = scored.merge(e1[[*KEYS, "y", *A_COLUMNS]], on=KEYS, suffixes=("", "_e1"))
    if not (merged["y"] == merged["y_e1"]).all():
        raise ValueError("E1 and E4 targets differ on shared rows")
    merged = merged.drop(columns="y_e1").merge(labels, on=["station_key", "fold"], how="left")
    merged["cluster"] = merged["cluster_id"].map(lambda c: "none" if pd.isna(c) else str(int(c)))
    return merged.drop(columns="cluster_id")


def score_all(
    merged: pd.DataFrame, names: Sequence[str], extra: Sequence[str] = ("cluster",)
) -> pd.DataFrame:
    """Per-slice metrics for every model present at that fold and horizon.

    Args:
        merged: Rows with ``pred_<model>`` columns and slice columns.
        names: Models; the first must be ``persistence`` (point forecast, no interval).
        extra: Further slice columns scored on their overall metrics (e.g. ``cluster``).

    Returns:
        Rows shaped like ``backtest_results``.
    """
    rows: list[dict[str, object]] = []
    pairs = merged[["fold", "horizon_min"]].drop_duplicates().itertuples(index=False)
    for fold, horizon in sorted((int(f), int(h)) for f, h in pairs):
        part = merged[(merged["fold"] == fold) & (merged["horizon_min"] == horizon)]
        present = [n for n in names if f"pred_{n}" in part and part[f"pred_{n}"].notna().all()]
        rows += score_slices(part, present, fold, horizon, present[1:])
        for kind in extra:
            for value, sub in part.groupby(kind):
                for rec in score_slices(sub, present, fold, horizon, present[1:]):
                    if rec["slice_kind"] == "overall":
                        rows.append(rec | {"slice_kind": kind, "slice_value": str(value)})
    return pd.DataFrame(rows)


def delta_table(results: pd.DataFrame, names: Sequence[str], horizon: int) -> list[str]:
    """Markdown rows: MAE of A and ΔMAE (B - A) per slice at one horizon (mean over folds)."""
    part = results[results.horizon_min == horizon]
    mae = part.groupby(["slice_kind", "slice_value", "model_name"])["mae"].mean()
    n = part[part.model_name == "lgbm_global"].groupby(["slice_kind", "slice_value"])["n"].sum()
    lines = []
    for kind in ("overall", *SLICES):
        values = sorted({v for (k, v, _) in mae.index if k == kind})
        for value in values:
            a = float(mae[(kind, value, "lgbm_global")])
            deltas = [f"{float(mae[(kind, value, m)]) - a:+.3f}" for m in names]
            lines.append(
                f"| {kind} | {value} | {int(n[(kind, value)])} | {a:.3f} | "
                + " | ".join(deltas)
                + " |"
            )
    return lines


def render_section(
    run_id: str,
    e1_run: str,
    e3_run: str,
    folds: Sequence[Fold],
    radii: Mapping[int, Sequence[float]],
    k: int,
    results: pd.DataFrame,
) -> str:
    """The E4 section of ``reports/experiments.md``."""
    summary = summarise(results)
    plan = "; ".join(f"+{h}: " + " / ".join(f"{int(r)} m" for r in rs) for h, rs in radii.items())
    lines = [
        "## E4 — Spatial features (A: no spatial vs B: + neighbours)",
        "",
        generated_line(run_id, folds[0].test_start, folds[-1].test_end),
        "",
        f"A = `lgbm_global` from E1 run `{e1_run}` (same folds, rows and training). B = the same "
        f"model plus PRD 10.5 neighbour features: the {k} nearest stations within the radius "
        "(haversine); neighbours' mean occupancy ratio and mean change over the last hour, "
        "neighbours with 0 bikes, total bikes at every station within the radius, inverse-"
        "distance-weighted mean ratio; all read at or before the issue time. Scored on rows "
        f"common to E1 and E4. Cluster slice: E3 run `{e3_run}`, labels fitted in-fold. "
        f"Radii per horizon (owner decision 2026-10-30, to fit the compute budget): {plan}. "
        "**No weather.** Every radius run is reported; none is selected on the test weeks.",
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
    overall = results[results.slice_kind == "overall"]
    fold_mae = overall.pivot_table(
        index=["horizon_min", "fold"], columns="model_name", values="mae"
    )
    lines += ["", "Folds where B beats A (overall MAE), per horizon:", ""]
    for h, rs in radii.items():
        part = fold_mae.loc[h]
        names = [model_name(r) for r in rs]
        wins = [f"{m}: {int((part[m] < part['lgbm_global']).sum())}/{len(part)}" for m in names]
        lines.append(f"- +{h}: " + ", ".join(wins))
    for h, rs in radii.items():
        header = " | ".join(f"Δ {int(r)} m" for r in rs)
        lines += [
            "",
            f"ΔMAE (B - A, bikes; negative = B better) by slice at +{h}, mean over folds:",
            "",
            f"| slice | value | rows | MAE A | {header} |",
            "|---|---|---:|---:|" + "---:|" * len(rs),
            *delta_table(results, [model_name(r) for r in rs], h),
        ]
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    """``make backtest E=E4`` (``--folds N``, ``--horizons``, ``--radii`` for timing runs)."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--folds", type=int, default=None)
    parser.add_argument("--horizons", type=str, default=None, help="e.g. 60 or 30,60")
    parser.add_argument("--radii", type=str, default=None, help="e.g. 600 or 400,800")
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
    spatial = cfg.spatial
    sweep = [float(r) for r in args.radii.split(",")] if args.radii else spatial.e4_radii_m
    radii = {
        h: sweep if h == spatial.e4_sweep_horizon_min else [spatial.neighbour_radius_m]
        for h in horizons
    }
    k = spatial.neighbour_k
    all_radii = sorted({r for rs in radii.values() for r in rs})
    setup_mlflow("E1")
    e1_run, e1_file = latest_run("E1", "predictions_file")
    setup_mlflow("E3")
    e3_run, e3_file = latest_run("E3", "fold_labels_file")
    setup_mlflow(EXPERIMENT)
    commit = git_commit()
    with mlflow.start_run(run_name="e4") as active:
        run_id = active.info.run_id
        mlflow.log_params(
            {
                "radii_m": "; ".join(
                    f"{h}:" + ",".join(str(int(r)) for r in rs) for h, rs in radii.items()
                ),
                "neighbour_k": k,
                "horizons": ",".join(map(str, horizons)),
                "n_folds": len(folds),
                "baseline_e1_run": e1_run,
                "cluster_e3_run": e3_run,
                "git_commit": commit,
                "data_source": "hist_b",
            }
        )
        outcomes = run(engine, folds, gaps, radii, k)
        scored = pd.concat([o.scored for o in outcomes], ignore_index=True)
        merged = attach_baseline(scored, pd.read_parquet(e1_file), pd.read_parquet(e3_file))
        names = ["persistence", "lgbm_global", *[model_name(r) for r in all_radii]]
        results = score_all(merged, names)
        summary = summarise(results)
        for rec in summary.to_dict("records"):
            key = f"{rec['model_name']}_h{rec['horizon_min']}"
            mlflow.log_metric(f"mae_{key}", float(rec["mae"]))
            if not pd.isna(rec["coverage_80"]):
                mlflow.log_metric(f"coverage80_{key}", float(rec["coverage_80"]))
        mlflow.log_metric("rows_merged", len(merged))
        mlflow.log_metric("rows_e4_common", len(scored))
        mlflow.log_text(results.to_csv(index=False), "results.csv")
        keep = [c for c in merged.columns if c.startswith(("pred_", "p10_", "p90_"))]
        path = get_env_settings().data_dir / "processed" / f"e4_predictions_{run_id}.parquet"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        merged[[*KEYS, "y", "cluster", *keep]].to_parquet(path, index=False)
        mlflow.log_param("predictions_file", str(path))
        stored = store_results(engine, run_id, EXPERIMENT, results)
    if args.folds is None and args.horizons is None and args.radii is None:
        section = render_section(run_id, e1_run, e3_run, folds, radii, k, results)
        replace_section(REPORTS / "experiments.md", EXPERIMENT, section)
    log.info("e4_done", run_id=run_id, rows=len(merged), results_rows=stored)


if __name__ == "__main__":
    main()
