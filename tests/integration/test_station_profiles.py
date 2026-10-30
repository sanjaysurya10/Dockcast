"""E3 profile cells from the 15-min table: filters, capacity in force, local hours on DST days."""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from dockcast.db.queries import StationRecord, ensure_city, upsert_stations
from dockcast.features.station import load_profile_cells
from tests.integration.test_ingest_db import CITY

pytestmark = pytest.mark.integration
START = datetime(2026, 3, 23, tzinfo=UTC)  # Monday; DST starts Sun 29 Mar 2026 01:00 UTC


def seed_stations(engine: Engine, capacity: int = 20) -> list[int]:
    """Two stations with one capacity record from ``START - 1 day``."""
    with Session(engine) as session:
        ensure_city(session, CITY)
        keys = upsert_stations(
            session,
            "dublin",
            [
                StationRecord("A", "FIRST", 53.34, -6.26, capacity),
                StationRecord("B", "SECOND", 53.35, -6.27, capacity),
            ],
            START - timedelta(days=1),
        )
        session.execute(
            text(
                "INSERT INTO station_capacity (station_key, valid_from, capacity, source) "
                "SELECT station_key, :start, :cap, 'test' FROM stations"
            ),
            {"start": START - timedelta(days=1), "cap": capacity},
        )
        session.commit()
    return sorted(keys.values())


def insert_buckets(engine: Engine, rows: Iterable[dict[str, object]]) -> None:
    """Upsert ``station_status_15m`` rows (``station_key, ts, bikes`` plus optional flags)."""
    sql = text(
        """
        INSERT INTO station_status_15m (station_key, ts, bikes_last, docks_last, n_obs,
                                        is_imputed, is_closed, flatline_flag)
        VALUES (:station_key, :ts, :bikes, 0, :n_obs, :is_imputed, :is_closed, :flatline)
        ON CONFLICT (station_key, ts) DO UPDATE SET bikes_last = EXCLUDED.bikes_last,
            n_obs = EXCLUDED.n_obs, is_imputed = EXCLUDED.is_imputed,
            is_closed = EXCLUDED.is_closed, flatline_flag = EXCLUDED.flatline_flag
        """
    )
    defaults = {"n_obs": 1, "is_imputed": False, "is_closed": False, "flatline": False}
    with engine.begin() as conn:
        conn.execute(sql, [{**defaults, **r} for r in rows])


def grid_rows(keys: Iterable[int], start: datetime, end: datetime) -> list[dict[str, object]]:
    """One bucket per 15 min; bikes = local-agnostic function of UTC hour and station."""
    rows: list[dict[str, object]] = []
    ts = start
    while ts < end:
        rows += [{"station_key": k, "ts": ts, "bikes": float((ts.hour + k) % 20)} for k in keys]
        ts += timedelta(minutes=15)
    return rows


def test_dst_day_maps_states_to_local_hours_and_weekend(db_engine: Engine) -> None:
    keys = seed_stations(db_engine)
    # Buckets 00:30 and 00:45 UTC on Sun 29 Mar -> states at 00:45 GMT and 02:00 IST.
    insert_buckets(
        db_engine,
        [
            {"station_key": keys[0], "ts": datetime(2026, 3, 29, 0, 30, tzinfo=UTC), "bikes": 4.0},
            {"station_key": keys[0], "ts": datetime(2026, 3, 29, 0, 45, tzinfo=UTC), "bikes": 10.0},
        ],
    )
    cells = load_profile_cells(db_engine, START, START + timedelta(days=7))
    got = {(r.day_type, r.hour): r.occupancy for r in cells.itertuples()}
    assert got == {("weekend", 0): pytest.approx(0.2), ("weekend", 2): pytest.approx(0.5)}


def test_excluded_states_and_capacity_in_force(db_engine: Engine) -> None:
    keys = seed_stations(db_engine)
    ts = datetime(2026, 3, 24, 9, 0, tzinfo=UTC)  # Tuesday, state at 09:15 GMT
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO station_capacity (station_key, valid_from, capacity, source) "
                "VALUES (:k, :t, 40, 'test')"
            ),
            {"k": keys[0], "t": ts},
        )
    insert_buckets(
        db_engine,
        [
            {"station_key": keys[0], "ts": ts, "bikes": 10.0},  # capacity 40 from ts
            {"station_key": keys[0], "ts": ts + timedelta(days=1), "bikes": 0.0, "n_obs": 0},
            {"station_key": keys[0], "ts": ts + timedelta(days=2), "bikes": 0.0, "is_closed": True},
            {"station_key": keys[1], "ts": ts, "bikes": 0.0, "is_imputed": True},
            {"station_key": keys[1], "ts": ts + timedelta(days=1), "bikes": 0.0, "flatline": True},
            {"station_key": keys[1], "ts": ts + timedelta(days=2), "bikes": 25.0},  # capped at 1
        ],
    )
    cells = load_profile_cells(db_engine, START, START + timedelta(days=7))
    got = {(r.station_key, r.day_type, r.hour): (r.occupancy, r.n) for r in cells.itertuples()}
    assert got == {
        (keys[0], "weekday", 9): (pytest.approx(0.25), 1),
        (keys[1], "weekday", 9): (pytest.approx(1.0), 1),
    }
