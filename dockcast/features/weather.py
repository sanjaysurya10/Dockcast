"""Oracle weather features (PRD 10.1 v1, 10.7) — observed weather at the target time.

**Oracle weather is not available at prediction time.** It is the observed Dublin Airport
weather in the hour that contains the target bucket, an upper bound on what a weather forecast
could add; every report that uses it must say so (CLAUDE.md §3). Met Éireann's ``ts`` closes the
hour (``rain`` is the amount in the hour ending at ``ts``), so the 15-min bucket ending at
``target_ts`` is matched to ``ts = ceil(target_ts, 1 h)``. ``precip_next_hour`` (forecast only)
is not built here.
"""

from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import Engine, text

RAIN_MM = 0.2
WEATHER_COLUMNS = ["temp_c", "precip_mm", "is_raining", "wind_speed_ms"]


def load_observed_weather(engine: Engine, start: datetime, end: datetime) -> pd.DataFrame:
    """Observed hourly weather with ``start <= ts <= end``.

    Args:
        engine: Database engine.
        start: First hour.
        end: Last hour.

    Returns:
        Columns ``ts, temp_c, precip_mm, wind_speed_ms`` (UTC).
    """
    query = text(
        "SELECT ts, temp_c, precip_mm, wind_speed_ms FROM weather_hourly "
        "WHERE kind = 'observed' AND ts BETWEEN :start AND :end ORDER BY ts"
    )
    with engine.connect() as conn:
        frame = pd.read_sql(query, conn, params={"start": start, "end": end})
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    return frame


def oracle_weather(rows: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    """Add :data:`WEATHER_COLUMNS` from the observed hour containing each target bucket.

    Args:
        rows: Rows with ``target_ts``.
        weather: Output of :func:`load_observed_weather`.

    Returns:
        ``rows`` plus the weather columns (NaN where the hour is missing).
    """
    hourly = weather.set_index("ts")
    hour = rows["target_ts"].dt.ceil("h")
    out = rows.copy()
    for column in ("temp_c", "precip_mm", "wind_speed_ms"):
        out[column] = hour.map(hourly[column]).to_numpy(dtype=float)
    out["is_raining"] = np.where(
        out["precip_mm"].isna(), np.nan, (out["precip_mm"] > RAIN_MM).astype(float)
    )
    return out
