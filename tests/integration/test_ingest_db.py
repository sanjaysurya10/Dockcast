import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from dockcast.config import CityConfig, load_project_config
from dockcast.db.engine import make_session_factory
from dockcast.db.models import CollectorRun, DataQualityFile, Station, StationStatusRaw
from dockcast.ingest.collector import Collector
from dockcast.ingest.historical.backfill import backfill

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parent.parent / "fixtures"
ROOT = "https://gbfs.test/gbfs.json"
CKAN = "https://ckan.test/package_show?id=dublinbikes-api"
CITY = CityConfig(
    city_code="dublin",
    name="Dublin",
    timezone="Europe/Dublin",
    centre_lat=53.3473,
    centre_lon=-6.2591,
    default_zoom=13,
    gbfs_root_url=ROOT,
    ckan_package_url=CKAN,
)


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / "gbfs" / f"{name}.json").read_text())


def _mock_gbfs() -> None:
    respx.get(ROOT).mock(return_value=httpx.Response(200, json=_fixture("gbfs")))
    base = "https://api.cyclocity.fr/contracts/dublin/gbfs/v2"
    for name in ("station_information", "station_status"):
        respx.get(f"{base}/{name}.json").mock(return_value=httpx.Response(200, json=_fixture(name)))


@respx.mock
def test_collector_poll_is_idempotent_and_logged(db_engine: Engine, tmp_path: Path) -> None:
    _mock_gbfs()
    now = datetime(2026, 10, 15, 14, 0, 0, tzinfo=UTC)
    with httpx.Client() as client:
        collector = Collector(
            make_session_factory(db_engine),
            client,
            CITY,
            load_project_config().collector,
            tmp_path,
            clock=lambda: now,
            sleep=lambda _: None,
        )
        first = collector.poll_once()
        second = collector.poll_once()
    assert (first.status, first.stations_seen, first.rows_written) == ("ok", 3, 3)
    assert second.rows_written == 0  # same observed_at -> ON CONFLICT DO NOTHING
    assert first.feed_last_updated == datetime.fromtimestamp(1792075100, tz=UTC)
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(StationStatusRaw)) == 3
        assert session.scalar(select(func.count()).select_from(CollectorRun)) == 2
    assert (tmp_path / "2026/10/15/1400.json.gz").exists()


@respx.mock
def test_collector_records_error_run(db_engine: Engine, tmp_path: Path) -> None:
    respx.get(ROOT).mock(return_value=httpx.Response(503))
    with httpx.Client() as client:
        run = Collector(
            make_session_factory(db_engine),
            client,
            CITY,
            load_project_config().collector,
            tmp_path,
            sleep=lambda _: None,
        ).poll_once()
    assert run.status == "error" and run.error and "503" in run.error
    with Session(db_engine) as session:
        assert session.scalar(select(CollectorRun.status)) == "error"


@respx.mock
def test_backfill_loads_reconciles_and_profiles(db_engine: Engine, tmp_path: Path) -> None:
    _mock_gbfs()
    respx.get(CKAN).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "resources": [
                        {"format": "CSV", "name": "Quarterly", "url": "https://x/q_2018.csv"}
                    ]
                }
            },
        )
    )
    hist = tmp_path / "hist"
    hist.mkdir()
    for name in (
        "dublinbike-historical-data-2022-10.csv",
        "dublin-bikes_station_status_102025.csv",
        "dublin-bikes_station_status_011999.csv",
    ):
        shutil.copy(FIXTURES / "hist" / name, hist / name)
    report = tmp_path / "data_profile.md"
    with httpx.Client() as client:
        profiles = backfill(hist, db_engine, CITY, client, report)

    assert len(profiles) == 3
    with Session(db_engine) as session:
        by_source = dict(
            session.execute(
                select(StationStatusRaw.source, func.count()).group_by(StationStatusRaw.source)
            ).all()
        )
        assert by_source == {"hist_a": 16, "hist_b": 7}
        methods = dict(
            session.execute(text("SELECT method, count(*) FROM station_id_map GROUP BY 1")).all()
        )
        # IDs 1 and 2 exist in the live feed; ID 3 (Bolton Street) is not in the fixture feed
        assert methods == {"exact": 2, "new": 1}
        inactive = session.scalar(select(Station).where(Station.source_id == "3"))
        assert inactive is not None and inactive.is_active is False
        assert session.scalar(select(func.count()).select_from(DataQualityFile)) == 3
    text_out = report.read_text(encoding="utf-8")
    assert "dublin-bikes_station_status_011999.csv" in text_out and "Quarterly" in text_out

    with httpx.Client() as client:
        backfill(hist, db_engine, CITY, client, report)  # rerun is idempotent
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(StationStatusRaw)) == 23
