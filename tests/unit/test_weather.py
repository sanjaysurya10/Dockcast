from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from dockcast.ingest.weather_forecast import parse_locationforecast
from dockcast.ingest.weather_history import KNOT_TO_MS, parse_station_csv

pytestmark = pytest.mark.unit
FIXTURES = Path(__file__).parent.parent / "fixtures" / "weather"


def test_station_csv_parses_real_header_and_units() -> None:
    frame = parse_station_csv((FIXTURES / "hly532_sample.csv").read_text(encoding="utf-8"))
    first = frame.iloc[0]
    # 25-oct-2025 00:00,111,0.0,111,8.3,...,85 (rhum),...,14 (wdsp kn),...,6 (clamt oktas)
    assert first["ts"] == pd.Timestamp("2025-10-25 00:00", tz="UTC")
    assert first["temp_c"] == 8.3
    assert first["precip_mm"] == 0.0
    assert first["humidity_pct"] == 85
    assert first["wind_speed_ms"] == pytest.approx(14 * KNOT_TO_MS)
    assert first["cloud_pct"] == pytest.approx(75.0)


def test_station_csv_is_utc_and_continuous_across_dst() -> None:
    frame = parse_station_csv((FIXTURES / "hly532_sample.csv").read_text(encoding="utf-8"))
    dst_day = frame[frame["ts"].dt.date == datetime(2025, 10, 26).date()]["ts"]
    # Irish clocks went back on 2025-10-26; the file is UTC, so hours stay unique and 1 h apart.
    assert dst_day.is_unique
    assert set(dst_day.diff().dropna()) == {pd.Timedelta(hours=1)}


def test_station_csv_start_filter_and_missing_columns() -> None:
    text = (FIXTURES / "hly532_sample.csv").read_text(encoding="utf-8")
    frame = parse_station_csv(text, datetime(2025, 10, 26, tzinfo=UTC))
    assert frame["ts"].min() == pd.Timestamp("2025-10-26 00:00", tz="UTC")
    no_wind = "date,ind,rain,ind,temp\n25-oct-2025 00:00,0,0.2,0,9.1\n"
    parsed = parse_station_csv(no_wind)
    assert parsed["wind_speed_ms"].isna().all() and parsed["precip_mm"].iloc[0] == 0.2


def test_locationforecast_issue_and_values() -> None:
    issue = parse_locationforecast(
        (FIXTURES / "locationforecast_sample.xml").read_text(encoding="utf-8")
    )
    assert issue.model == "harmonie"
    assert issue.issued_at == datetime(2026, 10, 25, 15, 16, 1, tzinfo=UTC)
    first = issue.frame.iloc[0]
    assert first["ts"] == pd.Timestamp("2026-10-25 21:00", tz="UTC")
    assert (first["temp_c"], first["wind_speed_ms"]) == (8.5, 3.4)
    assert (first["humidity_pct"], first["cloud_pct"]) == (74.9, 96.1)
    assert first["precip_mm"] == 0.0  # interval 20:00-21:00 ends at 21:00
    assert issue.frame["ts"].is_monotonic_increasing and issue.frame["ts"].is_unique
