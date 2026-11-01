"""Model metadata, backtest results and error analysis (PRD 15.1, 16.5)."""

import json

from fastapi import APIRouter, Request, Response
from sqlalchemy import Engine

from dockcast.api import queries
from dockcast.api.errors import ApiError
from dockcast.api.schemas import (
    Backtest,
    BacktestRow,
    ChampionModel,
    DataHealth,
    ErrorAnalysis,
    ModelSummary,
)
from dockcast.config import get_env_settings, load_project_config

router = APIRouter()

UPTIME_DAYS = 7
SLICE_KINDS = {"overall", "hour", "weekend", "rush_hour", "capacity_band", "rebalance", "dow"}
ERROR_ANALYSIS_FILE = "error_analysis.json"


def _engine(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


@router.get("/model/summary", response_model=ModelSummary)
def model_summary(request: Request, response: Response) -> ModelSummary:
    """Champion versions, last retrain, backtest metrics (with E1 run id) and data health."""
    response.headers["Cache-Control"] = "public, max-age=3600"
    expected = UPTIME_DAYS * 86_400 // load_project_config().collector.poll_interval_s
    with _engine(request).connect() as conn:
        champions = [ChampionModel.model_validate(c) for c in queries.champions(conn)]
        polls = queries.collector_polls(conn, UPTIME_DAYS)
        modelled = queries.stations_modelled(conn)
    last = max((c.trained_at for c in champions), default=None)
    health = DataHealth(
        collector_polls_7d=polls,
        expected_polls_7d=expected,
        collector_uptime_7d=min(1.0, polls / expected),
        stations_modelled=modelled,
        train_end=max((c.train_end for c in champions), default=None),
    )
    return ModelSummary(champions=champions, last_retrain=last, data_health=health)


@router.get("/model/backtest", response_model=Backtest)
def model_backtest(
    request: Request,
    response: Response,
    experiment: str = "E1",
    slice_kind: str = "overall",
    run_id: str | None = None,
) -> Backtest:
    """Rows from ``backtest_results``, averaged over folds (default: the newest full run)."""
    if slice_kind not in SLICE_KINDS:
        raise ApiError(422, "invalid_request", f"slice_kind must be one of {sorted(SLICE_KINDS)}")
    with _engine(request).connect() as conn:
        run = run_id or queries.default_run(conn, experiment)
        rows = queries.backtest(conn, experiment, run, slice_kind) if run else []
    if not run or not rows:
        raise ApiError(404, "backtest_not_found", f"no backtest rows for {experiment}")
    response.headers["Cache-Control"] = "public, max-age=3600"
    return Backtest(
        experiment=experiment,
        run_id=run,
        slice_kind=slice_kind,
        rows=[BacktestRow.model_validate(r) for r in rows],
    )


@router.get("/model/error-analysis", response_model=ErrorAnalysis)
def model_error_analysis(response: Response) -> ErrorAnalysis:
    """Slices pre-computed by ``make error-analysis`` (``reports/error_analysis.json``)."""
    path = get_env_settings().reports_dir / ERROR_ANALYSIS_FILE
    if not path.exists():
        raise ApiError(404, "error_analysis_not_found", "run `make error-analysis` first")
    response.headers["Cache-Control"] = "public, max-age=3600"
    return ErrorAnalysis.model_validate(json.loads(path.read_text(encoding="utf-8")))
