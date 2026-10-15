import json
import shutil
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from dockcast.db.models import DataGap, DataQualityFile, StationStatusRaw
from dockcast.ingest.historical.backfill import backfill
from dockcast.ingest.historical.monthly import backfill_new_months
from tests.integration.test_ingest_db import CITY, CKAN, FIXTURES, _mock_gbfs

pytestmark = pytest.mark.integration
BASE = "https://data.test/download"
A_FILE = "dublinbike-historical-data-2022-10.csv"
B_FILE = "dublin-bikes_station_status_102025.csv"


def _listing(*names: str) -> dict[str, object]:
    return {
        "result": {"resources": [{"format": "CSV", "name": n, "url": f"{BASE}/{n}"} for n in names]}
    }


@respx.mock
def test_only_new_months_are_downloaded_and_loaded(db_engine: Engine, tmp_path: Path) -> None:
    _mock_gbfs()
    hist = tmp_path / "hist"
    hist.mkdir()
    shutil.copy(FIXTURES / "hist" / A_FILE, hist / A_FILE)
    reports = tmp_path / "reports"
    respx.get(CKAN).mock(return_value=httpx.Response(200, json=_listing(A_FILE)))
    with httpx.Client() as client:
        backfill(hist, db_engine, CITY, client, reports / "data_profile.md")

    respx.get(CKAN).mock(return_value=httpx.Response(200, json=_listing(A_FILE, B_FILE)))
    a_route = respx.get(f"{BASE}/{A_FILE}").mock(return_value=httpx.Response(500))
    b_route = respx.get(f"{BASE}/{B_FILE}").mock(
        return_value=httpx.Response(200, content=(FIXTURES / "hist" / B_FILE).read_bytes())
    )
    with httpx.Client() as client:
        loaded = backfill_new_months(db_engine, CITY, client, hist, reports)

    assert loaded == [B_FILE]
    assert a_route.call_count == 0 and b_route.call_count == 1
    with Session(db_engine) as session:
        files = set(session.scalars(select(DataQualityFile.file_name)))
        assert files == {A_FILE, B_FILE}
        assert session.scalar(select(func.count()).select_from(StationStatusRaw)) == 16 + 7
        # A (Oct 2022) -> B (Oct 2025) is one long gap
        assert session.scalar(select(func.count()).select_from(DataGap)) >= 1
    report = (reports / "data_profile.md").read_text(encoding="utf-8")
    assert A_FILE in report and B_FILE in report  # earlier file kept in the report
    assert len(json.loads((reports / "data_profile.json").read_text())["profiles"]) == 2
    assert (reports / "data_gaps.md").exists()

    with httpx.Client() as client:
        assert backfill_new_months(db_engine, CITY, client, hist, reports) == []
