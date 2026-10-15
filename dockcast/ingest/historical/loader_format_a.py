"""Loader for "DublinBike historical data YYYY-MM" files (Oct 2021 - Feb 2024).

Timestamps are Europe/Dublin local time: the spring-forward hour is absent and the autumn
fall-back hour appears twice (verified on 2022-10-30 and 2023-03-26). Snapshots every 30 min.
"""

from pathlib import Path

import pandas as pd

from dockcast.ingest.historical.formats import CANONICAL_COLUMNS, empty_canonical

LOCAL_TZ = "Europe/Dublin"


def localize_station_times(local: pd.Series, station: pd.Series) -> pd.Series:
    """Convert naive local times to UTC, resolving the repeated autumn hour per station.

    Files are sorted by local time, so the two copies of the repeated hour are interleaved
    (e.g. 01:00:03, 01:00:04, 01:30:02, 01:30:03). Within each (station, 30-min slot) of the
    repeated hour, the first row in file order is taken as IST and the second as GMT. A slot
    holding a single row cannot be resolved and becomes NaT (dropped by the backfill).

    Args:
        local: Naive local timestamps, in file order.
        station: Station ID per row (same index).

    Returns:
        UTC timestamps aligned with ``local``.
    """
    slot = local.dt.floor("30min")
    occurrence = local.groupby([station, slot], sort=False).cumcount()
    slot_size = local.groupby([station, slot], sort=False).transform("size")
    is_dst = (occurrence == 0).to_numpy()
    localized = pd.DatetimeIndex(local).tz_localize(LOCAL_TZ, ambiguous=is_dst, nonexistent="NaT")
    result = pd.Series(localized.tz_convert("UTC"), index=local.index)
    ambiguous = (
        pd.Series(
            pd.DatetimeIndex(local).tz_localize(LOCAL_TZ, ambiguous="NaT", nonexistent="NaT"),
            index=local.index,
        ).isna()
        & local.notna()
    )
    nonexistent_or_unpaired = ambiguous & (slot_size != 2)
    return result.mask(nonexistent_or_unpaired)


def load_format_a(path: Path) -> pd.DataFrame:
    """Read a format-A CSV into canonical columns.

    Args:
        path: CSV path.

    Returns:
        Canonical frame; ``observed_at`` is the poll ``TIME`` in UTC.
    """
    raw = pd.read_csv(path, dtype={"STATION ID": str})
    if raw.empty:
        return empty_canonical()
    station = raw["STATION ID"].str.strip()
    observed_local = pd.to_datetime(raw["TIME"]).dt.floor("s")
    is_open = raw["STATUS"].str.upper().eq("OPEN")
    df = pd.DataFrame(
        {
            "source_id": station,
            "name": raw["NAME"],
            "lat": raw["LATITUDE"].astype(float),
            "lon": raw["LONGITUDE"].astype(float),
            "capacity": raw["BIKE_STANDS"].astype(int),
            "observed_at": localize_station_times(observed_local, station),
            "last_reported": pd.to_datetime(raw["LAST UPDATED"])
            .dt.tz_localize(LOCAL_TZ, ambiguous="NaT", nonexistent="NaT")
            .dt.tz_convert("UTC"),
            "bikes_available": raw["AVAILABLE_BIKES"].astype(int),
            "docks_available": raw["AVAILABLE_BIKE_STANDS"].astype(int),
            "is_renting": is_open,
            "is_returning": is_open,
            "source": "hist_a",
        }
    )
    return df[CANONICAL_COLUMNS]
