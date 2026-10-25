from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from dockcast.db.models import WeatherHourly
from dockcast.db.queries import ensure_city
from dockcast.ingest.weather_forecast import parse_locationforecast, store_forecast
from dockcast.ingest.weather_history import parse_station_csv, store_observed
from tests.integration.test_ingest_db import CITY

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parent.parent / "fixtures" / "weather"


def _count(engine: Engine, kind: str) -> int:
    with Session(engine) as session:
        stmt = select(func.count()).select_from(WeatherHourly).where(WeatherHourly.kind == kind)
        return int(session.scalar(stmt) or 0)


def test_observed_upsert_is_idempotent_with_null_issued_at(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        ensure_city(session, CITY)
        session.commit()
    frame = parse_station_csv((FIXTURES / "hly532_sample.csv").read_text(encoding="utf-8"))
    assert store_observed(db_engine, "dublin", frame) == 8
    assert store_observed(db_engine, "dublin", frame) == 8  # updated in place, not duplicated
    assert _count(db_engine, "observed") == len(frame) == 8


def test_forecast_issue_stored_once(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        ensure_city(session, CITY)
        session.commit()
    issue = parse_locationforecast(
        (FIXTURES / "locationforecast_sample.xml").read_text(encoding="utf-8")
    )
    first = store_forecast(db_engine, "dublin", issue)
    again = store_forecast(db_engine, "dublin", issue)
    assert first == len(issue.frame) > 0 and again == 0
    assert _count(db_engine, "forecast") == first
