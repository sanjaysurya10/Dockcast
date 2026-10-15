from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from dockcast.features.lags import gap_mask, lag, rolling
from dockcast.quality.gaps import Gap

pytestmark = pytest.mark.unit

START = pd.Timestamp("2025-03-01 00:00", tz="UTC")
INDEX = pd.date_range(START, periods=12, freq="15min")
SERIES = pd.Series(np.arange(12, dtype=float), index=INDEX)  # bucket i holds value i
CUTOFF = datetime(2025, 3, 2, tzinfo=UTC)
# No observations strictly between 01:00 and 01:40 -> buckets 01:00 (4), 01:15 (5), 01:30 (6)
GAP = Gap(
    datetime(2025, 3, 1, 1, 0, tzinfo=UTC),
    datetime(2025, 3, 1, 1, 40, tzinfo=UTC),
    "hist_b",
    "hist_b",
)


def at(hh_mm: str) -> pd.Timestamp:
    return pd.Timestamp(f"2025-03-01 {hh_mm}", tz="UTC")


def test_gap_mask_marks_overlapping_buckets() -> None:
    assert list(np.flatnonzero(gap_mask(INDEX, [GAP]))) == [4, 5, 6]


def test_lag_without_gaps() -> None:
    lag1 = lag(SERIES, 1, [], CUTOFF)
    lag4 = lag(SERIES, 4, [], CUTOFF)
    assert lag1[at("01:00")] == 3  # bucket 00:45-01:00
    assert lag4[at("01:00")] == 0


def test_lag_is_nan_when_source_bucket_is_in_gap() -> None:
    lag1 = lag(SERIES, 1, [GAP], CUTOFF)
    assert np.isnan(lag1[at("01:15")])  # reads bucket 01:00 (in gap)
    assert np.isnan(lag1[at("01:45")])  # reads bucket 01:30 (in gap)
    assert lag1[at("02:00")] == 7  # bucket 01:45 is after the gap
    lag8 = lag(SERIES, 8, [GAP], CUTOFF)
    assert np.isnan(lag8[at("03:00")])  # reads bucket 01:00
    assert lag8[at("02:45")] == 3


def test_rolling_is_nan_if_any_bucket_in_window_is_in_gap() -> None:
    mean4 = rolling(SERIES, 4, "mean", [GAP], CUTOFF)
    assert mean4[at("01:00")] == pytest.approx(1.5)  # buckets 0-3
    assert np.isnan(mean4[at("01:15")])  # window includes bucket 4
    assert np.isnan(mean4[at("02:30")])  # window 6-9 includes bucket 6
    assert mean4[at("02:45")] == pytest.approx(8.5)  # buckets 7-10


def test_missing_bucket_breaks_rolling_window() -> None:
    holey = SERIES.drop(at("00:30"))
    mean4 = rolling(holey, 4, "mean", [], CUTOFF)
    assert np.isnan(mean4[at("01:00")])
