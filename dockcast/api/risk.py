"""Interim empty/full risk levels from the regression forecast range (owner decision 2026-11-01).

Event classifiers (E5, M10) need 12 weeks of collector data, so until then risk comes from the
quantile forecast, not from a probability:

- **likely**: P50 is within ``NEAR_ZERO`` of empty (bikes) or of full (free docks).
- **possible**: P50 is not, but the P10 tail (empty) or the P90 tail (full) is. E6 measured those
  tails at about 9-10 % of outcomes (run ``9f9688d815da4c4298891cfdd044219f``).
- **low**: otherwise.

``NEAR_ZERO`` = 0.5 bikes is the PRD 16.3 "ETA to empty/full" rule (first horizon where
P50 <= 0.5).
"""

from collections.abc import Mapping, Sequence
from typing import Literal

NEAR_ZERO = 0.5
Level = Literal["likely", "possible", "low"]
Kind = Literal["empty", "full"]
LEVEL_RANK: dict[Level, int] = {"likely": 0, "possible": 1, "low": 2}


def empty_level(p10: float, p50: float) -> Level:
    """Risk that the station has no bikes."""
    if p50 <= NEAR_ZERO:
        return "likely"
    return "possible" if p10 <= NEAR_ZERO else "low"


def full_level(p50: float, p90: float, capacity: int) -> Level:
    """Risk that the station has no free docks (free docks = capacity - bikes)."""
    if capacity - p50 <= NEAR_ZERO:
        return "likely"
    return "possible" if capacity - p90 <= NEAR_ZERO else "low"


def eta_min(forecasts: Sequence[Mapping[str, float]], kind: Kind, capacity: int) -> int | None:
    """First horizon (minutes) where P50 is empty or full, or None (PRD 16.3 item 6).

    Args:
        forecasts: Rows with ``horizon_min`` and ``bikes_p50``, in any order.
        kind: ``empty`` or ``full``.
        capacity: Docks at the station.

    Returns:
        The earliest such horizon, or None.
    """
    for row in sorted(forecasts, key=lambda r: r["horizon_min"]):
        free = row["bikes_p50"] if kind == "empty" else capacity - row["bikes_p50"]
        if free <= NEAR_ZERO:
            return int(row["horizon_min"])
    return None


def rank_key(level: Level, p50: float, capacity: int, kind: Kind) -> tuple[int, float]:
    """Sort key: level first, then fewest forecast bikes (empty) or free docks (full)."""
    free = p50 if kind == "empty" else capacity - p50
    return LEVEL_RANK[level], free
