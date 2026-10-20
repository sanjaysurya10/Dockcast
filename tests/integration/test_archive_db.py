from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from dockcast.config import CityConfig
from dockcast.db.models import StationStatusRaw
from dockcast.db.queries import StationRecord, ensure_city, insert_status_rows, upsert_stations
from dockcast.ingest.archive import archive_path, days_before, export_day, prune_day

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
