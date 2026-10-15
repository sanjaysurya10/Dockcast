"""Gap-aware lag and rolling features on one station's 15-min series (PRD 10.1, 10.3, 9.8).

Inputs are indexed by bucket start ``ts``. Outputs are indexed by prediction time ``t``; the
bucket ``[t - 15 min, t)`` is lag 1. Only buckets that close by ``cutoff`` are read, and any
bucket overlapping a data gap is treated as missing, so every lag/rolling value that reads it is
NaN (never forward-filled across a gap).
"""

from collections.abc import Sequence
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from dockcast.quality.gaps import Gap

BUCKET = timedelta(minutes=15)


def gap_mask(
    index: pd.DatetimeIndex, gaps: Sequence[Gap], bucket: timedelta = BUCKET
) -> np.ndarray:
    """True for buckets ``[ts, ts + bucket)`` overlapping a gap's open interval.

    Args:
        index: Bucket start times (UTC).
        gaps: Data gaps.
        bucket: Bucket length.

    Returns:
        Boolean array aligned with ``index``.
    """
    mask = np.zeros(len(index), dtype=bool)
    starts = index
    ends = index + bucket
    for gap in gaps:
        mask |= (starts < pd.Timestamp(gap.end)) & (ends > pd.Timestamp(gap.start))
    return mask


def _visible(
    series: pd.Series, gaps: Sequence[Gap], cutoff: datetime, bucket: timedelta
) -> pd.Series:
    """Regular-grid series of buckets that close by ``cutoff``, with gap buckets set to NaN."""
    starts = pd.DatetimeIndex(series.index)
    closed: pd.Series = series[(starts + bucket) <= pd.Timestamp(cutoff)].astype(float)
    if closed.empty:
        return closed
    grid: pd.Series = closed.asfreq(pd.offsets.Second(int(bucket.total_seconds())))
    masked: pd.Series = grid.mask(gap_mask(pd.DatetimeIndex(grid.index), gaps, bucket))
    return masked


def lag(
    series: pd.Series,
    steps: int,
    gaps: Sequence[Gap],
    cutoff: datetime,
    bucket: timedelta = BUCKET,
) -> pd.Series:
    """Value of the bucket ``steps`` buckets before each prediction time.

    Args:
        series: One station's values indexed by bucket start.
        steps: Lag in buckets (1 = the bucket ending at ``t``).
        gaps: Data gaps.
        cutoff: Only buckets ending at or before this time are read.
        bucket: Bucket length.

    Returns:
        Series indexed by prediction time ``t``.
    """
    visible = _visible(series, gaps, cutoff, bucket)
    shifted = visible.shift(steps - 1)
    shifted.index = visible.index + bucket
    return shifted


def rolling(
    series: pd.Series,
    window: int,
    stat: str,
    gaps: Sequence[Gap],
    cutoff: datetime,
    bucket: timedelta = BUCKET,
) -> pd.Series:
    """Rolling ``mean``/``std`` over the ``window`` buckets ending at each prediction time.

    A window containing any missing or gap bucket yields NaN.

    Args:
        series: One station's values indexed by bucket start.
        window: Window length in buckets.
        stat: ``"mean"`` or ``"std"``.
        gaps: Data gaps.
        cutoff: Only buckets ending at or before this time are read.
        bucket: Bucket length.

    Returns:
        Series indexed by prediction time ``t``.
    """
    visible = _visible(series, gaps, cutoff, bucket)
    roll = visible.rolling(window, min_periods=window)
    result = roll.mean() if stat == "mean" else roll.std()
    result.index = visible.index + bucket
    return result
