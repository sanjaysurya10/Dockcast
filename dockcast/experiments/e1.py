"""E1 — ML vs baselines (PRD 14): persistence, seasonal naive 7 d, ridge, LightGBM quantiles.

``make backtest E=E1``. Writes MLflow (experiment ``E1``), ``backtest_results``,
``reports/folds.json``, the E1 section of ``reports/experiments.md`` and the scored test rows
(``data/processed/e1_predictions_<run>.parquet``) used by the error analysis.
"""

import argparse
import json
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

import mlflow
import pandas as pd
import structlog
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from dockcast.config import get_env_settings, load_project_config
from dockcast.db.engine import make_engine
from dockcast.evaluation.backtest import FoldOutcome, score_fold, summarise
from dockcast.evaluation.champion import select_champions
from dockcast.evaluation.reports import (
    REPORTS,
    folds_json,
    generated_line,
    git_commit,
    replace_section,
    store_results,
    write_folds,
)
from dockcast.evaluation.splits import Fold, last_complete_month_end, rolling_origin_folds
from dockcast.evaluation.training import prepare_fold
from dockcast.features.matrix import feature_columns
from dockcast.models.base import Forecaster
from dockcast.models.baselines import Persistence, SeasonalNaive7d
from dockcast.models.lgbm_quantile import LgbmQuantile
from dockcast.models.linear import RidgeForecaster
from dockcast.quality.gaps import Gap, load_gaps
from dockcast.targets.regression import load_panel
from dockcast.tracking import setup_mlflow

log = structlog.get_logger(job="e1")
EXPERIMENT = "E1"
KEEP_COLUMNS = [
    "station_key", "issued_at", "target_ts", "y", "capacity", "rebalance_flag", "change_4",
    "hour", "weekend", "rush_hour", "capacity_band",
]  # fmt: skip


def b_span(engine: Engine) -> tuple[datetime, datetime]:
    """First and last Format B observation."""
    with engine.connect() as conn:
        lo, hi = conn.execute(
            text(
                "SELECT min(observed_at), max(observed_at) FROM station_status_raw "
                "WHERE source = 'hist_b'"
            )
        ).one()
    return lo, hi


def default_folds(engine: Engine, gaps: Sequence[Gap]) -> list[Fold]:
    """PRD 13.1 folds on Format B: end at its last complete month, avoid gaps."""
    cfg = load_project_config().backtest
    lo, hi = b_span(engine)
    end = last_complete_month_end(hi, timedelta(minutes=30))
    return rolling_origin_folds(lo, end, gaps, cfg.n_folds, cfg.test_window_days, cfg.gap_min)


def reference_tables(engine: Engine) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``calendar_days`` and station coordinates."""
    with engine.connect() as conn:
        cal = pd.read_sql(
            text("SELECT date, is_public_holiday, is_school_term, is_uni_term FROM calendar_days"),
            conn,
        )
        info = pd.read_sql(text("SELECT station_key, lat, lon FROM stations"), conn)
    return cal, info


def make_models(stations: Sequence[int]) -> list[Forecaster]:
    """The four E1 models with the full v1 feature set."""
    cols = feature_columns()
    return [
        Persistence(),
        SeasonalNaive7d(),
        RidgeForecaster(cols),
        LgbmQuantile(cols, stations, num_threads=10),
    ]


def run(
    engine: Engine,
    folds: Sequence[Fold],
    gaps: Sequence[Gap],
    horizons: Sequence[int],
    model_factory: Callable[[Sequence[int]], list[Forecaster]],
) -> tuple[list[FoldOutcome], pd.DataFrame, dict[str, int]]:
    """Train and score every fold and horizon.

    Returns:
        Fold outcomes, per-slice results, and LightGBM best iterations per fold/horizon/q.
    """
    data_start, _ = b_span(engine)
    calendar, info = reference_tables(engine)
    outcomes: list[FoldOutcome] = []
    iterations: dict[str, int] = {}
    for fold in folds:
        panel = load_panel(engine, data_start, fold.test_end)
        stations = sorted(int(s) for s in panel["station_key"].unique())
        for horizon in horizons:
            started = time.monotonic()
            data = prepare_fold(panel, fold, horizon, gaps, calendar, info, data_start)
            models = model_factory(stations)
            outcome = score_fold(data, fold, horizon, models, feature_columns())
            for m in models:
                for q, it in getattr(m, "best_iterations", {}).items():
                    iterations[f"f{fold.fold}_h{horizon}_q{q}"] = it
            log.info(
                "fold_scored",
                fold=fold.fold,
                horizon=horizon,
                train=len(data.train),
                valid=len(data.valid),
                common=outcome.rows_common,
                seconds=round(time.monotonic() - started),
            )
            outcomes.append(outcome)
        del panel
    results = pd.DataFrame([m for o in outcomes for m in o.metrics])
    return outcomes, results, iterations


def render_section(
    run_id: str,
    folds: Sequence[Fold],
    outcomes: Sequence[FoldOutcome],
    results: pd.DataFrame,
    champions: pd.DataFrame,
) -> str:
    """The E1 section of ``reports/experiments.md``."""
    summary = summarise(results)
    lines = [
        "## E1 — ML vs baselines (persistence, seasonal naive 7 d, ridge, LightGBM quantiles)",
        "",
        generated_line(run_id, folds[0].test_start - timedelta(days=7), folds[-1].test_end),
        "",
        "Rolling origin, 8 test weeks on Format B (PRD 9.1a, 13.1; `reports/folds.json`). "
        "Training: hourly issue times on all Format B history before each fold, early stopping "
        "on the last training week (15-min). Targets: state at t + h; closed, imputed and "
        "flat-lined targets excluded; every model scored on the same common rows. Features: "
        "lags, rolling, seasonal, calendar, station static (PRD 10.2-10.4); **no weather**. "
        "Means over folds (± std of fold MAE). Coverage = share inside P10-P90 (target 80 %).",
        "",
        "| horizon | model | MAE | ± | RMSE | MASE | bias | coverage P10-P90 | width | rows |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rec in summary.to_dict("records"):
        cov = "—" if pd.isna(rec["coverage_80"]) else f"{float(rec['coverage_80']):.3f}"
        width = "—" if pd.isna(rec["interval_width"]) else f"{float(rec['interval_width']):.2f}"
        lines.append(
            f"| +{rec['horizon_min']} | {rec['model_name']} | {float(rec['mae']):.3f} | "
            f"{float(rec['mae_std']):.3f} | {float(rec['rmse']):.3f} | {float(rec['mase']):.3f} | "
            f"{float(rec['bias']):+.3f} | {cov} | {width} | {rec['n']} |"
        )
    lines += ["", "**Champion per horizon (PRD 12.5):**", ""]
    for c in champions.to_dict("records"):
        if c["champion"] is None:
            lines.append(f"- +{c['horizon_min']}: none — {c['reason']}")
        else:
            lines.append(
                f"- +{c['horizon_min']}: `{c['champion']}` (MAE {float(c['mae']):.3f}, "
                f"coverage {float(c['coverage_80']):.3f}; {c['reason']})"
            )
    h60 = {str(r["model_name"]): r for r in summary[summary.horizon_min == 60].to_dict("records")}
    if "persistence" in h60 and "lgbm_global" in h60:
        target = 0.85 * float(h60["persistence"]["mae"])
        got = float(h60["lgbm_global"]["mae"])
        verdict = "met" if got <= target else "not met"
        lines += [
            "",
            f"**S1** (+60 MAE <= 0.85 x persistence = {target:.3f}): lgbm_global {got:.3f} -> "
            f"**{verdict}** (MASE {float(h60['lgbm_global']['mase']):.3f}).",
        ]
    rows = (
        pd.DataFrame(
            [(o.horizon_min, o.rows_total, o.rows_target_ok, o.rows_common) for o in outcomes],
            columns=["horizon", "total", "target_ok", "common"],
        )
        .groupby("horizon")
        .sum()
    )
    lines += ["", "Test rows per horizon (all folds), issued / valid target / common:", ""]
    lines += [f"- +{h}: {r.total} / {r.target_ok} / {r.common}" for h, r in rows.iterrows()]
    lines += ["", "MAE by slice at +60 (mean over folds):", ""]
    lines += ["| slice | value | " + " | ".join(summary.model_name.unique()) + " |"]
    lines += ["|---|---|" + "---:|" * summary.model_name.nunique()]
    r60 = results[results.horizon_min == 60]
    for kind in ("rush_hour", "weekend", "capacity_band", "rebalance"):
        part = r60[r60.slice_kind == kind].groupby(["slice_value", "model_name"])["mae"].mean()
        for value in sorted(part.index.get_level_values(0).unique()):
            names = summary.model_name.unique()
            cells = [f"{float(part.get((value, m), float('nan'))):.3f}" for m in names]
            lines.append(f"| {kind} | {value} | " + " | ".join(cells) + " |")
    fold_lines = [
        f"| {f.fold} | {f.train_end:%Y-%m-%d %H:%M} | {f.test_start:%Y-%m-%d %H:%M} | "
        f"{f.test_end:%Y-%m-%d %H:%M} |"
        for f in folds
    ]
    lines += [
        "",
        "| fold | train end (UTC) | test start (UTC) | test end (UTC) |",
        "|---:|---|---|---|",
        *fold_lines,
        "",
    ]
    return "\n".join(lines)


def save_predictions(outcomes: Sequence[FoldOutcome], run_id: str) -> str:
    """Write scored common rows (all folds, horizons, models) for the error analysis."""
    frames = []
    for o in outcomes:
        cols = [c for c in o.scored.columns if c.startswith(("pred_", "p10_", "p90_"))]
        part = o.scored[KEEP_COLUMNS + cols].copy()
        part["fold"], part["horizon_min"] = o.fold, o.horizon_min
        frames.append(part)
    path = get_env_settings().data_dir / "processed" / f"e1_predictions_{run_id}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(frames, ignore_index=True).to_parquet(path, index=False)
    return str(path)


def main(argv: Sequence[str] | None = None) -> None:
    """``make backtest E=E1`` (``--folds N`` runs the last N folds, for timing)."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--folds", type=int, default=None)
    parser.add_argument("--horizons", type=str, default=None, help="e.g. 60 or 30,60")
    args = parser.parse_args(argv)
    engine = make_engine()
    with Session(engine) as session:
        gaps = load_gaps(session)
    folds = default_folds(engine, gaps)
    if args.folds:
        folds = folds[-args.folds :]
    horizons = (
        [int(h) for h in args.horizons.split(",")]
        if args.horizons
        else load_project_config().forecast.horizons_min
    )
    setup_mlflow(EXPERIMENT)
    with mlflow.start_run(run_name="e1") as active:
        run_id = active.info.run_id
        outcomes, results, iterations = run(engine, folds, gaps, horizons, make_models)
        summary = summarise(results)
        champions = select_champions(summary)
        mlflow.log_params(
            {
                "models": "persistence,seasonal_naive_7d,ridge,lgbm_global",
                "horizons": ",".join(map(str, horizons)),
                "n_folds": len(folds),
                "test_start": folds[0].test_start.isoformat(),
                "test_end": folds[-1].test_end.isoformat(),
                "git_commit": git_commit(),
                "data_source": "hist_b",
                "train_rows": "hourly issue times; valid = last training week (15-min)",
                "features": ",".join(feature_columns()),
            }
        )
        for rec in summary.to_dict("records"):
            key = f"{rec['model_name']}_h{rec['horizon_min']}"
            mlflow.log_metric(f"mae_{key}", float(rec["mae"]))
            mlflow.log_metric(f"mase_{key}", float(rec["mase"]))
            if not pd.isna(rec["coverage_80"]):
                mlflow.log_metric(f"coverage80_{key}", float(rec["coverage_80"]))
        mlflow.log_text(folds_json(folds), "folds.json")
        mlflow.log_text(results.to_csv(index=False), "results.csv")
        mlflow.log_text(json.dumps(iterations, indent=1), "lgbm_best_iterations.json")
        mlflow.log_text(champions.to_csv(index=False), "champions.csv")
        predictions = save_predictions(outcomes, run_id)
        mlflow.log_param("predictions_file", predictions)
        stored = store_results(engine, run_id, EXPERIMENT, results)
    if args.folds is None and args.horizons is None:
        write_folds(folds)
        section = render_section(run_id, folds, outcomes, results, champions)
        replace_section(REPORTS / "experiments.md", EXPERIMENT, section)
    log.info("e1_done", run_id=run_id, results_rows=stored, predictions=predictions)


if __name__ == "__main__":
    main()
