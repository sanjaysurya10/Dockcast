"""``GET /health``."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from dockcast.api import queries
from dockcast.api.schemas import Health
from dockcast.config import load_project_config

router = APIRouter()


@router.get("/health", response_model=Health)
def get_health(request: Request, response: Response) -> Health:
    """Database reachability and freshness of the collector and the forecast job."""
    engine: Engine = request.app.state.engine
    response.headers["Cache-Control"] = "no-store"
    try:
        with engine.connect() as conn:
            run, issued = queries.health(conn)
    except SQLAlchemyError:
        response.status_code = 503
        return Health(status="degraded", db="error", last_collector_run=None,
                      last_forecast_issued_at=None)  # fmt: skip
    limit = timedelta(minutes=load_project_config().serving.stale_after_min)
    now = datetime.now(UTC)
    fresh = all(ts is not None and now - ts <= limit for ts in (run, issued))
    return Health(
        status="ok" if fresh else "degraded",
        db="ok",
        last_collector_run=run,
        last_forecast_issued_at=issued,
    )
