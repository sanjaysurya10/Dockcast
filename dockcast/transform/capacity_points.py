"""Capacity change points (pure pandas helpers; no database imports)."""

from collections.abc import Iterable
from typing import Any

import pandas as pd

POINT_COLUMNS = ["station_key", "valid_from", "capacity", "source"]


def change_points(frame: pd.DataFrame) -> pd.DataFrame:
    """First observation of each new capacity value per station.

    Args:
        frame: Columns ``station_key``, ``observed_at``, ``capacity``, ``source``.

    Returns:
        Columns ``station_key, valid_from, capacity, source``.
    """
    ordered = frame.dropna(subset=["capacity"]).sort_values(["station_key", "observed_at"])
    previous = ordered.groupby("station_key")["capacity"].shift()
    changed = ordered[previous.isna() | (ordered["capacity"] != previous)]
    renamed = changed.rename(columns={"observed_at": "valid_from"})
    return renamed[POINT_COLUMNS].reset_index(drop=True)


def merge_points(points: Iterable[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate per-file change points and drop repeats of the same capacity.

    Args:
        points: Outputs of :func:`change_points`.

    Returns:
        Chronological change points per station.
    """
    frames = [p for p in points if not p.empty]
    if not frames:
        return pd.DataFrame(columns=POINT_COLUMNS)
    merged = pd.concat(frames).sort_values(["station_key", "valid_from"])
    previous = merged.groupby("station_key")["capacity"].shift()
    return merged[previous.isna() | (merged["capacity"] != previous)].reset_index(drop=True)


def point_records(points: pd.DataFrame) -> list[dict[str, Any]]:
    """Change points as plain-Python dicts ready for insertion.

    Args:
        points: Output of :func:`change_points` / :func:`merge_points`.

    Returns:
        One dict per change point.
    """
    return [
        {
            "station_key": int(row["station_key"]),
            "valid_from": pd.Timestamp(row["valid_from"]).to_pydatetime(),
            "capacity": int(row["capacity"]),
            "source": str(row["source"]),
        }
        for row in points.to_dict("records")
    ]
