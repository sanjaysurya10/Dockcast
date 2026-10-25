from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from dockcast.db.models import DataGap
from dockcast.db.queries import StationRecord, ensure_city, insert_status_rows, upsert_stations
from dockcast.transform.resample import resample
from tests.integration.test_ingest_db import CITY

pytestmark = pytest.mark.integration


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def _station(engine: Engine) -> int:
    with Session(engine) as session:
        ensure_city(session, CITY)
        keys = upsert_stations(
            session,
            "dublin",
            [StationRecord("1", "CLARENDON ROW", 53.34, -6.26, 31)],
            _ts("2025-01-01"),
        )
        session.commit()
    return keys["1"]


def _raw(engine: Engine, key: int, rows: list[tuple[str, int, bool]]) -> None:
    with Session(engine) as session:
        insert_status_rows(
            session,
            [
                {
                    "station_key": key,
                    "observed_at": _ts(t),
                    "last_reported": None,
                    "bikes_available": bikes,
                    "docks_available": 31 - bikes,
                    "is_renting": renting,
                    "is_returning": renting,
                    "source": "hist_b",
                }
                for t, bikes, renting in rows
            ],
        )
        session.commit()


def _buckets(engine: Engine) -> dict[datetime, tuple[object, ...]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT ts, bikes_last, bikes_min, bikes_max, docks_last, n_obs, is_imputed, "
                "is_closed FROM station_status_15m ORDER BY ts"
            )
        ).all()
    return {r[0]: tuple(r[1:]) for r in rows}


def test_bucketing_fill_and_limits(db_engine: Engine) -> None:
    key = _station(db_engine)
    _raw(
        db_engine,
        key,
        [
            ("2025-03-01 00:01", 10, True),
            ("2025-03-01 00:07", 8, True),  # last in bucket 00:00
            ("2025-03-01 00:20", 5, False),  # bucket 00:15, closed
            ("2025-03-01 01:31", 12, True),  # bucket 01:30
        ],
    )
    assert resample(db_engine) == 7  # 00:00 .. 01:30
    b = _buckets(db_engine)
    assert b[_ts("2025-03-01 00:00")] == (8, 8, 10, 23, 2, False, False)
    assert b[_ts("2025-03-01 00:15")] == (5, 5, 5, 26, 1, False, True)
    # 00:30 and 00:45 are <= 2 buckets after 00:15: filled, min/max stay NULL
    assert b[_ts("2025-03-01 00:30")] == (5, None, None, 26, 0, True, True)
    assert b[_ts("2025-03-01 00:45")] == (5, None, None, 26, 0, True, True)
    # 01:00 and 01:15 are 3+ buckets after the last observation: not filled
    assert b[_ts("2025-03-01 01:00")] == (None, None, None, None, 0, False, False)
    assert b[_ts("2025-03-01 01:15")] == (None, None, None, None, 0, False, False)
    assert b[_ts("2025-03-01 01:30")][0] == 12


def test_no_fill_across_data_gap(db_engine: Engine) -> None:
    key = _station(db_engine)
    _raw(db_engine, key, [("2025-03-01 00:01", 10, True), ("2025-03-01 00:46", 4, True)])
    with Session(db_engine) as session:
        session.add(
            DataGap(
                gap_start=_ts("2025-03-01 00:01"),
                gap_end=_ts("2025-03-01 00:46"),
                source_before="hist_b",
                source_after="hist_b",
                duration_s=2700,
            )
        )
        session.commit()
    resample(db_engine)
    b = _buckets(db_engine)
    assert b[_ts("2025-03-01 00:15")][0] is None and b[_ts("2025-03-01 00:15")][5] is False
    assert b[_ts("2025-03-01 00:30")][0] is None


@pytest.mark.parametrize("day", ["2025-03-30", "2025-10-26"])  # last Sundays of Mar and Oct
def test_dst_days_have_96_unique_buckets(db_engine: Engine, day: str) -> None:
    key = _station(db_engine)
    start = _ts(f"{day} 00:00")
    _raw(
        db_engine,
        key,
        [((start + timedelta(minutes=10 * i)).isoformat()[:16], i % 30, True) for i in range(144)],
    )
    resample(db_engine)
    b = _buckets(db_engine)
    day_buckets = [ts for ts in b if ts.date() == start.date()]
    assert len(day_buckets) == 96 == len(set(day_buckets))
    assert all(b[ts][4] >= 1 for ts in day_buckets)  # every bucket observed at 10-min spacing


def test_incremental_rerun_matches_full(db_engine: Engine) -> None:
    key = _station(db_engine)
    _raw(
        db_engine,
        key,
        [
            ("2025-03-01 00:01", 10, True),
            ("2025-03-01 00:20", 5, True),
            ("2025-03-01 01:31", 3, True),
        ],
    )
    resample(db_engine)
    full = _buckets(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE station_status_15m SET bikes_last = -1 WHERE ts >= :t"),
            {"t": _ts("2025-03-01 00:30")},
        )
    resample(db_engine, since=_ts("2025-03-01 00:30"))
    assert _buckets(db_engine) == full


@settings(
    max_examples=15, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    offsets=st.lists(st.integers(min_value=0, max_value=3 * 24 * 60), min_size=1, max_size=40),
)
def test_bucket_count_equals_grid_length(db_engine: Engine, offsets: list[int]) -> None:
    with db_engine.begin() as conn:
        conn.execute(text("TRUNCATE station_status_15m, station_status_raw"))
    key = _station(db_engine)
    start = _ts("2025-10-25 00:00")  # spans the 2025-10-26 DST change
    times = sorted({start + timedelta(minutes=m) for m in offsets})
    _raw(db_engine, key, [(t.isoformat()[:19], 3, True) for t in times])
    resample(db_engine)
    first = start + timedelta(minutes=(min(offsets) // 15) * 15)
    last = start + timedelta(minutes=(max(offsets) // 15) * 15)
    expected = int((last - first) / timedelta(minutes=15)) + 1
    buckets = _buckets(db_engine)
    assert len(buckets) == expected
    assert sum(int(str(v[4])) for v in buckets.values()) == len(times)
