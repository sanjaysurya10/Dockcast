"""Reconcile historical station IDs to ``stations`` (PRD 5.4 item 4, 9.2 step 4).

Order: exact ID match, else normalised name + coordinates within 30 m, else a new station.
"""

import math
import re
from dataclasses import dataclass

import pandas as pd

MATCH_RADIUS_M = 30.0
EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class KnownStation:
    """A row already in ``stations``."""

    station_key: int
    source_id: str
    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Match:
    """Result of reconciling one legacy station ID."""

    legacy_id: str
    station_key: int | None  # None => create a new station
    method: str  # 'exact' | 'name+coords' | 'new'
    distance_m: float | None
    warning: str | None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres.

    Args:
        lat1: Latitude of point 1 (degrees).
        lon1: Longitude of point 1 (degrees).
        lat2: Latitude of point 2 (degrees).
        lon2: Longitude of point 2 (degrees).

    Returns:
        Distance in metres.
    """
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def normalise_name(name: str) -> str:
    """Upper-case, strip punctuation and collapse whitespace.

    Args:
        name: Station name.

    Returns:
        Normalised name.
    """
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", name.upper())).strip()


def legacy_stations(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per legacy ID with its most recent name and median coordinates.

    Args:
        frame: Canonical rows (``source_id``, ``name``, ``lat``, ``lon``, ``observed_at``).

    Returns:
        Columns ``source_id, name, lat, lon, first_seen, last_seen``.
    """
    ordered = frame.sort_values("observed_at")
    grouped = ordered.groupby("source_id")
    return pd.DataFrame(
        {
            "name": grouped["name"].last(),
            "lat": grouped["lat"].median(),
            "lon": grouped["lon"].median(),
            "first_seen": grouped["observed_at"].min(),
            "last_seen": grouped["observed_at"].max(),
        }
    ).reset_index()


def reconcile(
    legacy_id: str, name: str, lat: float, lon: float, known: list[KnownStation]
) -> Match:
    """Match one legacy station against known stations.

    Args:
        legacy_id: Station ID in the historical file.
        name: Its name.
        lat: Its latitude.
        lon: Its longitude.
        known: Stations already in the database.

    Returns:
        The match decision.
    """
    by_id = {k.source_id: k for k in known}
    if legacy_id in by_id:
        hit = by_id[legacy_id]
        dist = haversine_m(lat, lon, hit.lat, hit.lon)
        warning = None
        if dist > MATCH_RADIUS_M:
            warning = f"exact ID match {dist:.0f} m apart ({name!r} vs {hit.name!r})"
        return Match(legacy_id, hit.station_key, "exact", dist, warning)
    target = normalise_name(name)
    for cand in known:
        dist = haversine_m(lat, lon, cand.lat, cand.lon)
        if normalise_name(cand.name) == target and dist <= MATCH_RADIUS_M:
            return Match(legacy_id, cand.station_key, "name+coords", dist, None)
    return Match(legacy_id, None, "new", None, f"no match for {legacy_id} {name!r}; new station")
