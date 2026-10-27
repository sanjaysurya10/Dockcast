"""One forecast cycle end to end (PRD 19.4): live raw rows -> 15-min grid -> forecasts table."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from dockcast.db.queries import StationRecord, ensure_city, insert_status_rows, upsert_stations
from dockcast.serving.bundle import Bundle
from dockcast.serving.forecast import register, run_cycle
from tests.integration.test_ingest_db import CITY
from tests.unit.test_serving import tiny_bundle

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 26, 12, 1, 30, tzinfo=UTC)


def seed_live(engine: Engine, until: datetime, hours: int = 30) -> dict[str, int]:
    """Two stations ('A', 'B' -> served keys) with a live poll every 5 min until ``until``."""
    with Session(engine) as session:
        ensure_city(session, CITY)
        keys = upsert_stations(
            session,
            "dublin",
            [
                StationRecord("B", "SECOND", 53.35, -6.27, 30),
                StationRecord("A", "FIRST", 53.34, -6.26, 30),
            ],
            until - timedelta(days=30),
        )
        session.execute(
            text(
                "INSERT INTO station_capacity (station_key, valid_from, capacity, source) "
                "SELECT station_key, :start, 30, 'test' FROM stations"
            ),
            {"start": until - timedelta(days=30)},
        )
        polls = [until - timedelta(minutes=5 * i) for i in range(hours * 12)]
        insert_status_rows(
            session,
            [
                {
                    "station_key": key,
                    "observed_at": ts,
                    "last_reported": None,
                    "bikes_available": (ts.hour + i) % 20,
                    "docks_available": 30 - (ts.hour + i) % 20,
                    "is_renting": True,
                    "is_returning": True,
                    "source": "live",
                }
                for i, key in enumerate(keys.values())
                for ts in polls
            ],
        )
        session.commit()
    return keys


@pytest.fixture
def bundle(tmp_path: Path) -> Bundle:
    return Bundle(tiny_bundle(tmp_path))


def test_cycle_fills_forecasts_for_every_station_and_horizon(
    db_engine: Engine, bundle: Bundle
) -> None:
    keys = seed_live(db_engine, NOW - timedelta(minutes=1, seconds=30))
    register(db_engine, bundle)
    assert run_cycle(db_engine, bundle, NOW) == 6
    assert run_cycle(db_engine, bundle, NOW) == 6  # re-run overwrites, no duplicates
    with db_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT station_key, issued_at, horizon_min, bikes_p10, bikes_p50, bikes_p90, "
                "model_version FROM forecasts ORDER BY 1, 3"
            )
        ).all()
        champions = conn.execute(
            text("SELECT count(*) FROM model_versions WHERE is_champion")
        ).scalar()
        buckets = conn.execute(text("SELECT count(*) FROM station_status_15m")).scalar()
    assert len(rows) == 6 and champions == 3 and buckets
    assert {r.station_key for r in rows} == set(keys.values())
    assert {r.issued_at for r in rows} == {datetime(2026, 10, 26, 12, 0, tzinfo=UTC)}
    assert all(0 <= r.bikes_p10 <= r.bikes_p50 <= r.bikes_p90 <= 30 for r in rows)
    assert {r.model_version for r in rows} == {f"lgbm-q-test-h{h}" for h in (30, 60, 120)}


def test_cycle_skips_when_live_data_is_stale(db_engine: Engine, bundle: Bundle) -> None:
    seed_live(db_engine, NOW - timedelta(minutes=45), hours=2)
    register(db_engine, bundle)
    assert run_cycle(db_engine, bundle, NOW) == 0
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM forecasts")).scalar() == 0


def test_new_bundle_takes_over_champion_flag(db_engine: Engine, tmp_path: Path) -> None:
    seed_live(db_engine, NOW, hours=1)
    register(db_engine, Bundle(tiny_bundle(tmp_path / "a", bundle_id="old")))
    register(db_engine, Bundle(tiny_bundle(tmp_path / "b", bundle_id="new")))
    with db_engine.connect() as conn:
        champions = conn.execute(
            text("SELECT model_version FROM model_versions WHERE is_champion ORDER BY 1")
        ).scalars()
        assert list(champions) == ["new-h120", "new-h30", "new-h60"]
