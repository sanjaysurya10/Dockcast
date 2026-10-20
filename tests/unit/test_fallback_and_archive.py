from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from dockcast.ingest.archive import archive_path, day_bounds, retention_cutoff
from dockcast.ingest.collector import parse_args, primary_is_stale

pytestmark = pytest.mark.unit
NOW = datetime(2026, 10, 20, 18, 45, tzinfo=UTC)


def test_fallback_polls_when_no_run_or_primary_silent() -> None:
    assert primary_is_stale(None, NOW, timedelta(minutes=3))
    assert primary_is_stale(NOW - timedelta(minutes=4), NOW, timedelta(minutes=3))
    assert not primary_is_stale(NOW - timedelta(minutes=1), NOW, timedelta(minutes=3))


def test_parse_args() -> None:
    args = parse_args(["--once", "--if-stale-min", "3"])
    assert args.once and args.if_stale_min == 3
    assert parse_args([]).once is False


def test_retention_cutoff_keeps_whole_days() -> None:
    assert retention_cutoff(NOW, 7) == datetime(2026, 10, 13, tzinfo=UTC)


def test_day_bounds_are_utc_midnights_on_dst_day() -> None:
    start, end = day_bounds(date(2026, 10, 25))  # Irish clocks go back this day
    assert (start, end) == (
        datetime(2026, 10, 25, tzinfo=UTC),
        datetime(2026, 10, 26, tzinfo=UTC),
    )


def test_archive_path_is_hive_partitioned() -> None:
    assert archive_path(Path("a"), date(2026, 10, 15)) == Path(
        "a/station_status_raw/source=live/date=2026-10-15/part-0.parquet"
    )
