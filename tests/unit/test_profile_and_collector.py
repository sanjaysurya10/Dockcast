from datetime import UTC, datetime
from pathlib import Path

import pytest

from dockcast.ingest.collector import archive_path, status_rows
from dockcast.ingest.gbfs import StationStatus
from dockcast.ingest.historical.backfill import load_file
from dockcast.quality.profile import profile_frame, render_report

pytestmark = pytest.mark.unit
HIST = Path(__file__).parent.parent / "fixtures" / "hist"


def test_profile_format_b_fixture() -> None:
    df, profile = load_file(HIST / "dublin-bikes_station_status_102025.csv")
    assert profile.rows == len(df) == 7
    assert profile.stations == 1
    assert profile.median_interval_s == 600
    assert profile.pct_missing == 0.0
    assert profile.min_ts == datetime(2025, 10, 26, 0, 5, tzinfo=UTC)


def test_profile_counts_missing_snapshots() -> None:
    df, _ = load_file(HIST / "dublin-bikes_station_status_102025.csv")
    profile = profile_frame("x.csv", "hist_b", df.drop(df.index[3]))
    # 6 rows over a 60-min span at a 600 s interval -> 7 expected
    assert profile.pct_missing == pytest.approx(100 * (1 - 6 / 7), abs=0.01)


def test_report_lists_every_file() -> None:
    _, p1 = load_file(HIST / "dublin-bikes_station_status_102025.csv")
    _, p2 = load_file(HIST / "dublin-bikes_station_status_011999.csv")
    text = render_report([p1, p2], ["Quarterly 2018"], ["exact: 1 legacy IDs"], datetime.now(UTC))
    assert p1.file_name in text and p2.file_name in text and "Quarterly 2018" in text


def test_status_rows_skip_unknown_stations() -> None:
    now = datetime(2026, 10, 15, 14, 0, tzinfo=UTC)
    statuses = [
        StationStatus("1", 3, 27, True, True, True, None),
        StationStatus("999", 1, 1, True, True, True, None),
    ]
    rows = status_rows(statuses, {"1": 10}, now)
    assert rows == [
        {
            "station_key": 10,
            "observed_at": now,
            "last_reported": None,
            "bikes_available": 3,
            "docks_available": 27,
            "is_renting": True,
            "is_returning": True,
            "source": "live",
        }
    ]


def test_archive_path_layout() -> None:
    path = archive_path(Path("root"), datetime(2026, 3, 29, 1, 7, tzinfo=UTC))
    assert path == Path("root/2026/03/29/0107.json.gz")
