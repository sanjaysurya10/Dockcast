"""Full feature matrix (PRD 10.2-10.4) built on a dense time x station grid.

Every feature for a row issued at ``t`` reads only states at offsets ``<= 0`` from ``t`` (states
at or before ``t``: observations ``< t``, PRD 10.1). States whose bucket overlaps a data gap are
NaN before anything is computed, and rolling windows need every state present, so values never
cross a gap (PRD 9.8). Calendar features describe the **target** time ``T = t + h`` (known in
advance). The station x hour occupancy encoding is fitted on training rows only
(:func:`fit_station_hour_encoding`) and passed in, so it is computed inside each fold.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from dockcast.features.lags import BUCKET, gap_mask
from dockcast.features.registry import FEATURE_GROUPS
from dockcast.quality.gaps import Gap

TZ = "Europe/Dublin"
STEPS_PER_DAY = 96
LAGS = (1, 2, 3, 4, 8)
ROLLING = (4, 12)


@dataclass(frozen=True)
class StateGrid:
    """States as dense matrices ``[time, station]`` on the 15-min grid."""

    times: pd.DatetimeIndex  # state times (bucket ends), regular 15 min
    stations: np.ndarray  # station keys, column order
    bikes: np.ndarray
    docks: np.ndarray
    capacity: np.ndarray

    def index_of(self, ts: pd.Series) -> np.ndarray:
        """Row positions of state times (``-1`` when outside the grid)."""
        pos = ((ts - self.times[0]) / BUCKET).to_numpy()
        pos = np.where(np.isfinite(pos), pos, -1).astype(np.int64)
        return np.where((pos >= 0) & (pos < len(self.times)), pos, -1)


def build_grid(panel: pd.DataFrame, gaps: Sequence[Gap], cutoff: pd.Timestamp) -> StateGrid:
    """Dense grid of states known at ``cutoff`` with gap buckets masked.

    Args:
        panel: Columns ``station_key, state_ts, bikes, docks, capacity``.
        gaps: Data gaps.
        cutoff: Latest issue time that will use the grid; later states are dropped.

    Returns:
        The grid.
    """
    known = panel[panel["state_ts"] <= cutoff]
    times = pd.date_range(known["state_ts"].min(), cutoff, freq="15min")
    stations = np.sort(known["station_key"].unique())

    def dense(column: str) -> np.ndarray:
        wide = known.pivot_table(
            index="state_ts", columns="station_key", values=column, aggfunc="last"
        )
        return wide.reindex(index=times, columns=stations).to_numpy(dtype=float)

    bikes, docks, capacity = dense("bikes"), dense("docks"), dense("capacity")
    masked = gap_mask(pd.DatetimeIndex(times - BUCKET), gaps)
    bikes[masked, :] = np.nan
    docks[masked, :] = np.nan
    capacity = pd.DataFrame(capacity).ffill().to_numpy()  # capacity in force, carried forward
    return StateGrid(times, stations, bikes, docks, capacity)


def _gather(matrix: np.ndarray, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    out = np.full(len(rows), np.nan)
    ok = (rows >= 0) & (rows < matrix.shape[0]) & (cols >= 0)
    out[ok] = matrix[rows[ok], cols[ok]]
    return out


def _rolling(matrix: np.ndarray, window: int, stat: str) -> np.ndarray:
    frame = pd.DataFrame(matrix).rolling(window, min_periods=window)
    return (frame.mean() if stat == "mean" else frame.std()).to_numpy()


def _count_zeros(matrix: np.ndarray, window: int) -> np.ndarray:
    zeros = pd.DataFrame((matrix == 0).astype(float))
    zeros[pd.DataFrame(np.isnan(matrix))] = np.nan
    return zeros.rolling(window, min_periods=1).sum().to_numpy()


def calendar_features(target_ts: pd.Series, calendar: pd.DataFrame) -> pd.DataFrame:
    """PRD 10.2 features of the target time (local Europe/Dublin).

    Args:
        target_ts: Target times (UTC).
        calendar: ``calendar_days`` rows (``date, is_public_holiday, is_school_term,
            is_uni_term``).

    Returns:
        One row per target time.
    """
    local = target_ts.dt.tz_convert(TZ)
    minute = local.dt.hour * 60 + local.dt.minute
    dow = local.dt.dayofweek
    month = local.dt.month
    day = local.dt.date
    cal = calendar.set_index("date")
    holidays: list[date] = sorted(
        d for d, h in zip(calendar["date"], calendar["is_public_holiday"], strict=True) if h
    )

    def days_to_next(d: date) -> float:
        nxt = next((h for h in holidays if h >= d), None)
        return float((nxt - d).days) if nxt else np.nan

    def flag(column: str) -> np.ndarray:
        values = day.map(cal[column]) if len(cal) else pd.Series(np.nan, index=day.index)
        return pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)

    unique_days = {d: days_to_next(d) for d in day.unique()}
    return pd.DataFrame(
        {
            "hour_local": local.dt.hour.to_numpy(),
            "minute_sin": np.sin(2 * np.pi * minute / 1440).to_numpy(),
            "minute_cos": np.cos(2 * np.pi * minute / 1440).to_numpy(),
            "dow": dow.to_numpy(),
            "dow_sin": np.sin(2 * np.pi * dow / 7).to_numpy(),
            "dow_cos": np.cos(2 * np.pi * dow / 7).to_numpy(),
            "is_weekend": (dow >= 5).astype(float).to_numpy(),
            "is_public_holiday": flag("is_public_holiday"),
            "is_school_term": flag("is_school_term"),
            "is_uni_term": flag("is_uni_term"),
            "days_to_next_holiday": day.map(unique_days).to_numpy(dtype=float),
            "month_sin": np.sin(2 * np.pi * (month - 1) / 12).to_numpy(),
            "month_cos": np.cos(2 * np.pi * (month - 1) / 12).to_numpy(),
        },
        index=target_ts.index,
    )


def fit_station_hour_encoding(panel: pd.DataFrame, train_end: pd.Timestamp) -> pd.Series:
    """Mean occupancy ratio per (station, local hour) from states before ``train_end``.

    Args:
        panel: Panel with ``bikes`` and ``capacity``.
        train_end: Only states with ``state_ts < train_end`` are used (in-fold, PRD 10.4).

    Returns:
        Series indexed by ``(station_key, hour)``.
    """
    train = panel[(panel["state_ts"] < train_end) & panel["bikes"].notna()]
    hour = train["state_ts"].dt.tz_convert(TZ).dt.hour
    ratio = train["bikes"] / train["capacity"].where(train["capacity"] > 0)
    return ratio.groupby([train["station_key"], hour]).mean()


def feature_matrix(
    grid: StateGrid,
    rows: pd.DataFrame,
    horizon_min: int,
    calendar: pd.DataFrame,
    station_info: pd.DataFrame,
    encoding: pd.Series,
) -> pd.DataFrame:
    """Features for ``rows`` (``station_key, issued_at``), all at or before each issue time.

    Args:
        grid: States known at the latest issue time.
        rows: Rows to featurise.
        horizon_min: Horizon in minutes.
        calendar: ``calendar_days`` rows.
        station_info: ``station_key, lat, lon``.
        encoding: Output of :func:`fit_station_hour_encoding` (training rows only).

    Returns:
        ``rows`` plus every column in :data:`FEATURE_GROUPS`.
    """
    col_of = {int(k): i for i, k in enumerate(grid.stations)}
    cols = rows["station_key"].map(col_of).fillna(-1).astype(np.int64).to_numpy()
    now = grid.index_of(rows["issued_at"])
    steps = horizon_min // 15
    cap = _gather(grid.capacity, now, cols)
    out = rows.copy()
    out["bikes_now"] = _gather(grid.bikes, now, cols)
    out["docks_now"] = _gather(grid.docks, now, cols)
    out["ratio_now"] = out["bikes_now"] / np.where(cap > 0, cap, np.nan)
    for k in LAGS:
        out[f"bikes_lag{k}"] = _gather(grid.bikes, np.where(now >= 0, now - k, -1), cols)
        out[f"ratio_lag{k}"] = out[f"bikes_lag{k}"] / np.where(cap > 0, cap, np.nan)
    for days, name in ((1, "bikes_seasonal_1d"), (7, "bikes_seasonal_7d")):
        offset = steps - days * STEPS_PER_DAY  # always < 0 for horizons below one day
        out[name] = _gather(grid.bikes, np.where(now >= 0, now + offset, -1), cols)
    for window in ROLLING:
        for stat in ("mean", "std"):
            out[f"bikes_roll{window}_{stat}"] = _gather(
                _rolling(grid.bikes, window, stat), now, cols
            )
    out["change_1"] = out["bikes_now"] - out["bikes_lag1"]
    out["change_4"] = out["bikes_now"] - out["bikes_lag4"]
    out["acceleration"] = out["change_1"] - (out["bikes_lag1"] - out["bikes_lag2"])
    out["zero_bikes_24h"] = _gather(_count_zeros(grid.bikes, STEPS_PER_DAY), now, cols)
    out["zero_docks_24h"] = _gather(_count_zeros(grid.docks, STEPS_PER_DAY), now, cols)
    out["capacity"] = cap
    info = station_info.set_index("station_key")
    out["lat"] = rows["station_key"].map(info["lat"]).to_numpy(dtype=float)
    out["lon"] = rows["station_key"].map(info["lon"]).to_numpy(dtype=float)
    target_ts = out["issued_at"] + pd.Timedelta(minutes=horizon_min)
    cal = calendar_features(target_ts, calendar)
    for column in cal.columns:
        out[column] = cal[column].to_numpy()
    keys = pd.MultiIndex.from_arrays([out["station_key"], out["hour_local"]])
    out["te_station_hour"] = encoding.reindex(keys).to_numpy(dtype=float)
    return out


def feature_columns(groups: Sequence[str] | None = None) -> list[str]:
    """Feature names for the selected groups (all groups by default).

    Args:
        groups: Group names from :data:`FEATURE_GROUPS`.

    Returns:
        Column names in a stable order.
    """
    chosen = groups or list(FEATURE_GROUPS)
    return [c for g in chosen for c in FEATURE_GROUPS[g]]
