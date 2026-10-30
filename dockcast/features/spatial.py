"""Neighbour features (PRD 10.5) on the dense state grid.

Neighbours of a station are the ``k`` nearest other stations within ``radius_m`` (haversine).
Every value reads neighbours' states at the issue time ``t`` (bucket ending at ``t``, i.e.
observations ``< t``) or earlier, the same cut-off rule as the station's own lags (PRD 10.1);
gap buckets are already NaN in the grid, so nothing crosses a gap. Columns carry the radius,
e.g. ``nb600_ratio_mean``, so several radii can sit side by side in one matrix (E4).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

EARTH_RADIUS_M = 6_371_000.0
SPATIAL_FEATURES = ("ratio_mean", "change_4_mean", "zero_count", "bikes_total", "ratio_idw")


@dataclass(frozen=True)
class Neighbours:
    """Neighbour sets for the grid's station columns."""

    radius_m: float
    index: list[np.ndarray]  # per station column: neighbour column positions (k nearest)
    distance_m: list[np.ndarray]  # matching distances
    within: list[np.ndarray]  # per station column: every other station within the radius


def haversine_m(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Pairwise great-circle distances in metres.

    Args:
        lat: Latitudes in degrees.
        lon: Longitudes in degrees.

    Returns:
        Square distance matrix.
    """
    phi, lam = np.radians(lat)[:, None], np.radians(lon)[:, None]
    dphi, dlam = phi - phi.T, lam - lam.T
    a = np.sin(dphi / 2) ** 2 + np.cos(phi) * np.cos(phi.T) * np.sin(dlam / 2) ** 2
    distance: np.ndarray = 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    return distance


def neighbour_sets(
    stations: np.ndarray, station_info: pd.DataFrame, k: int, radius_m: float
) -> Neighbours:
    """Nearest ``k`` stations within ``radius_m`` for each grid column.

    Args:
        stations: Grid station keys (column order).
        station_info: ``station_key, lat, lon``.
        k: Maximum neighbours.
        radius_m: Search radius in metres.

    Returns:
        Neighbour sets; stations without coordinates get none.
    """
    info = station_info.set_index("station_key").reindex(stations)
    dist = haversine_m(info["lat"].to_numpy(dtype=float), info["lon"].to_numpy(dtype=float))
    np.fill_diagonal(dist, np.inf)
    dist = np.where(np.isnan(dist), np.inf, dist)
    index, distance, within = [], [], []
    for row in dist:
        inside = np.flatnonzero(row <= radius_m)
        nearest = inside[np.argsort(row[inside], kind="stable")][:k]
        index.append(nearest)
        distance.append(row[nearest])
        within.append(inside)
    return Neighbours(radius_m, index, distance, within)


def _mean_over(matrix: np.ndarray, cols: np.ndarray, weights: np.ndarray | None) -> np.ndarray:
    """Row-wise (weighted) mean over ``cols`` ignoring NaN; NaN when nothing is known."""
    if len(cols) == 0:
        return np.full(matrix.shape[0], np.nan)
    part = matrix[:, cols]
    w = np.ones(len(cols)) if weights is None else weights
    known = ~np.isnan(part)
    total = np.where(known, part, 0.0) @ w
    norm = known.astype(float) @ w
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(norm > 0, total / norm, np.nan)


def _count_over(matrix: np.ndarray, cols: np.ndarray, how: str) -> np.ndarray:
    """Row-wise count of zeros or sum over ``cols``; NaN when every value is missing."""
    if len(cols) == 0:
        return np.full(matrix.shape[0], np.nan)
    part = matrix[:, cols]
    any_known = (~np.isnan(part)).any(axis=1)
    value = (part == 0).sum(axis=1).astype(float) if how == "zeros" else np.nansum(part, axis=1)
    return np.where(any_known, value, np.nan)


def spatial_matrices(
    bikes: np.ndarray, capacity: np.ndarray, neighbours: Neighbours
) -> dict[str, np.ndarray]:
    """Neighbour feature matrices ``[time, station]`` aligned with the grid.

    Args:
        bikes: Grid bikes (gap buckets NaN).
        capacity: Grid capacity in force.
        neighbours: Output of :func:`neighbour_sets`.

    Returns:
        One matrix per name in :data:`SPATIAL_FEATURES`.
    """
    ratio = bikes / np.where(capacity > 0, capacity, np.nan)
    change_4 = np.full_like(bikes, np.nan)
    change_4[4:] = bikes[4:] - bikes[:-4]
    n = bikes.shape[1]
    out = {name: np.full_like(bikes, np.nan) for name in SPATIAL_FEATURES}
    for col in range(n):
        idx, dist = neighbours.index[col], neighbours.distance_m[col]
        out["ratio_mean"][:, col] = _mean_over(ratio, idx, None)
        out["change_4_mean"][:, col] = _mean_over(change_4, idx, None)
        out["zero_count"][:, col] = _count_over(bikes, idx, "zeros")
        out["bikes_total"][:, col] = _count_over(bikes, neighbours.within[col], "sum")
        out["ratio_idw"][:, col] = _mean_over(ratio, idx, 1.0 / np.maximum(dist, 1.0))
    return out


def spatial_columns(radius_m: float) -> list[str]:
    """Feature names for one radius.

    Args:
        radius_m: Radius in metres.

    Returns:
        Column names, e.g. ``nb600_ratio_mean``.
    """
    return [f"nb{int(radius_m)}_{name}" for name in SPATIAL_FEATURES]
