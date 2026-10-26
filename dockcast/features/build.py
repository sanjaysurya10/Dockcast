"""Feature matrix assembly with a cut-off (PRD 10.1).

M3 only needs the baseline inputs:

- ``bikes_now``: state at the issue time ``t`` (bucket ending at ``t``; observations ``< t``).
- ``bikes_seasonal_7d``: state at ``t + h - 7 days`` (always before ``t`` for ``h <= 7 days``).

Both read the panel only through :func:`visible_states`, which drops every state after the
cut-off and masks states whose bucket overlaps a data gap (PRD 9.8).
"""

from collections.abc import Sequence
from datetime import timedelta

import pandas as pd

from dockcast.features.lags import BUCKET, gap_mask
from dockcast.quality.gaps import Gap

SEASON = timedelta(days=7)
FEATURE_COLUMNS = ["bikes_now", "bikes_seasonal_7d"]


def visible_states(panel: pd.DataFrame, cutoff: pd.Timestamp, gaps: Sequence[Gap]) -> pd.DataFrame:
    """States known at ``cutoff``: ``state_ts <= cutoff``, gap buckets set to NaN.

    Args:
        panel: Columns ``station_key, state_ts, bikes``.
        cutoff: Latest issue time that will use these states.
        gaps: Data gaps.

    Returns:
        ``station_key, state_ts, bikes`` restricted to the cut-off.
    """
    known = panel.loc[panel["state_ts"] <= cutoff, ["station_key", "state_ts", "bikes"]].copy()
    bucket_start = pd.DatetimeIndex(known["state_ts"] - BUCKET)
    known.loc[gap_mask(bucket_start, gaps), "bikes"] = float("nan")
    return known


def baseline_features(
    panel: pd.DataFrame,
    rows: pd.DataFrame,
    horizon_min: int,
    gaps: Sequence[Gap],
) -> pd.DataFrame:
    """Add baseline input columns to ``rows`` using only states visible at each issue time.

    Every state read is at or before its row's ``issued_at``: ``bikes_now`` reads the state at
    ``issued_at``; ``bikes_seasonal_7d`` reads ``issued_at + h - 7 days``. A single cut-off at
    the latest issue time is therefore enough (no row can see a later state).

    Args:
        panel: Output of :func:`dockcast.targets.regression.load_panel`.
        rows: Columns ``station_key, issued_at`` (plus anything else, passed through).
        horizon_min: Horizon in minutes.
        gaps: Data gaps.

    Returns:
        ``rows`` with ``FEATURE_COLUMNS`` added (NaN when the state is unknown).
    """
    if rows.empty:
        return rows.assign(**{c: pd.Series(dtype=float) for c in FEATURE_COLUMNS})
    states = visible_states(panel, rows["issued_at"].max(), gaps)
    out = rows.copy()
    out["_now_ts"] = out["issued_at"]
    out["_seasonal_ts"] = out["issued_at"] + pd.Timedelta(minutes=horizon_min) - SEASON
    for column, key in (("bikes_now", "_now_ts"), ("bikes_seasonal_7d", "_seasonal_ts")):
        lookup = states.rename(columns={"state_ts": key, "bikes": column})
        out = out.merge(lookup, on=["station_key", key], how="left")
    return out.drop(columns=["_now_ts", "_seasonal_ts"])
