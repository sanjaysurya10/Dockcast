"""PRD 19.2 leakage checks for the M3 pipeline (targets, baseline features, folds)."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from dockcast.evaluation.splits import rolling_origin_folds
from dockcast.features.build import FEATURE_COLUMNS, baseline_features
from dockcast.quality.gaps import Gap
from dockcast.targets.regression import targets
from tests.unit.test_targets_backtest import T0, make_panel

pytestmark = pytest.mark.leakage

RNG = np.random.default_rng(7)
PANEL = make_panel(days=15, stations=(1, 2, 3))
PANEL["bikes"] = RNG.integers(0, 30, len(PANEL)).astype(float)  # no exploitable pattern
GAPS = [
    Gap(
        (T0 + pd.Timedelta(days=9, hours=3)).to_pydatetime(),
        (T0 + pd.Timedelta(days=9, hours=4)).to_pydatetime(),
        "hist_b",
        "hist_b",
    )
]
ISSUES = [
    T0 + pd.Timedelta(days=8) + pd.Timedelta(minutes=15 * int(k))
    for k in RNG.integers(0, 4 * 96, 20)
]


@pytest.mark.parametrize("t", ISSUES)
@pytest.mark.parametrize("horizon", [30, 60, 120])
def test_features_identical_when_data_after_t_deleted(t: pd.Timestamp, horizon: int) -> None:
    rows = targets(PANEL, pd.DatetimeIndex([t]), horizon)[["station_key", "issued_at"]]
    full = baseline_features(PANEL, rows, horizon, GAPS)
    truncated = baseline_features(PANEL[PANEL.state_ts <= t], rows, horizon, GAPS)
    pd.testing.assert_frame_equal(
        full[FEATURE_COLUMNS].reset_index(drop=True),
        truncated[FEATURE_COLUMNS].reset_index(drop=True),
    )


def test_future_values_cannot_reach_features() -> None:
    t = ISSUES[0]
    poisoned = PANEL.copy()
    poisoned.loc[poisoned.state_ts > t, "bikes"] = 1e9
    rows = targets(poisoned, pd.DatetimeIndex([t]), 120)
    feats = baseline_features(poisoned, rows, 120, GAPS)
    assert feats[FEATURE_COLUMNS].max().max() < 1e9
    assert (feats["y"] == 1e9).all()  # the target itself does see the future, as it must


def test_target_never_used_as_feature() -> None:
    rows = targets(PANEL, pd.DatetimeIndex(ISSUES), 60)
    feats = baseline_features(PANEL, rows, 60, GAPS)
    assert not any(c in {"y", "target_ts", "target_ok"} for c in FEATURE_COLUMNS)
    for column in FEATURE_COLUMNS:
        both = feats[[column, "y"]].dropna()
        assert not (both[column] == both["y"]).all(), column  # random series: no identity


def test_fold_gap_separates_training_targets_from_test() -> None:
    folds = rolling_origin_folds(
        datetime(2024, 5, 2, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC), [], 8, 7, 120
    )
    for fold in folds:
        assert fold.test_start - fold.train_end == timedelta(minutes=120)
        # training rows have target_ts < train_end, so the latest training target ends
        # >= 120 min (the max horizon) before the first test issue time
        latest_training_target = fold.train_end - timedelta(minutes=15)
        assert fold.test_start - latest_training_target > timedelta(minutes=120)
