"""Loader for "Dublin Bikes Historical Station Data MMYYYY" files (May 2024 onward).

The ``last_reported`` column holds the snapshot time on a 5-minute grid, in UTC (no DST gap or
repeated hour on 2025-03-30 / 2025-10-26). Each station appears roughly every 10 minutes.
The publisher's ``last_reported`` is therefore stored as ``observed_at``; ``last_reported`` is
left null because the file carries no separate station report time.
"""

from pathlib import Path

import pandas as pd

from dockcast.ingest.historical.formats import CANONICAL_COLUMNS, empty_canonical


def _to_bool(col: pd.Series) -> pd.Series:
    return col.astype(str).str.strip().str.lower().map({"true": True, "false": False})


def load_format_b(path: Path) -> pd.DataFrame:
    """Read a format-B CSV into canonical columns.

    Args:
        path: CSV path.

    Returns:
        Canonical frame with UTC ``observed_at``.
    """
    raw = pd.read_csv(path, dtype={"station_id": str})
    if raw.empty:
        return empty_canonical()
    df = pd.DataFrame(
        {
            "source_id": raw["station_id"].str.strip(),
            "name": raw["name"],
            "lat": raw["lat"].astype(float),
            "lon": raw["lon"].astype(float),
            "capacity": raw["capacity"].astype(int),
            "observed_at": pd.to_datetime(raw["last_reported"]).dt.tz_localize("UTC"),
            "last_reported": pd.Series(pd.NaT, index=raw.index, dtype="datetime64[ns, UTC]"),
            "bikes_available": raw["num_bikes_available"].astype(int),
            "docks_available": raw["num_docks_available"].astype(int),
            "is_renting": _to_bool(raw["is_renting"]),
            "is_returning": _to_bool(raw["is_returning"]),
            "source": "hist_b",
        }
    )
    return df[CANONICAL_COLUMNS]
