"""Leakage tests for every M4 feature (CLAUDE.md §3, PRD 19.2)."""

import numpy as np
import pandas as pd
import pytest

from dockcast.features.matrix import (
    build_grid,
    feature_columns,
    feature_matrix,
    fit_station_hour_encoding,
)
from dockcast.quality.gaps import Gap
from tests.unit.test_feature_matrix import CALENDAR, INFO
from tests.unit.test_targets_backtest import T0, make_panel

pytestmark = pytest.mark.leakage

RNG = np.random.default_rng(11)
PANEL = make_panel(days=15)
PANEL["bikes"] = RNG.integers(0, 30, len(PANEL)).astype(float)
PANEL["docks"] = 30 - PANEL["bikes"]
GAPS = [
    Gap(
        (T0 + pd.Timedelta(days=9, hours=2)).to_pydatetime(),
        (T0 + pd.Timedelta(days=9, hours=3)).to_pydatetime(),
        "hist_b",
        "hist_b",
    )
]
TRAIN_END = T0 + pd.Timedelta(days=8)
ENCODING = fit_station_hour_encoding(PANEL, TRAIN_END)
TIMES = [TRAIN_END + pd.Timedelta(minutes=15 * int(k)) for k in RNG.integers(0, 4 * 96, 15)]
COLUMNS = feature_columns()


def _row_features(
    panel: pd.DataFrame, t: pd.Timestamp, cutoff: pd.Timestamp, horizon: int
) -> pd.DataFrame:
    grid = build_grid(panel, GAPS, cutoff)
    rows = pd.DataFrame({"station_key": [1, 2], "issued_at": [t, t]})
    return feature_matrix(grid, rows, horizon, CALENDAR, INFO, ENCODING)[COLUMNS]


@pytest.mark.parametrize("t", TIMES)
@pytest.mark.parametrize("horizon", [30, 60, 120])
def test_every_feature_identical_when_data_after_t_deleted(t: pd.Timestamp, horizon: int) -> None:
    later = t + pd.Timedelta(days=2)
    full = _row_features(PANEL, t, later, horizon)
    truncated = _row_features(PANEL[PANEL.state_ts <= t], t, t, horizon)
    pd.testing.assert_frame_equal(full.reset_index(drop=True), truncated.reset_index(drop=True))


def test_poisoned_future_never_reaches_any_feature() -> None:
    t = TIMES[0]
    poisoned = PANEL.copy()
    poisoned.loc[poisoned.state_ts > t, ["bikes", "docks"]] = 1e6
    features = _row_features(poisoned, t, t + pd.Timedelta(days=2), 120)
    assert np.nanmax(features.to_numpy(dtype=float)) < 1e6


def test_station_hour_encoding_uses_training_rows_only() -> None:
    poisoned = PANEL.copy()
    poisoned.loc[poisoned.state_ts >= TRAIN_END, "bikes"] = 29.0
    pd.testing.assert_series_equal(fit_station_hour_encoding(poisoned, TRAIN_END), ENCODING)
