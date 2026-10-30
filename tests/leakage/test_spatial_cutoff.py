"""Spatial features read nothing after the issue time (CLAUDE.md §3, PRD 10.5, 19.2)."""

import numpy as np
import pandas as pd
import pytest

from dockcast.features.matrix import build_grid, feature_matrix, fit_station_hour_encoding
from dockcast.features.spatial import neighbour_sets, spatial_columns
from dockcast.quality.gaps import Gap
from tests.unit.test_feature_matrix import CALENDAR
from tests.unit.test_spatial import INFO
from tests.unit.test_targets_backtest import T0, make_panel

pytestmark = pytest.mark.leakage

RNG = np.random.default_rng(23)
KEYS = (1, 2, 3, 4)
PANEL = make_panel(days=15, stations=KEYS)
PANEL["bikes"] = RNG.integers(0, 30, len(PANEL)).astype(float)
GAPS = [
    Gap(
        (T0 + pd.Timedelta(days=9, hours=2)).to_pydatetime(),
        (T0 + pd.Timedelta(days=9, hours=3)).to_pydatetime(),
        "hist_b",
        "hist_b",
    )
]
ENCODING = fit_station_hour_encoding(PANEL, T0 + pd.Timedelta(days=8))
TIMES = [T0 + pd.Timedelta(days=8, minutes=15 * int(k)) for k in RNG.integers(0, 4 * 96, 12)]
COLUMNS = [c for r in (400, 600, 800) for c in spatial_columns(r)]


def _spatial(panel: pd.DataFrame, t: pd.Timestamp, cutoff: pd.Timestamp) -> pd.DataFrame:
    grid = build_grid(panel, GAPS, cutoff)
    nbs = [neighbour_sets(grid.stations, INFO, 5, r) for r in (400, 600, 800)]
    rows = pd.DataFrame({"station_key": list(KEYS), "issued_at": [t] * len(KEYS)})
    return feature_matrix(grid, rows, 60, CALENDAR, INFO, ENCODING, nbs)[COLUMNS]


@pytest.mark.parametrize("t", TIMES)
def test_spatial_identical_when_data_after_t_deleted(t: pd.Timestamp) -> None:
    full = _spatial(PANEL, t, t + pd.Timedelta(days=2))
    truncated = _spatial(PANEL[PANEL.state_ts <= t], t, t)
    pd.testing.assert_frame_equal(full.reset_index(drop=True), truncated.reset_index(drop=True))
    assert full.notna().any().any()


def test_poisoned_future_never_reaches_spatial_features() -> None:
    t = TIMES[0]
    poisoned = PANEL.copy()
    poisoned.loc[poisoned.state_ts > t, "bikes"] = 1e6
    assert np.nanmax(_spatial(poisoned, t, t + pd.Timedelta(days=2)).to_numpy(dtype=float)) < 1e6


def test_neighbours_inside_a_gap_are_missing_not_carried() -> None:
    t = pd.Timestamp(GAPS[0].start) + pd.Timedelta(minutes=30)
    values = _spatial(PANEL, t, t + pd.Timedelta(days=1))
    assert values[[c for c in COLUMNS if "ratio_mean" in c]].isna().all().all()
