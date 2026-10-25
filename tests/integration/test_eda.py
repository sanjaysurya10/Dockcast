import shutil
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import Engine

from dockcast.ingest.historical.backfill import backfill
from dockcast.ingest.weather_history import parse_station_csv, store_observed
from dockcast.quality import eda
from dockcast.quality.gaps import refresh_gaps
from dockcast.transform.resample import resample
from tests.integration.test_ingest_db import CITY, CKAN, FIXTURES, _mock_gbfs

pytestmark = pytest.mark.integration


@respx.mock
def test_report_is_generated_from_real_shaped_data(
    db_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_gbfs()
    respx.get(CKAN).mock(return_value=httpx.Response(200, json={"result": {"resources": []}}))
    hist = tmp_path / "hist"
    hist.mkdir()
    for name in (
        "dublinbike-historical-data-2022-10.csv",
        "dublin-bikes_station_status_102025.csv",
    ):
        shutil.copy(FIXTURES / "hist" / name, hist / name)
    with httpx.Client() as client:
        backfill(hist, db_engine, CITY, client, tmp_path / "data_profile.md")
    refresh_gaps(db_engine, tmp_path / "data_gaps.md")
    weather = parse_station_csv((FIXTURES / "weather" / "hly532_sample.csv").read_text("utf-8"))
    store_observed(db_engine, "dublin", weather)
    resample(db_engine)

    monkeypatch.setattr(eda, "FIGURES", tmp_path / "figures")
    text = eda.build_report(db_engine)

    for heading in (
        "## 1. Coverage",
        "## 2. Occupancy",
        "## 3. Activity",
        "## 4. Activity vs weather",
        "## 5. Closures",
        "## 6. Large count jumps",
        "## 7. Flat-lined counts",
        "## 8. Cleaning applied",
    ):
        assert heading in text
    assert "| hist_b | 7 |" in text  # coverage row from the Format B fixture
    assert (tmp_path / "figures" / "eda_hourly_profile.png").exists()
