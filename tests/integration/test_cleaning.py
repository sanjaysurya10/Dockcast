from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from dockcast.db.models import StationCapacity
from dockcast.db.queries import StationRecord, ensure_city, insert_status_rows, upsert_stations
from dockcast.transform.resample import resample
from tests.integration.test_ingest_db import CITY

pytestmark = pytest.mark.integration
T0 = datetime(2025, 3, 1, tzinfo=UTC)


def _station(engine: Engine) -> int:
    with Session(engine) as session:
        ensure_city(session, CITY)
        keys = upsert_stations(
            session, "dublin", [StationRecord("1", "CLARENDON ROW", 53.34, -6.26, 30)], T0
        )
        session.commit()
    return keys["1"]


def _raw(engine: Engine, key: int, rows: list[tuple[int, int]], docks: int | None = None) -> None:
    """rows: (minutes after T0, bikes); docks default to 30 - bikes."""
    with Session(engine) as session:
        insert_status_rows(
            session,
            [
                {
                    "station_key": key,
                    "observed_at": T0 + timedelta(minutes=m),
                    "last_reported": None,
                    "bikes_available": b,
                    "docks_available": (30 - b) if docks is None else docks,
                    "is_renting": True,
                    "is_returning": True,
                    "source": "hist_b",
                }
                for m, b in rows
            ],
        )
        session.commit()


def _flags(engine: Engine) -> dict[datetime, tuple[object, ...]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT ts, bikes_last, n_obs, rebalance_flag, flatline_flag, capacity_mismatch "
                "FROM station_status_15m ORDER BY ts"
            )
        ).all()
    return {r[0]: tuple(r[1:]) for r in rows}


def test_v_shaped_spike_is_excluded(db_engine: Engine) -> None:
    key = _station(db_engine)
    # 20 bikes, a one-reading dip to 1 five minutes later, back to 20: the dip is dropped
    _raw(db_engine, key, [(1, 20), (6, 1), (11, 20)])
    resample(db_engine)
    bucket = _flags(db_engine)[T0]
    assert bucket[0] == 20 and bucket[1] == 2  # 2 kept observations, last = 20


def test_real_drop_is_not_a_spike(db_engine: Engine) -> None:
    key = _station(db_engine)
    _raw(db_engine, key, [(0, 20), (5, 1), (10, 1)])  # stays low: not V-shaped
    resample(db_engine)
    assert _flags(db_engine)[T0][:2] == (1, 3)


def test_rebalance_flag_from_gradual_one_minute_unloading(db_engine: Engine) -> None:
    key = _station(db_engine)
    # live-like 1-min data: +1 bike per minute for 9 minutes (swing 9 within 10 min)
    _raw(db_engine, key, [(m, 2 + m) for m in range(10)])
    resample(db_engine)
    assert _flags(db_engine)[T0][2] is True


def test_no_rebalance_flag_for_small_changes(db_engine: Engine) -> None:
    key = _station(db_engine)
    _raw(db_engine, key, [(0, 10), (10, 12), (20, 9)])
    resample(db_engine)
    assert not any(v[2] for v in _flags(db_engine).values())


def test_flatline_flag_after_24_hours_unchanged(db_engine: Engine) -> None:
    key = _station(db_engine)
    _raw(db_engine, key, [(m, 0) for m in range(0, 25 * 60, 10)])  # 0 bikes for ~25 h
    resample(db_engine)
    assert all(v[3] for v in _flags(db_engine).values() if v[1])


def test_flatline_not_flagged_below_threshold_or_across_gap(db_engine: Engine) -> None:
    key = _station(db_engine)
    # 23 h unchanged, then a 2 h silence (breaks the run), then 23 h unchanged again
    first = [(m, 5) for m in range(0, 23 * 60, 10)]
    second = [(m, 5) for m in range(25 * 60, 48 * 60, 10)]
    _raw(db_engine, key, first + second)
    resample(db_engine)
    assert not any(v[3] for v in _flags(db_engine).values())


def test_capacity_mismatch_uses_capacity_at_the_time(db_engine: Engine) -> None:
    key = _station(db_engine)
    with Session(db_engine) as session:
        session.add_all(
            [
                StationCapacity(station_key=key, valid_from=T0, capacity=20, source="hist_b"),
                StationCapacity(
                    station_key=key,
                    valid_from=T0 + timedelta(hours=1),
                    capacity=30,
                    source="hist_b",
                ),
            ]
        )
        session.commit()
    # bikes + docks = 30 throughout: too many for capacity 20, fine once capacity is 30
    _raw(db_engine, key, [(0, 10), (70, 10)], docks=20)
    resample(db_engine)
    flags = _flags(db_engine)
    assert flags[T0][4] is True
    assert flags[T0 + timedelta(hours=1)][4] is False
