"""Historical CSV format detection and the canonical column set shared by loaders A and B."""

import csv
from pathlib import Path

import pandas as pd

# Verified against every downloaded file on 2026-10-15 (see reports/data_profile.md).
FORMAT_A_COLUMNS = (
    "STATION ID", "TIME", "LAST UPDATED", "NAME", "BIKE_STANDS", "AVAILABLE_BIKE_STANDS",
    "AVAILABLE_BIKES", "STATUS", "ADDRESS", "LATITUDE", "LONGITUDE",
)  # fmt: skip
FORMAT_B_COLUMNS = (
    "system_id", "last_reported", "station_id", "num_bikes_available", "num_docks_available",
    "is_installed", "is_renting", "is_returning", "name", "short_name", "address", "lat", "lon",
    "region_id", "capacity",
)  # fmt: skip

CANONICAL_COLUMNS = [
    "source_id",
    "name",
    "lat",
    "lon",
    "capacity",
    "observed_at",
    "last_reported",
    "bikes_available",
    "docks_available",
    "is_renting",
    "is_returning",
    "source",
]


class UnknownFormatError(ValueError):
    """Raised when a CSV header matches neither known format."""


def read_header(path: Path) -> tuple[str, ...] | None:
    """Return the CSV header, or ``None`` for a zero-byte file.

    Args:
        path: CSV path.

    Returns:
        Column names, or ``None`` if the file is empty.
    """
    with path.open(newline="", encoding="utf-8-sig") as fh:
        row = next(csv.reader(fh), None)
    return tuple(col.strip() for col in row) if row else None


def detect_format(header: tuple[str, ...]) -> str:
    """Identify the format from an exact header match.

    Args:
        header: Column names.

    Returns:
        ``"hist_a"`` or ``"hist_b"``.

    Raises:
        UnknownFormatError: If the header is not recognised.
    """
    if header == FORMAT_A_COLUMNS:
        return "hist_a"
    if header == FORMAT_B_COLUMNS:
        return "hist_b"
    raise UnknownFormatError(f"unrecognised header: {header}")


def empty_canonical() -> pd.DataFrame:
    """An empty frame with the canonical columns."""
    return pd.DataFrame({col: pd.Series(dtype="object") for col in CANONICAL_COLUMNS})
