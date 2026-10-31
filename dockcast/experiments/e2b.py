"""E2b — low-data stations simulated by truncating training histories (M9 owner decision).

``make backtest E=E2b``. In E2 almost every Format B station has the full history, so the
PRD's "bottom quarter by training rows" barely separates anything. Here a fixed, seeded quarter
of stations (``short``) keeps only its last :data:`TRAIN_DAYS` days of training issue times
before each fold's validation week: their states before ``valid_start - TRAIN_DAYS - LOOKBACK``
are removed from the panel, so lags, the station x hour encoding and Prophet see the short
history too. The validation week and the test window are unchanged.

Every model is retrained on the truncated data (``lgbm_global`` cannot be read from E1).
Cluster labels are E3's in-fold labels, fitted on the full pre-fold history: a real new station
would have a less certain cluster. Writes MLflow (experiment ``E2``, run name ``e2b``),
``backtest_results`` (experiment ``E2b``), ``data/processed/e2b_predictions_<run>.parquet``,
the E2b section of ``reports/experiments.md`` and ``reports/figures/e2b_short_history.png``.
"""

import argparse
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

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
from dockcast.evaluation.training import LOOKBACK, VALID_WINDOW, prepare_fold
from dockcast.experiments.e1 import b_span, default_folds, reference_tables
from dockcast.experiments.e2 import (
    COMPARED,
    MODELS,
    SLICES,
    cluster_groups,
    fold_wins,
    plot_low_data,
    slice_mae,
)
from dockcast.experiments.e4 import KEYS, latest_run, score_all
from dockcast.features.matrix import feature_columns
from dockcast.models.base import Forecaster
from dockcast.models.baselines import Persistence
from dockcast.models.lgbm_quantile import LgbmQuantile
from dockcast.models.partitioned import PartitionedLgbm
from dockcast.models.prophet_model import ProphetStation
from dockcast.quality.gaps import Gap, load_gaps
from dockcast.targets.regression import load_panel
from dockcast.tracking import setup_mlflow

log = structlog.get_logger(job="e2b")
EXPERIMENT = "E2b"
MLFLOW_EXPERIMENT = "E2"
FIGURES = REPORTS / "figures"
SHORT_SHARE = 0.25
TRAIN_DAYS = 28
SEED = 0
E2B_SLICES = tuple("history" if s == "data_amount" else s for s in SLICES)


@dataclass(frozen=True)
class ShortInfo:
    """Training-row counts of short and full-history stations for one fold and horizon."""

    fold: int
    horizon_min: int
    short: int
    short_min_rows: int
    short_max_rows: int
    full_min_rows: int


def short_history_stations(
    stations: Sequence[int], share: float = SHORT_SHARE, seed: int = SEED
) -> list[int]:
    """A seeded random ``share`` of stations (same set in every fold), sorted.

    Args:
        stations: Station keys.
        share: Fraction to pick (rounded to the nearest station, at least one).
        seed: Random seed.

    Returns:
        Picked station keys.
    """
    keys = sorted(int(s) for s in stations)
    n_short = max(1, round(len(keys) * share))
    picked = np.random.default_rng(seed).choice(keys, size=n_short, replace=False)
    return sorted(int(s) for s in picked)


def history_start(fold: Fold, days: int = TRAIN_DAYS) -> pd.Timestamp:
    """First state kept for short stations: ``days`` of training plus the lag lookback."""
    valid_start = pd.Timestamp(fold.train_end) - VALID_WINDOW
    return valid_start - timedelta(days=days) - LOOKBACK


def truncate_panel(panel: pd.DataFrame, short: Sequence[int], start: pd.Timestamp) -> pd.DataFrame:
    """Drop states of ``short`` stations before ``start``; other stations are untouched."""
    drop = panel["station_key"].isin(list(short)) & (panel["state_ts"] < start)
    return panel[~drop].reset_index(drop=True)


def drop_warmup(train: pd.DataFrame, short: Sequence[int], start: pd.Timestamp) -> pd.DataFrame:
    """Drop short stations' training rows issued before their lag lookback is filled."""
    drop = train["station_key"].isin(list(short)) & (train["issued_at"] < start + LOOKBACK)
    return train[~drop].reset_index(drop=True)


def short_summary(train: pd.DataFrame, short: Sequence[int], fold: int, horizon: int) -> ShortInfo:
    """Training-row counts behind the short / full split, for the report."""
    counts = train.groupby("station_key").size()
    is_short = counts.index.isin(list(short))
    return ShortInfo(
        fold,
        horizon,
        int(is_short.sum()),
        int(counts[is_short].min()),
        int(counts[is_short].max()),
        int(counts[~is_short].min()),
    )


def make_models(
    groups: dict[int, int], stations: Sequence[int], prophet: ProphetStation
) -> list[Forecaster]:
    """Persistence, the global and partitioned LightGBMs and Prophet, all retrained."""
    cols = feature_columns()
    return [
        Persistence(),
        LgbmQuantile(cols, stations, num_threads=10),
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
) -> tuple[list[FoldOutcome], list[ShortInfo], list[int]]:
    """Truncate, train and score every fold and horizon."""
    data_start, _ = b_span(engine)
    calendar, info = reference_tables(engine)
    holidays = [
        d for d, h in zip(calendar["date"], calendar["is_public_holiday"], strict=True) if h
    ]
    full_panel = load_panel(engine, data_start, max(f.test_end for f in folds))
    short = short_history_stations([int(s) for s in full_panel["station_key"].unique()])
    outcomes: list[FoldOutcome] = []
    short_info: list[ShortInfo] = []
    for fold in folds:
        start = history_start(fold)
        panel = truncate_panel(
            full_panel[full_panel["state_ts"] <= pd.Timestamp(fold.test_end)], short, start
        )
        stations = sorted(int(s) for s in panel["station_key"].unique())
        started = time.monotonic()
        prophet = ProphetStation(holidays).fit_states(panel, pd.Timestamp(fold.train_end))
        log.info("prophet_fitted", fold=fold.fold, seconds=round(time.monotonic() - started))
        for horizon in horizons:
            started = time.monotonic()
            data = prepare_fold(panel, fold, horizon, gaps, calendar, info, data_start)
            data.train = drop_warmup(data.train, short, start)
            short_info.append(short_summary(data.train, short, fold.fold, horizon))
            models = make_models(cluster_groups(labels, fold.fold), stations, prophet)
            outcome = score_fold(data, fold, horizon, models, feature_columns())
            scored = outcome.scored
            scored["fold"], scored["horizon_min"] = fold.fold, horizon
            scored["history"] = np.where(scored["station_key"].isin(short), "short", "full")
            outcomes.append(outcome)
            log.info(
                "fold_scored",
                fold=fold.fold,
                horizon=horizon,
                common=outcome.rows_common,
                seconds=round(time.monotonic() - started),
            )
        del panel
    return outcomes, short_info, short


def attach_clusters(scored: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Add the in-fold E3 ``cluster`` slice column."""
    merged = scored.merge(labels, on=["station_key", "fold"], how="left")
    merged["cluster"] = merged["cluster_id"].map(lambda c: "none" if pd.isna(c) else str(int(c)))
    return merged.drop(columns="cluster_id")


def _fmt(value: float) -> str:
    return "—" if pd.isna(value) else f"{value:.3f}"


def render_section(
    run_id: str,
    e3_run: str,
    folds: Sequence[Fold],
    results: pd.DataFrame,
    short_info: Sequence[ShortInfo],
    short: Sequence[int],
) -> str:
    """The E2b section of ``reports/experiments.md``."""
    summary = summarise(results)
    rows = pd.DataFrame([vars(r) for r in short_info])
    lines = [
        "## E2b — Low-data stations by truncated history",
        "",
        generated_line(run_id, folds[0].test_start, folds[-1].test_end),
        "",
        "E2's bottom quarter by training rows barely differs from the other stations (every "
        f"Format B station has almost the full history). Here {len(short)} stations "
        f"({int(SHORT_SHARE * 100)}%, seeded random, the same in every fold) keep only their "
        f"last {TRAIN_DAYS} days of training before each fold's validation week: their earlier "
        "states are removed, so lags, the station x hour encoding and Prophet see the short "
        "history too. Validation week and test window are unchanged. Training rows per short "
        f"station: {int(rows['short_min_rows'].min())}-{int(rows['short_max_rows'].max())}; "
        f"per full-history station at least {int(rows['full_min_rows'].min())}. Every model, "
        "`lgbm_global` included, is retrained on this data, with E2's features, LightGBM "
        "defaults and early stopping. Clusters are E3 run "
        f"`{e3_run}`'s in-fold labels, fitted on the full pre-fold history (a real new station "
        "would have a less certain cluster). Short stations: "
        + ", ".join(map(str, short))
        + ". **No weather.**",
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
        "MAE by history, mean over folds (folds where the model beats `lgbm_global` on that "
        "slice in brackets):",
        "",
        "| horizon | model | all stations | short history | full history |",
        "|---:|---|---:|---:|---:|",
    ]
    frames = {
        "all": slice_mae(results, "overall", "all"),
        "short": slice_mae(results, "history", "short"),
        "full": slice_mae(results, "history", "full"),
    }
    wins = {
        "all": fold_wins(results, "overall", "all"),
        "short": fold_wins(results, "history", "short"),
        "full": fold_wins(results, "history", "full"),
    }
    n_folds = len(folds)
    for h in frames["all"].index:
        for m in MODELS[1:]:
            cells = []
            for key, frame in frames.items():
                text = _fmt(float(frame.loc[h, m]))
                if m in COMPARED:
                    text += f" ({int(wins[key].loc[h, m])}/{n_folds})"
                cells.append(text)
            lines.append(f"| +{h} | {m} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "![MAE on all stations and on short-history stations](figures/e2b_short_history.png)",
        "",
        "ΔMAE (model - `lgbm_global`, bikes; negative = better) by slice, mean over folds:",
        "",
        "| horizon | slice | value | MAE global | Δ per-station | Δ per-cluster | Δ Prophet |",
        "|---:|---|---|---:|---:|---:|---:|",
    ]
    mae = results.groupby(["horizon_min", "slice_kind", "slice_value", "model_name"])["mae"].mean()
    for h in sorted(results.horizon_min.unique()):
        for kind in E2B_SLICES:
            values = sorted({v for (hh, k, v, _) in mae.index if hh == h and k == kind})
            for value in values:
                base = float(mae[(h, kind, value, "lgbm_global")])
                deltas = [f"{float(mae[(h, kind, value, m)]) - base:+.3f}" for m in COMPARED]
                lines.append(
                    f"| +{h} | {kind} | {value} | {base:.3f} | " + " | ".join(deltas) + " |"
                )
    lines.append("")
    return "\n".join(lines)


def write_report(
    run_id: str,
    e3_run: str,
    folds: Sequence[Fold],
    results: pd.DataFrame,
    short_info: Sequence[ShortInfo],
    short: Sequence[int],
) -> None:
    """Write the E2b chart and report section."""
    plot_low_data(
        results,
        FIGURES / "e2b_short_history.png",
        "history",
        "short",
        f"Short-history stations ({TRAIN_DAYS} d)",
    )
    section = render_section(run_id, e3_run, folds, results, short_info, short)
    replace_section(REPORTS / "experiments.md", EXPERIMENT, section)


def render_run(run_id: str) -> None:
    """Re-render the report from a finished full E2b run's MLflow artifacts."""
    setup_mlflow(MLFLOW_EXPERIMENT)
    params = mlflow.get_run(run_id).data.params
    results = pd.read_csv(
        mlflow.artifacts.download_artifacts(run_id=run_id, artifact_path="results.csv")
    )
    results["slice_value"] = results["slice_value"].astype(str)
    info = pd.read_csv(
        mlflow.artifacts.download_artifacts(run_id=run_id, artifact_path="short_history.csv")
    )
    short_info = [
        ShortInfo(*(int(v) for v in row))
        for row in info[list(ShortInfo.__dataclass_fields__)].itertuples(index=False)
    ]
    short = [int(s) for s in params["short_stations"].split(",")]
    engine = make_engine()
    with Session(engine) as session:
        gaps = load_gaps(session)
    folds = default_folds(engine, gaps)[-int(params["n_folds"]) :]
    write_report(run_id, params["cluster_e3_run"], folds, results, short_info, short)
    log.info("e2b_rendered", run_id=run_id, run_commit=params["git_commit"])


def main(argv: Sequence[str] | None = None) -> None:
    """``make backtest E=E2b`` (``--folds N``, ``--horizons`` for timing runs).

    ``--render RUN_ID`` rebuilds the report section and chart from a finished run.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--folds", type=int, default=None)
    parser.add_argument("--horizons", type=str, default=None, help="e.g. 60 or 30,60")
    parser.add_argument("--render", type=str, default=None, help="MLflow run id to re-render")
    args = parser.parse_args(argv)
    if args.render:
        render_run(args.render)
        return
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
    setup_mlflow("E3")
    e3_run, e3_file = latest_run("E3", "fold_labels_file")
    labels = pd.read_parquet(e3_file)
    setup_mlflow(MLFLOW_EXPERIMENT)
    commit = git_commit()
    with mlflow.start_run(run_name="e2b") as active:
        run_id = active.info.run_id
        mlflow.log_params(
            {
                "models": ",".join(MODELS),
                "horizons": ",".join(map(str, horizons)),
                "n_folds": len(folds),
                "short_share": SHORT_SHARE,
                "train_days": TRAIN_DAYS,
                "seed": SEED,
                "cluster_e3_run": e3_run,
                "git_commit": commit,
                "data_source": "hist_b",
            }
        )
        outcomes, short_info, short = run(engine, folds, gaps, horizons, labels)
        mlflow.log_param("short_stations", ",".join(map(str, short)))
        scored = pd.concat([o.scored for o in outcomes], ignore_index=True)
        merged = attach_clusters(scored, labels)
        results = score_all(merged, MODELS, extra=("cluster", "history"))
        for rec in summarise(results).to_dict("records"):
            key = f"{rec['model_name']}_h{rec['horizon_min']}"
            mlflow.log_metric(f"mae_{key}", float(rec["mae"]))
            if not pd.isna(rec["coverage_80"]):
                mlflow.log_metric(f"coverage80_{key}", float(rec["coverage_80"]))
        mlflow.log_metric("rows_scored", len(merged))
        mlflow.log_text(results.to_csv(index=False), "results.csv")
        mlflow.log_text(
            pd.DataFrame([vars(r) for r in short_info]).to_csv(index=False), "short_history.csv"
        )
        keep = [c for c in merged.columns if c.startswith(("pred_", "p10_", "p90_"))]
        path = get_env_settings().data_dir / "processed" / f"e2b_predictions_{run_id}.parquet"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        merged[[*KEYS, "y", "cluster", "history", *keep]].to_parquet(path, index=False)
        mlflow.log_param("predictions_file", str(path))
        stored = store_results(engine, run_id, EXPERIMENT, results)
    if args.folds is None and args.horizons is None:
        write_report(run_id, e3_run, folds, results, short_info, short)
    log.info("e2b_done", run_id=run_id, rows=len(merged), results_rows=stored)


if __name__ == "__main__":
    main()
