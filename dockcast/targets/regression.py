"""Panel of station states on the 15-min grid and regression targets (PRD 11.1).

Time convention: the *state at T* is ``bikes_last`` of the 15-min bucket that **ends** at ``T``
(bucket start ``T - 15 min``). A forecast issued at ``t`` may use states at times ``<= t`` (all
observations ``< t``, PRD 10.1) and predicts the state at ``T = t + h``.

Target validity (owner decision 2026-10-26): the target bucket must be observed and not closed,
imputed or flat-lined. Rebalance-flagged targets stay in and are reported as a slice.
"""

from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import Engine, text

BUCKET = timedelta(minutes=15)
HORIZONS_MIN = (30, 60, 120)

PANEL_SQL = text(
    """
    WITH cap AS (
        SELECT station_key, valid_from, capacity,
               lead(valid_from, 1, 'infinity') OVER (PARTITION BY station_key
                                                     ORDER BY valid_from) AS valid_to
        FROM station_capacity
    )
    SELECT b.station_key,
           b.ts + INTERVAL '15 minutes' AS state_ts,
           b.bikes_last AS bikes,
           b.docks_last AS docks,
           (b.n_obs > 0 AND NOT b.is_closed AND NOT b.is_imputed AND NOT b.flatline_flag)
               AS target_ok,
           b.rebalance_flag,
           c.capacity
    FROM station_status_15m b
    LEFT JOIN cap c ON c.station_key = b.station_key
                   AND b.ts >= c.valid_from AND b.ts < c.valid_to
    WHERE b.ts >= :start AND b.ts < :end
    ORDER BY b.station_key, b.ts
    """
)


def load_panel(engine: Engine, start: datetime, end: datetime) -> pd.DataFrame:
    """States with ``start <= state_ts - 15 min < end``.

    Args:
        engine: Database engine.
        start: Earliest bucket start.
        end: Exclusive latest bucket start.

    Returns:
        Columns ``station_key, state_ts, bikes, docks, target_ok, rebalance_flag, capacity``.
    """
    with engine.connect() as conn:
        result = conn.execute(PANEL_SQL, {"start": start, "end": end})
        frame = pd.DataFrame(result.fetchall(), columns=list(result.keys()))
    frame["state_ts"] = pd.to_datetime(frame["state_ts"], utc=True)
    frame["bikes"] = frame["bikes"].astype(float)
    frame["docks"] = frame["docks"].astype(float)
    frame["capacity"] = pd.to_numeric(frame["capacity"], errors="coerce")
    frame["target_ok"] = frame["target_ok"].astype(bool)
    frame["rebalance_flag"] = frame["rebalance_flag"].astype(bool)
    return frame


def issue_times(start: datetime, end: datetime, horizon_min: int) -> pd.DatetimeIndex:
    """Issue times ``t`` on the 15-min grid in ``[start, end)`` whose target ``t + h <= end``.

    Args:
        start: Window start (UTC).
        end: Window end (UTC, exclusive for issue times).
        horizon_min: Horizon in minutes.

    Returns:
        Issue times.
    """
    last = pd.Timestamp(end) - pd.Timedelta(minutes=horizon_min)
    return pd.date_range(pd.Timestamp(start), last, freq="15min", inclusive="both")


def targets(panel: pd.DataFrame, times: pd.DatetimeIndex, horizon_min: int) -> pd.DataFrame:
    """Target rows for every station and issue time.

    Args:
        panel: Output of :func:`load_panel`.
        times: Issue times.
        horizon_min: Horizon in minutes.

    Returns:
        Columns ``station_key, issued_at, target_ts, y, target_ok, rebalance_flag, capacity``;
        ``y`` is NaN and ``target_ok`` False where the target bucket is missing.
    """
    stations = sorted(int(k) for k in panel["station_key"].unique())
    grid = pd.MultiIndex.from_product(
        [stations, times], names=["station_key", "issued_at"]
    ).to_frame(index=False)
    grid["target_ts"] = grid["issued_at"] + pd.Timedelta(minutes=horizon_min)
    states = panel.rename(columns={"state_ts": "target_ts", "bikes": "y"})
    out = grid.merge(
        states[["station_key", "target_ts", "y", "target_ok", "rebalance_flag", "capacity"]],
        on=["station_key", "target_ts"],
        how="left",
    )
    out["target_ok"] = out["target_ok"].fillna(False).astype(bool) & out["y"].notna()
    out["rebalance_flag"] = out["rebalance_flag"].fillna(False).astype(bool)
    return out
