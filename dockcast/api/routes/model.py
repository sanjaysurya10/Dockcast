"""Model metadata (PRD 15.1)."""

from fastapi import APIRouter, Request, Response
from sqlalchemy import Engine

from dockcast.api import queries
from dockcast.api.schemas import ChampionModel, ModelSummary

router = APIRouter()


@router.get("/model/summary", response_model=ModelSummary)
def model_summary(request: Request, response: Response) -> ModelSummary:
    """Champion versions, last retrain and their backtest metrics (with E1 run id)."""
    response.headers["Cache-Control"] = "public, max-age=3600"
    engine: Engine = request.app.state.engine
    with engine.connect() as conn:
        champions = [ChampionModel.model_validate(c) for c in queries.champions(conn)]
    last = max((c.trained_at for c in champions), default=None)
    return ModelSummary(champions=champions, last_retrain=last)
