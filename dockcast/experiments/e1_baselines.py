"""E1 — ML vs baselines (PRD 14). M3 runs the baseline half: persistence and seasonal naive.

``make backtest E=E1``. Writes MLflow (experiment ``E1``), ``backtest_results``,
``reports/folds.json`` and the E1 section of ``reports/experiments.md``.
"""

import json
from collections.abc import Sequence
from datetime import timedelta

import mlflow
import pandas as pd
import structlog
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from dockcast.config import PROJECT_ROOT, load_project_config
from dockcast.db.engine import make_engine
from dockcast.evaluation.backtest import FoldOutcome, run_fold, summarise
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
from dockcast.features.build import SEASON
from dockcast.models.base import Forecaster
from dockcast.models.baselines import Persistence, SeasonalNaive7d
from dockcast.quality.gaps import Gap, load_gaps
from dockcast.targets.regression import load_panel
from dockcast.tracking import setup_mlflow

log = structlog.get_logger(job="e1")
EXPERIMENT = "E1"


def default_folds(engine: Engine, gaps: Sequence[Gap]) -> list[Fold]:
    """PRD 13.1 folds on Format B: end at its last complete month, avoid gaps.

    Args:
        engine: Database engine.
        gaps: Data gaps.

    Returns:
        Folds, oldest first.
    """
    cfg = load_project_config().backtest
    with engine.connect() as conn:
        lo, hi = conn.execute(
            text(
                "SELECT min(observed_at), max(observed_at) FROM station_status_raw "
                "WHERE source = 'hist_b'"
            )
        ).one()
    end = last_complete_month_end(hi, timedelta(minutes=30))
    return rolling_origin_folds(lo, end, gaps, cfg.n_folds, cfg.test_window_days, cfg.gap_min)


def run(
    engine: Engine,
    folds: Sequence[Fold],
    gaps: Sequence[Gap],
    horizons: Sequence[int],
    models: Sequence[Forecaster],
) -> tuple[list[FoldOutcome], pd.DataFrame]:
    """Run every fold and horizon.

    Args:
        engine: Database engine.
        folds: Folds.
        gaps: Data gaps.
        horizons: Horizons in minutes.
        models: Forecasters.

    Returns:
        Fold outcomes and the concatenated per-slice results.
    """
    outcomes: list[FoldOutcome] = []
    for fold in folds:
        panel = load_panel(engine, fold.test_start - SEASON - timedelta(hours=1), fold.test_end)
        for horizon in horizons:
            outcome = run_fold(panel, fold, horizon, models, gaps)
            log.info(
                "fold_scored",
                fold=fold.fold,
                horizon=horizon,
                rows=outcome.rows_total,
                target_ok=outcome.rows_target_ok,
                common=outcome.rows_common,
            )
            outcomes.append(outcome)
    results = pd.DataFrame([m for o in outcomes for m in o.metrics])
    return outcomes, results


def render_section(
    run_id: str, folds: Sequence[Fold], outcomes: Sequence[FoldOutcome], results: pd.DataFrame
) -> str:
    """The E1 section of ``reports/experiments.md``.

    Args:
        run_id: MLflow run id.
        folds: Folds.
        outcomes: Fold outcomes.
        results: Per-slice results.

    Returns:
        Markdown.
    """
    summary = summarise(results)
    lines = [
        "## E1 — Baselines (persistence, seasonal naive 7 d)",
        "",
        generated_line(run_id, folds[0].test_start - SEASON, folds[-1].test_end),
        "",
        "Rolling origin, 8 test weeks, Format B (PRD 9.1a, 13.1); fold dates in "
        "`reports/folds.json`. Targets: state at t + h (bucket ending at t + h); closed, imputed "
        "and flat-lined targets excluded; all models scored on common rows. MAE/RMSE in bikes; "
        "values are means over folds (± std of fold MAE). No weather is used by these models.",
        "",
        "| horizon | model | MAE | ± | RMSE | MASE | bias | rows |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in summary.itertuples(index=False):
        lines.append(
            f"| +{r.horizon_min} | {r.model_name} | {r.mae:.3f} | {r.mae_std:.3f} | {r.rmse:.3f} "
            f"| {r.mase:.3f} | {r.bias:+.3f} | {r.n} |"
        )
    rows = (
        pd.DataFrame(
            [(o.horizon_min, o.rows_total, o.rows_target_ok, o.rows_common) for o in outcomes],
            columns=["horizon", "total", "target_ok", "common"],
        )
        .groupby("horizon")
        .sum()
    )
    lines += [
        "",
        "Rows per horizon (all folds): issue times x stations / valid target / common:",
        "",
    ]
    lines += [f"- +{h}: {r.total} / {r.target_ok} / {r.common}" for h, r in rows.iterrows()]
    lines += ["", "Persistence MAE by slice at +60 (mean over folds):", ""]
    p60 = results[(results.model_name == "persistence") & (results.horizon_min == 60)]
    for kind in ("rush_hour", "weekend", "capacity_band", "rebalance"):
        part = p60[p60.slice_kind == kind].groupby("slice_value")["mae"].mean()
        lines.append(f"- {kind}: " + ", ".join(f"{k} {v:.3f}" for k, v in part.items()))
    fold_lines = [
        f"| {f.fold} | {f.test_start:%Y-%m-%d %H:%M} | {f.test_end:%Y-%m-%d %H:%M} |" for f in folds
    ]
    lines += ["", "| fold | test start (UTC) | test end (UTC) |", "|---:|---|---|", *fold_lines, ""]
    return "\n".join(lines)


def main() -> None:
    """``make backtest E=E1``."""
    engine = make_engine()
    with Session(engine) as session:
        gaps = load_gaps(session)
    folds = default_folds(engine, gaps)
    horizons = load_project_config().forecast.horizons_min
    models: list[Forecaster] = [Persistence(), SeasonalNaive7d()]
    setup_mlflow(EXPERIMENT)
    with mlflow.start_run(run_name="e1_baselines") as active:
        run_id = active.info.run_id
        outcomes, results = run(engine, folds, gaps, horizons, models)
        summary = summarise(results)
        mlflow.log_params(
            {
                "models": ",".join(m.name for m in models),
                "horizons": ",".join(map(str, horizons)),
                "n_folds": len(folds),
                "test_start": folds[0].test_start.isoformat(),
                "test_end": folds[-1].test_end.isoformat(),
                "git_commit": git_commit(),
                "data_source": "hist_b",
            }
        )
        for rec in summary.to_dict("records"):
            key = f"{rec['model_name']}_h{rec['horizon_min']}"
            mlflow.log_metric(f"mae_{key}", float(rec["mae"]))
            mlflow.log_metric(f"mase_{key}", float(rec["mase"]))
        mlflow.log_text(folds_json(folds), "folds.json")
        mlflow.log_text(results.to_csv(index=False), "results.csv")
        mlflow.log_text(
            json.dumps(summary.to_dict("records"), indent=1, default=str), "summary.json"
        )
        stored = store_results(engine, run_id, EXPERIMENT, results)
    write_folds(folds)
    replace_section(
        REPORTS / "experiments.md", EXPERIMENT, render_section(run_id, folds, outcomes, results)
    )
    log.info("e1_done", run_id=run_id, results_rows=stored, report=str(PROJECT_ROOT / "reports"))


if __name__ == "__main__":
    main()
