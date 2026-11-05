from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from dockcast.config import CityConfig
from dockcast.db.models import StationStatusRaw
from dockcast.db.queries import StationRecord, ensure_city, insert_status_rows, upsert_stations
from dockcast.ingest.archive import (
    FORECASTS,
    archive_path,
    days_before,
    export_day,
    prune_day,
)

pytestmark = pytest.mark.integration
CITY = CityConfig(
    city_code="dublin",
    name="Dublin",
    timezone="Europe/Dublin",
    centre_lat=53.3473,
    centre_lon=-6.2591,
    default_zoom=13,
)
DAY = date(2026, 10, 15)


def _seed(engine: Engine) -> int:
    start = datetime(2026, 10, 15, 23, 58, tzinfo=UTC)
    with Session(engine) as session:
        ensure_city(session, CITY)
        keys = upsert_stations(
            session, "dublin", [StationRecord("1", "CLARENDON ROW", 53.34, -6.26, 31)], start
        )
        rows = [
            {
                "station_key": keys["1"],
                "observed_at": start + timedelta(minutes=m),
                "last_reported": None,
                "bikes_available": 5,
                "docks_available": 26,
                "is_renting": True,
                "is_returning": True,
                "source": "live",
            }
            for m in range(4)  # 23:58, 23:59 on 15 Oct; 00:00, 00:01 on 16 Oct
        ]
        insert_status_rows(session, rows)
        session.commit()
    return keys["1"]


def _count(engine: Engine) -> int:
    with Session(engine) as session:
        return int(session.scalar(select(func.count()).select_from(StationStatusRaw)) or 0)


def test_export_then_prune_one_day(db_engine: Engine, tmp_path: Path) -> None:
    _seed(db_engine)
    assert days_before(db_engine, datetime(2026, 10, 16, tzinfo=UTC)) == [DAY]
    assert export_day(db_engine, DAY, tmp_path) == 2
    frame = pd.read_parquet(archive_path(tmp_path, DAY))
    assert list(frame["source_id"]) == ["1", "1"] and set(frame["city_code"]) == {"dublin"}
    assert prune_day(db_engine, DAY, tmp_path) == 2
    assert _count(db_engine) == 2  # the 16 Oct rows remain


def test_prune_refuses_without_matching_archive(db_engine: Engine, tmp_path: Path) -> None:
    _seed(db_engine)
    assert prune_day(db_engine, DAY, tmp_path) == 0  # no file
    export_day(db_engine, DAY, tmp_path)
    with Session(db_engine) as session:  # a late row arrives after export
        key = session.scalar(select(StationStatusRaw.station_key))
        insert_status_rows(
            session,
            [
                {
                    "station_key": key,
                    "observed_at": datetime(2026, 10, 15, 12, 0, tzinfo=UTC),
                    "last_reported": None,
                    "bikes_available": 1,
                    "docks_available": 30,
                    "is_renting": True,
                    "is_returning": True,
                    "source": "live",
                }
            ],
        )
        session.commit()
    assert prune_day(db_engine, DAY, tmp_path) == 0
    assert _count(db_engine) == 5


def test_raw_rows_are_archived_and_pruned_per_city(db_engine: Engine, tmp_path: Path) -> None:
    _seed(db_engine)
    when = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    lyon = CITY.model_copy(update={"city_code": "lyon", "name": "Lyon"})
    with Session(db_engine) as session:
        ensure_city(session, lyon)
        keys = upsert_stations(
            session, "lyon", [StationRecord("1024", "ROUVILLE", 45.77, 4.82, 17)], when
        )
        insert_status_rows(
            session,
            [
                {
                    "station_key": keys["1024"],
                    "observed_at": when,
                    "last_reported": None,
                    "bikes_available": 6,
                    "docks_available": 10,
                    "is_renting": True,
                    "is_returning": True,
                    "source": "live",
                }
            ],
        )
        session.commit()
    cutoff = datetime(2026, 10, 16, tzinfo=UTC)
    assert days_before(db_engine, cutoff, city="lyon") == [DAY]
    assert export_day(db_engine, DAY, tmp_path, city="lyon") == 1
    frame = pd.read_parquet(archive_path(tmp_path, DAY, city="lyon"))
    assert list(frame["source_id"]) == ["1024"] and set(frame["city_code"]) == {"lyon"}
    assert prune_day(db_engine, DAY, tmp_path, city="lyon") == 1
    assert _count(db_engine) == 4  # all four Dublin rows remain
    assert days_before(db_engine, cutoff, city="lyon") == []
    assert days_before(db_engine, cutoff, city="dublin") == [DAY]


def test_forecasts_are_archived_and_pruned_by_issue_day(db_engine: Engine, tmp_path: Path) -> None:
    key = _seed(db_engine)
    issued = [datetime(2026, 10, 15, 23, 45, tzinfo=UTC), datetime(2026, 10, 16, 0, 0, tzinfo=UTC)]
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO model_versions (model_version, mlflow_run_id, kind, horizon_min, "
                "trained_at, train_end, metrics) VALUES ('m', 'r', 'lgbm', 60, :t, :t, '{}')"
            ),
            {"t": issued[0]},
        )
        for ts in issued:
            conn.execute(
                text(
                    "INSERT INTO forecasts (station_key, issued_at, horizon_min, target_ts, "
                    "bikes_p10, bikes_p50, bikes_p90, model_version) "
                    "VALUES (:k, :t, 60, :t + INTERVAL '60 minutes', 1, 2, 3, 'm')"
                ),
                {"k": key, "t": ts},
            )
    cutoff = datetime(2026, 10, 16, tzinfo=UTC)
    assert days_before(db_engine, cutoff, FORECASTS) == [DAY]
    assert export_day(db_engine, DAY, tmp_path, FORECASTS) == 1
    frame = pd.read_parquet(archive_path(tmp_path, DAY, FORECASTS))
    assert list(frame["bikes_p50"]) == [2] and list(frame["source_id"]) == ["1"]
    assert prune_day(db_engine, DAY, tmp_path, FORECASTS) == 1
    with db_engine.connect() as conn:
        left = conn.execute(text("SELECT issued_at FROM forecasts")).scalars().all()
    assert left == [issued[1]]
    assert _count(db_engine) == 4  # raw rows untouched
