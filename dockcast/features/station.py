"""Station behaviour profiles for E3 clustering (PRD 13, E3).

A profile is the mean occupancy ratio (bikes / capacity in force) per local hour, separately for
weekdays (Mon-Fri) and weekends (Sat-Sun): 48 values per station. Only observed, open,
non-imputed, non-flat-lined 15-min states with ``state_ts < cutoff`` are read (PRD 10.1), so
labels fitted from a profile are in-fold when ``cutoff`` is the fold's training end.
"""

from datetime import datetime

import pandas as pd
from sqlalchemy import Engine, text

from dockcast.features.matrix import TZ

DAY_TYPES = ("weekday", "weekend")
HOURS = tuple(range(24))

PROFILE_SQL = text(
    """
    WITH cap AS (
        SELECT station_key, valid_from, capacity,
               lead(valid_from, 1, 'infinity') OVER (PARTITION BY station_key
                                                     ORDER BY valid_from) AS valid_to
        FROM station_capacity
    ),
    states AS (
        SELECT b.station_key,
               (b.ts + INTERVAL '15 minutes') AT TIME ZONE :tz AS local_ts,
               b.bikes_last::double precision / c.capacity AS ratio
        FROM station_status_15m b
        JOIN cap c ON c.station_key = b.station_key
                  AND b.ts >= c.valid_from AND b.ts < c.valid_to
        WHERE b.ts + INTERVAL '15 minutes' >= :start
          AND b.ts + INTERVAL '15 minutes' < :cutoff
          AND b.n_obs > 0 AND NOT b.is_closed AND NOT b.is_imputed AND NOT b.flatline_flag
          AND c.capacity > 0 AND b.bikes_last IS NOT NULL
    )
    SELECT station_key,
           CASE WHEN extract(isodow FROM local_ts) >= 6 THEN 'weekend' ELSE 'weekday' END
               AS day_type,
           extract(hour FROM local_ts)::int AS hour,
           avg(least(ratio, 1.0)) AS occupancy,
           count(*) AS n
    FROM states
    GROUP BY 1, 2, 3
    """
)


def load_profile_cells(
    engine: Engine, start: datetime, cutoff: datetime, tz: str = TZ
) -> pd.DataFrame:
    """Mean occupancy per (station, day type, local hour) from states in ``[start, cutoff)``.

    Args:
        engine: Database engine.
        start: Earliest state time (UTC).
        cutoff: Exclusive latest state time (UTC); nothing at or after it is read.
        tz: Local time zone for hour and day type.

    Returns:
        Columns ``station_key, day_type, hour, occupancy, n``.
    """
    with engine.connect() as conn:
        result = conn.execute(PROFILE_SQL, {"start": start, "cutoff": cutoff, "tz": tz})
        frame = pd.DataFrame(result.fetchall(), columns=list(result.keys()))
    frame["occupancy"] = frame["occupancy"].astype(float)
    frame["n"] = frame["n"].astype(int)
    return frame


def profile_matrix(cells: pd.DataFrame, min_obs: int) -> pd.DataFrame:
    """Wide profiles: one row per station, 48 columns ``weekday_00`` ... ``weekend_23``.

    Stations with any cell below ``min_obs`` states are dropped (no imputation of profiles).

    Args:
        cells: Output of :func:`load_profile_cells`.
        min_obs: Minimum states per (day type, hour) cell.

    Returns:
        Profiles indexed by ``station_key``, sorted by it.
    """
    columns = [f"{d}_{h:02d}" for d in DAY_TYPES for h in HOURS]
    if cells.empty:
        return pd.DataFrame(columns=columns, dtype=float)
    keyed = cells.assign(column=cells["day_type"] + "_" + cells["hour"].map("{:02d}".format))
    occupancy = keyed.pivot(index="station_key", columns="column", values="occupancy")
    counts = keyed.pivot(index="station_key", columns="column", values="n")
    occupancy = occupancy.reindex(columns=columns)
    counts = counts.reindex(columns=columns).fillna(0)
    complete = (counts >= min_obs).all(axis=1)
    return occupancy[complete].sort_index().astype(float)
