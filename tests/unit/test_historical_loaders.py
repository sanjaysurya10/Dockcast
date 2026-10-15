from pathlib import Path

import pandas as pd
import pytest

from dockcast.ingest.historical.backfill import clean_frame, load_file
from dockcast.ingest.historical.formats import (
    CANONICAL_COLUMNS,
    UnknownFormatError,
    detect_format,
    read_header,
)
from dockcast.ingest.historical.loader_format_a import load_format_a
from dockcast.ingest.historical.loader_format_b import load_format_b

pytestmark = pytest.mark.unit
HIST = Path(__file__).parent.parent / "fixtures" / "hist"


def test_detect_format() -> None:
    a = read_header(HIST / "dublinbike-historical-data-2022-10.csv")
    b = read_header(HIST / "dublin-bikes_station_status_102025.csv")
    assert a is not None and detect_format(a) == "hist_a"
    assert b is not None and detect_format(b) == "hist_b"


def test_unknown_header_is_rejected_loudly() -> None:
    with pytest.raises(UnknownFormatError):
        load_file(HIST / "unknown_header.csv")


def test_header_only_file_is_profiled_as_empty() -> None:
    df, profile = load_file(HIST / "dublin-bikes_station_status_011999.csv")
    assert df.empty
    assert profile.is_empty and profile.rows == 0 and profile.format == "hist_b"


def test_format_a_autumn_dst_hour_resolves_to_distinct_utc_times() -> None:
    df = load_format_a(HIST / "dublinbike-historical-data-2022-10.csv")
    assert list(df.columns) == CANONICAL_COLUMNS
    station = df[df["source_id"] == "2"]["observed_at"].sort_values()
    # 00:00-02:30 local on 2022-10-30 = 23:00 UTC (IST) to 02:30 UTC (GMT): 8 polls, 30 min apart
    assert station.notna().all()
    assert station.is_unique
    gaps = station.diff().dropna().dt.total_seconds().round(-1)
    assert set(gaps) == {1800}
    assert station.iloc[0] == pd.Timestamp("2022-10-29 23:00:04", tz="UTC")
    assert station.iloc[-1] == pd.Timestamp("2022-10-30 02:30:02", tz="UTC")


def test_format_a_spring_dst_gap_is_continuous_in_utc() -> None:
    df = load_format_a(HIST / "dublinbike-historical-data-2023-03.csv")
    station = df[df["source_id"] == "2"]["observed_at"].sort_values()
    gaps = station.diff().dropna().dt.total_seconds().round(-1)
    assert set(gaps) == {1800}
    # 00:30 GMT is followed by 02:00 IST = 01:00 UTC
    assert pd.Timestamp("2023-03-26 01:00", tz="UTC") <= station.iloc[2]


def test_format_a_status_maps_to_renting_flags() -> None:
    df = load_format_a(HIST / "dublinbike-historical-data-2022-10.csv")
    assert df["is_renting"].all() and df["is_returning"].all()
    assert (df["source"] == "hist_a").all()


def test_format_b_is_utc_with_null_last_reported() -> None:
    df = load_format_b(HIST / "dublin-bikes_station_status_102025.csv")
    assert list(df.columns) == CANONICAL_COLUMNS
    assert str(df["observed_at"].dt.tz) == "UTC"
    assert df["observed_at"].iloc[0] == pd.Timestamp("2025-10-26 00:05", tz="UTC")
    assert df["last_reported"].isna().all()
    assert df["is_renting"].dtype == bool or set(df["is_renting"]) <= {True, False}
    assert (df["source_id"] == "1").all()


def test_clean_frame_drops_negatives_bad_times_and_duplicates() -> None:
    df = load_format_b(HIST / "dublin-bikes_station_status_102025.csv")
    dirty = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    dirty.loc[1, "bikes_available"] = -1
    dirty.loc[2, "observed_at"] = pd.NaT
    cleaned, counts = clean_frame(dirty)
    assert counts == {
        "rows_dropped_bad_time": 1,
        "rows_dropped_negative": 1,
        "rows_duplicate": 1,
    }
    assert len(cleaned) == len(df) - 2
