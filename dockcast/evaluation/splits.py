"""Rolling-origin folds whose test windows avoid data gaps (PRD 13.1, 9.8)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from dockcast.quality.gaps import Gap


@dataclass(frozen=True)
class Fold:
    """One backtest fold; training uses data with target time < ``train_end``."""

    fold: int
    train_end: datetime
    test_start: datetime
    test_end: datetime


def last_complete_month_end(last_observation: datetime, tolerance: timedelta) -> datetime:
    """End (exclusive) of the last calendar month fully covered by the data.

    Args:
        last_observation: Latest observation time (UTC).
        tolerance: How close to the month end the last observation must be.

    Returns:
        First instant of the month after the last complete month.
    """
    ts = pd.Timestamp(last_observation)
    month_start = ts.normalize().replace(day=1)
    next_month = month_start + pd.offsets.MonthBegin(1)
    end = next_month if ts >= next_month - tolerance else month_start
    return end.to_pydatetime()


def rolling_origin_folds(
    data_start: datetime,
    end: datetime,
    gaps: Sequence[Gap],
    n_folds: int = 8,
    test_days: int = 7,
    gap_min: int = 120,
) -> list[Fold]:
    """Place ``n_folds`` test windows walking back from ``end``, skipping data gaps.

    A window that would overlap a gap is moved so it ends at that gap's start.

    Args:
        data_start: Earliest usable time; windows may not start before it.
        end: Exclusive end of the last test window.
        gaps: Data gaps.
        n_folds: Number of folds.
        test_days: Test window length.
        gap_min: Minutes between training end and test start.

    Returns:
        Folds ordered oldest first.

    Raises:
        ValueError: If the data cannot hold ``n_folds`` gap-free windows.
    """
    length = timedelta(days=test_days)
    windows: list[tuple[datetime, datetime]] = []
    cursor = end
    while len(windows) < n_folds:
        start = cursor - length
        if start < data_start:
            raise ValueError(f"only {len(windows)} gap-free test windows fit after {data_start}")
        overlapping = [g for g in gaps if g.start < cursor and g.end > start]
        if overlapping:
            cursor = max(g.start for g in overlapping)
            continue
        windows.append((start, cursor))
        cursor = start
    windows.reverse()
    return [
        Fold(i, s - timedelta(minutes=gap_min), s, e) for i, (s, e) in enumerate(windows, start=1)
    ]
