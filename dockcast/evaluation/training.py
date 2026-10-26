"""Per-fold training, validation and test sets (PRD 13.1, M4 owner decision 2026-10-26).

- train: issue times on the hour, from ``data_start + 8 days`` (7-day seasonal lookback) until
  the last training week; targets before the validation week.
- valid: every 15-min issue time in the last training week (early stopping, PRD 12.3); its
  targets end before ``train_end``.
- test: every 15-min issue time in the test window (unchanged from M3).

One state grid per fold is built with the latest issue time as cut-off; each row still reads
only states at or before its own issue time (``tests/leakage``). The station x hour encoding is
fitted on states before ``train_end`` only.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from dockcast.evaluation.backtest import add_slices
from dockcast.evaluation.splits import Fold
from dockcast.features.matrix import build_grid, feature_matrix, fit_station_hour_encoding
from dockcast.quality.gaps import Gap
from dockcast.targets.regression import issue_times, targets

VALID_WINDOW = timedelta(days=7)
LOOKBACK = timedelta(days=8)


@dataclass
class FoldData:
    """Featurised rows for one fold and horizon."""

    train: pd.DataFrame
    valid: pd.DataFrame
    test: pd.DataFrame


def hourly_issue_times(start: datetime, end: datetime, horizon_min: int) -> pd.DatetimeIndex:
    """Issue times on the hour in ``[start, end - h]`` (targets ``<= end``).

    Args:
        start: First allowed issue time.
        end: Latest allowed target time.
        horizon_min: Horizon in minutes.

    Returns:
        Hourly issue times.
    """
    times = issue_times(start, end, horizon_min)
    return times[times.minute == 0]


def prepare_fold(
    panel: pd.DataFrame,
    fold: Fold,
    horizon_min: int,
    gaps: Sequence[Gap],
    calendar: pd.DataFrame,
    station_info: pd.DataFrame,
    data_start: datetime,
) -> FoldData:
    """Build train / valid / test rows with features, targets and slice columns.

    Args:
        panel: States from ``data_start`` to the fold's test end.
        fold: Fold.
        horizon_min: Horizon in minutes.
        gaps: Data gaps.
        calendar: ``calendar_days`` rows.
        station_info: ``station_key, lat, lon``.
        data_start: First usable state time.

    Returns:
        The fold's data. Train/valid keep only valid targets; test keeps all rows.
    """
    step = timedelta(minutes=15)
    valid_start = fold.train_end - VALID_WINDOW
    grid = build_grid(panel, gaps, pd.Timestamp(fold.test_end))
    encoding = fit_station_hour_encoding(panel, pd.Timestamp(fold.train_end))
    first = pd.Timestamp(data_start).ceil("h") + LOOKBACK
    spans = {
        "train": hourly_issue_times(first, valid_start - step, horizon_min),
        "valid": issue_times(valid_start, fold.train_end - step, horizon_min),
        "test": issue_times(fold.test_start, fold.test_end, horizon_min),
    }
    frames: dict[str, pd.DataFrame] = {}
    for name, times in spans.items():
        rows = targets(panel, times, horizon_min)
        if name != "test":
            rows = rows[rows["target_ok"]].reset_index(drop=True)
        featured = feature_matrix(grid, rows, horizon_min, calendar, station_info, encoding)
        frames[name] = add_slices(featured)
    return FoldData(frames["train"], frames["valid"], frames["test"])
