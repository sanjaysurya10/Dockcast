from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from dockcast.quality.gaps import Gap, find_gaps, render_gap_report

pytestmark = pytest.mark.unit


def _snapshots(times: list[str], sources: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"observed_at": pd.to_datetime(times, utc=True), "source": sources})


def test_b_silence_over_30_min_is_a_gap() -> None:
    snaps = _snapshots(
        ["2025-02-01 00:00", "2025-02-01 00:05", "2025-02-01 00:35", "2025-02-01 01:10"],
        ["hist_b"] * 4,
    )
    gaps = find_gaps(snaps)
    # 00:05 -> 00:35 is exactly 30 min (not a gap); 00:35 -> 01:10 is 35 min (gap)
    assert gaps == [
        Gap(
            datetime(2025, 2, 1, 0, 35, tzinfo=UTC),
            datetime(2025, 2, 1, 1, 10, tzinfo=UTC),
            "hist_b",
            "hist_b",
        )
    ]


def test_a_uses_60_min_threshold() -> None:
    snaps = _snapshots(["2023-01-01 00:00", "2023-01-01 00:30", "2023-01-01 01:30"], ["hist_a"] * 3)
    assert find_gaps(snaps) == []


def test_source_change_gaps_are_found() -> None:
    # Format A ends Feb 2024, B starts May 2024; B ends June 2026, collector starts Oct 2026
    snaps = _snapshots(
        ["2024-02-29 23:30", "2024-05-02 19:00", "2026-06-30 23:55", "2026-10-15 15:08"],
        ["hist_a", "hist_b", "hist_b", "live"],
    )
    gaps = find_gaps(snaps)
    assert [(g.source_before, g.source_after) for g in gaps] == [
        ("hist_a", "hist_b"),
        ("hist_b", "hist_b"),
        ("hist_b", "live"),
    ]
    assert gaps[-1].duration > timedelta(days=100)


def test_report_lists_each_gap() -> None:
    gap = Gap(
        datetime(2026, 6, 30, 23, 55, tzinfo=UTC),
        datetime(2026, 10, 15, 15, 8, tzinfo=UTC),
        "hist_b",
        "live",
    )
    text = render_gap_report([gap], datetime(2026, 10, 15, tzinfo=UTC))
    assert "| 1 | 2026-06-30 23:55 | 2026-10-15 15:08 | 106d 15h 13m | hist_b | live |" in text
