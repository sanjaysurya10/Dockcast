from datetime import date

import numpy as np
import pandas as pd
import pytest

from dockcast.features.matrix import (
    build_grid,
    calendar_features,
    feature_columns,
    feature_matrix,
    fit_station_hour_encoding,
)
from dockcast.quality.gaps import Gap
from tests.unit.test_targets_backtest import T0, make_panel

pytestmark = pytest.mark.unit

CALENDAR = pd.DataFrame(
    {
        "date": [date(2025, 10, 27), date(2025, 10, 28)],
        "is_public_holiday": [True, False],  # October bank holiday 2025
        "is_school_term": [False, None],
        "is_uni_term": [True, True],
    }
)
INFO = pd.DataFrame({"station_key": [1, 2], "lat": [53.34, 53.35], "lon": [-6.26, -6.27]})


def _features(panel: pd.DataFrame, t: pd.Timestamp, horizon: int = 60, gaps=()) -> pd.DataFrame:
    grid = build_grid(panel, list(gaps), t)
    rows = pd.DataFrame({"station_key": [1, 2], "issued_at": [t, t]})
    enc = fit_station_hour_encoding(panel, t)
    return feature_matrix(grid, rows, horizon, CALENDAR, INFO, enc)


def test_lags_seasonal_rolling_match_states() -> None:
    panel = make_panel()
    t = T0 + pd.Timedelta(days=8, hours=6)
    f = _features(panel, t).iloc[0]
    s = panel[panel.station_key == 1].set_index("state_ts")["bikes"]
    q = pd.Timedelta(minutes=15)
    assert f["bikes_now"] == s[t]
    assert f["bikes_lag1"] == s[t - q] and f["bikes_lag8"] == s[t - 8 * q]
    assert f["bikes_seasonal_1d"] == s[t + 4 * q - pd.Timedelta(days=1)]
    assert f["bikes_seasonal_7d"] == s[t + 4 * q - pd.Timedelta(days=7)]
    assert f["bikes_roll4_mean"] == pytest.approx(s[t - 3 * q : t].mean())
    assert f["change_1"] == s[t] - s[t - q]
    assert f["ratio_now"] == pytest.approx(s[t] / 30)
    assert f["capacity"] == 30 and f["lat"] == 53.34


def test_gap_makes_lags_and_rolling_nan() -> None:
    panel = make_panel()
    t = T0 + pd.Timedelta(days=8, hours=6)
    gap = Gap(
        (t - pd.Timedelta(minutes=50)).to_pydatetime(),
        (t - pd.Timedelta(minutes=35)).to_pydatetime(),
        "hist_b",
        "hist_b",
    )
    f = _features(panel, t, gaps=[gap]).iloc[0]
    assert np.isnan(f["bikes_lag3"])  # bucket ending t-45 overlaps the gap
    assert np.isnan(f["bikes_roll4_mean"])  # window includes it
    assert not np.isnan(f["bikes_now"]) and not np.isnan(f["bikes_lag1"])


def test_zero_counts() -> None:
    panel = make_panel()
    panel.loc[panel.station_key == 1, "bikes"] = 0.0
    t = T0 + pd.Timedelta(days=8)
    assert _features(panel, t).iloc[0]["zero_bikes_24h"] == 96


def test_calendar_features_local_time_and_unknown_terms() -> None:
    ts = pd.Series(
        pd.to_datetime(["2025-10-26 00:30", "2025-10-26 01:30", "2025-10-28 12:00"], utc=True)
    )
    cal = calendar_features(ts, CALENDAR)
    # 00:30 UTC on DST day = 01:30 IST; 01:30 UTC = 01:30 GMT (clocks went back at 01:00 UTC)
    assert list(cal.hour_local) == [1, 1, 12]
    assert cal.is_school_term.isna().iloc[2]  # None in calendar_days -> NaN, not False
    assert cal.days_to_next_holiday.iloc[0] == 1.0  # 26 Oct -> 27 Oct bank holiday
    assert cal.is_weekend.iloc[0] == 1.0 and cal.is_weekend.iloc[2] == 0.0


def test_feature_columns_cover_matrix() -> None:
    f = _features(make_panel(), T0 + pd.Timedelta(days=8))
    assert set(feature_columns()) <= set(f.columns)
    assert "y" not in feature_columns()
