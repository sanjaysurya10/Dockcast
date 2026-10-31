"""Prophet per station reads no state at or after the fold's training end (CLAUDE.md §3)."""

from datetime import date

import pandas as pd
import pytest

from dockcast.models.prophet_model import ProphetStation
from tests.unit.test_e2_models import hourly_states

pytestmark = pytest.mark.leakage

CUTOFF = pd.Timestamp("2026-03-18 12:00", tz="UTC")


def _predict(states: pd.DataFrame) -> pd.DataFrame:
    model = ProphetStation([date(2026, 3, 17)]).fit_states(states, CUTOFF)
    times = pd.date_range(CUTOFF + pd.Timedelta(hours=2), periods=12, freq="15min")
    return model.predict(pd.DataFrame({"station_key": 7, "target_ts": times}))


def test_poisoned_future_does_not_change_prophet() -> None:
    states = hourly_states()
    poisoned = states.copy()
    poisoned.loc[poisoned.state_ts >= CUTOFF, "bikes"] = 1e6
    pd.testing.assert_frame_equal(_predict(states), _predict(poisoned))


def test_prophet_identical_when_future_deleted() -> None:
    states = hourly_states()
    pd.testing.assert_frame_equal(_predict(states), _predict(states[states.state_ts < CUTOFF]))
