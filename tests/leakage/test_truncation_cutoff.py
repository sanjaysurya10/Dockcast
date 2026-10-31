"""E2b short-history stations read no state from before their history start."""

import numpy as np
import pandas as pd
import pytest

from dockcast.evaluation.training import prepare_fold
from dockcast.experiments.e2b import drop_warmup, history_start, truncate_panel
from tests.unit.test_e2b import short_fold
from tests.unit.test_models_m4 import CAL, INFO
from tests.unit.test_targets_backtest import T0, make_panel

pytestmark = pytest.mark.leakage


def _short_rows(panel: pd.DataFrame) -> list[pd.DataFrame]:
    fold = short_fold()
    start = history_start(fold, days=3)
    data = prepare_fold(
        truncate_panel(panel, [2], start), fold, 60, [], CAL, INFO, T0.to_pydatetime()
    )
    frames = [drop_warmup(data.train, [2], start), data.valid, data.test]
    return [f[f.station_key == 2].reset_index(drop=True) for f in frames]


def test_poisoned_early_history_does_not_change_short_station() -> None:
    panel = make_panel(days=24)
    poisoned = panel.copy()
    early = (poisoned.station_key == 2) & (poisoned.state_ts < history_start(short_fold(), days=3))
    assert early.any()
    poisoned.loc[early, "bikes"] = np.where(poisoned.loc[early, "bikes"] > 5, 0, 30)
    for clean, dirty in zip(_short_rows(panel), _short_rows(poisoned), strict=True):
        pd.testing.assert_frame_equal(clean, dirty)
