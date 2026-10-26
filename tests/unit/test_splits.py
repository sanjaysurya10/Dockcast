import itertools
from datetime import UTC, datetime, timedelta

import pytest

from dockcast.evaluation.splits import last_complete_month_end, rolling_origin_folds
from dockcast.quality.gaps import Gap

pytestmark = pytest.mark.unit
TOL = timedelta(minutes=30)


def test_last_complete_month_end() -> None:
    # Format B currently ends 2026-06-30 23:55 UTC -> June is complete
    assert last_complete_month_end(datetime(2026, 6, 30, 23, 55, tzinfo=UTC), TOL) == datetime(
        2026, 7, 1, tzinfo=UTC
    )
    # Data stopping on 24 Jan -> last complete month is December
    assert last_complete_month_end(datetime(2026, 1, 24, 23, 55, tzinfo=UTC), TOL) == datetime(
        2026, 1, 1, tzinfo=UTC
    )


def test_folds_without_gaps_are_consecutive_weeks() -> None:
    end = datetime(2026, 7, 1, tzinfo=UTC)
    folds = rolling_origin_folds(datetime(2024, 5, 2, tzinfo=UTC), end, [])
    assert len(folds) == 8
    assert folds[-1].test_end == end
    assert folds[0].test_start == end - timedelta(weeks=8)
    for a, b in itertools.pairwise(folds):
        assert a.test_end == b.test_start
    assert all(f.test_start - f.train_end == timedelta(minutes=120) for f in folds)


def test_no_fold_overlaps_a_gap() -> None:
    end = datetime(2026, 7, 1, tzinfo=UTC)
    gap = Gap(
        datetime(2026, 6, 10, 3, 0, tzinfo=UTC),
        datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
        "hist_b",
        "hist_b",
    )
    folds = rolling_origin_folds(datetime(2024, 5, 2, tzinfo=UTC), end, [gap])
    assert len(folds) == 8
    for f in folds:
        assert not (gap.start < f.test_end and gap.end > f.test_start)
    # the window that would have overlapped now ends exactly at the gap start
    assert any(f.test_end == gap.start for f in folds)


def test_not_enough_data_raises() -> None:
    with pytest.raises(ValueError):
        rolling_origin_folds(datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC), [])


def test_fold_boundaries_snap_to_grid_when_gap_starts_off_grid() -> None:
    # Format B's last reading is 2026-06-30 23:55; the gap to the collector starts there
    gap = Gap(
        datetime(2026, 6, 30, 23, 55, tzinfo=UTC),
        datetime(2026, 10, 15, 15, 8, tzinfo=UTC),
        "hist_b",
        "live",
    )
    folds = rolling_origin_folds(
        datetime(2024, 5, 2, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC), [gap]
    )
    assert folds[-1].test_end == datetime(2026, 6, 30, 23, 45, tzinfo=UTC)
    for f in folds:
        for ts in (f.train_end, f.test_start, f.test_end):
            assert ts.minute % 15 == 0 and ts.second == 0
