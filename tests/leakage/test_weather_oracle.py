"""Oracle weather reads only the observed hour containing each target bucket (PRD 10.1).

It is deliberately *not* cutoff-safe (labelled oracle in every report); this pins down that it
reads nothing beyond that one hour.
"""

import numpy as np
import pandas as pd
import pytest

from dockcast.features.weather import oracle_weather

pytestmark = pytest.mark.leakage


def test_only_the_target_hour_is_read() -> None:
    hours = pd.date_range("2026-05-06", periods=48, freq="h", tz="UTC")
    rng = np.random.default_rng(0)
    weather = pd.DataFrame(
        {
            "ts": hours,
            "temp_c": rng.normal(12, 3, 48),
            "precip_mm": rng.exponential(0.3, 48),
            "wind_speed_ms": rng.uniform(0, 10, 48),
        }
    )
    targets = pd.DataFrame(
        {"target_ts": pd.to_datetime(["2026-05-06 10:15", "2026-05-06 10:45"], utc=True)}
    )
    poisoned = weather.copy()
    others = poisoned["ts"] != pd.Timestamp("2026-05-06 11:00", tz="UTC")
    poisoned.loc[others, ["temp_c", "precip_mm", "wind_speed_ms"]] = 1e6
    pd.testing.assert_frame_equal(
        oracle_weather(targets, weather), oracle_weather(targets, poisoned)
    )
