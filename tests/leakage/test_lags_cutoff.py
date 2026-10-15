from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from dockcast.features.lags import lag, rolling
from dockcast.quality.gaps import Gap

pytestmark = pytest.mark.leakage

RNG = np.random.default_rng(42)
INDEX = pd.date_range("2025-10-24 00:00", periods=4 * 24 * 4, freq="15min", tz="UTC")  # spans DST
SERIES = pd.Series(RNG.integers(0, 40, len(INDEX)).astype(float), index=INDEX)
GAPS = [
    Gap(
        pd.Timestamp("2025-10-25 06:10", tz="UTC").to_pydatetime(),
        pd.Timestamp("2025-10-25 07:20", tz="UTC").to_pydatetime(),
        "hist_b",
        "hist_b",
    )
]
FAR_FUTURE = INDEX[-1] + timedelta(days=1)


def _features(series: pd.Series, cutoff: pd.Timestamp) -> dict[str, pd.Series]:
    c = cutoff.to_pydatetime()
    return {
        "lag1": lag(series, 1, GAPS, c),
        "lag8": lag(series, 8, GAPS, c),
        "mean4": rolling(series, 4, "mean", GAPS, c),
        "std12": rolling(series, 12, "std", GAPS, c),
    }


@pytest.mark.parametrize("t_pos", RNG.integers(20, len(INDEX) - 1, 25).tolist())
def test_features_identical_when_future_rows_deleted(t_pos: int) -> None:
    t = INDEX[t_pos]
    full = _features(SERIES, pd.Timestamp(FAR_FUTURE))
    truncated = _features(SERIES[SERIES.index < t], t)
    for name, values in full.items():
        np.testing.assert_equal(values.get(t, np.nan), truncated[name].get(t, np.nan), name)


def test_cutoff_hides_future_rows_even_if_passed_in() -> None:
    t = INDEX[200]
    poisoned = SERIES.copy()
    poisoned[poisoned.index >= t] = 1e9
    for name, values in _features(poisoned, t).items():
        assert values.max() < 1e9, name
