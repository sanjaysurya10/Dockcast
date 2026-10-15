"""Backfill historical CSVs into ``station_status_raw`` and profile them (PRD 9.2)."""

import io
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd
import structlog
from sqlalchemy import Engine, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from dockcast.config import (
    PROJECT_ROOT,
    CityConfig,
    get_env_settings,
    load_city_config,
    load_project_config,
)
from dockcast.db.engine import make_engine
from dockcast.db.models import DataQualityFile, Station, StationIdMap
from dockcast.ingest.collector import sync_station_information
from dockcast.ingest.historical.download import FORMAT_A_FILE, FORMAT_B_FILE, list_resources
from dockcast.ingest.historical.formats import detect_format, read_header
from dockcast.ingest.historical.loader_format_a import load_format_a
from dockcast.ingest.historical.loader_format_b import load_format_b
from dockcast.ingest.historical.reconcile import KnownStation, legacy_stations, reconcile
from dockcast.quality.profile import FileProfile, profile_frame, render_report, write_report

log = structlog.get_logger(job="backfill")

LOADERS: dict[str, Callable[[Path], pd.DataFrame]] = {
    "hist_a": load_format_a,
    "hist_b": load_format_b,
}
RAW_COLUMNS = [
    "station_key",
    "observed_at",
    "last_reported",
    "bikes_available",
    "docks_available",
    "is_renting",
    "is_returning",
    "source",
]


def clean_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Apply the load-time cleaning rules of PRD 9.3.

    Drops rows with unparseable times and negative counts, and keeps the first of duplicate
    ``(source_id, observed_at)`` rows.

    Args:
        df: Canonical frame.

    Returns:
        Cleaned frame and counts of rows dropped per rule.
    """
    bad_time = df["observed_at"].isna()
    negative = (df["bikes_available"] < 0) | (df["docks_available"] < 0)
    kept = df[~bad_time & ~negative]
    duplicate = kept.duplicated(["source_id", "observed_at"], keep="first")
    counts = {
        "rows_dropped_bad_time": int(bad_time.sum()),
        "rows_dropped_negative": int((negative & ~bad_time).sum()),
        "rows_duplicate": int(duplicate.sum()),
    }
    return kept[~duplicate], counts


def load_file(path: Path) -> tuple[pd.DataFrame, FileProfile]:
    """Detect, load, clean and profile one file.

    Args:
        path: CSV path.

    Returns:
        Cleaned canonical frame and its profile.

    Raises:
        UnknownFormatError: For an unrecognised header.
    """
    header = read_header(path)
    if header is None:
        fmt = "hist_b" if FORMAT_B_FILE.match(path.name) else "hist_a"
        return pd.DataFrame(), FileProfile(path.name, fmt, 0, None, None, 0, None, None, True)
    fmt = detect_format(header)
    df, counts = clean_frame(LOADERS[fmt](path))
    profile = profile_frame(path.name, fmt, df)
    for key, value in counts.items():
        setattr(profile, key, value)
    return df, profile


def map_station_keys(
    session: Session, city_code: str, df: pd.DataFrame, notes: list[str]
) -> dict[str, int]:
    """Resolve every legacy ID in ``df`` to a station key, creating ``station_id_map`` rows.

    Args:
        session: Open session (caller commits).
        city_code: City code.
        df: Canonical rows.
        notes: Reconciliation messages are appended here.

    Returns:
        ``{legacy_id: station_key}``.
    """
    mapped = {
        legacy: key
        for legacy, key in session.execute(
            select(StationIdMap.legacy_id, StationIdMap.station_key).where(
                StationIdMap.city_code == city_code
            )
        ).all()
    }
    legacy = legacy_stations(df)
    known = [
        KnownStation(s.station_key, s.source_id, s.name, s.lat, s.lon)
        for s in session.scalars(select(Station).where(Station.city_code == city_code))
    ]
    unmapped = legacy[~legacy["source_id"].isin(mapped)]
    capacity = df.groupby("source_id")["capacity"].last()
    for record in unmapped.to_dict("records"):
        legacy_id, name = str(record["source_id"]), str(record["name"])
        lat, lon = float(record["lat"]), float(record["lon"])
        match = reconcile(legacy_id, name, lat, lon, known)
        key = match.station_key
        if key is None:
            key = session.execute(
                insert(Station)
                .values(
                    city_code=city_code,
                    source_id=match.legacy_id,
                    name=name,
                    lat=lat,
                    lon=lon,
                    capacity=int(capacity[legacy_id]),
                    first_seen=record["first_seen"],
                    last_seen=record["last_seen"],
                    is_active=False,
                )
                .returning(Station.station_key)
            ).scalar_one()
            known.append(KnownStation(key, legacy_id, name, lat, lon))
        session.add(
            StationIdMap(
                city_code=city_code, legacy_id=match.legacy_id, station_key=key, method=match.method
            )
        )
        mapped[match.legacy_id] = key
        if match.warning:
            notes.append(match.warning)
            log.warning("reconcile", legacy_id=match.legacy_id, warning=match.warning)
    session.execute(
        text(
            "UPDATE stations s SET first_seen = LEAST(s.first_seen, v.first_seen) "
            "FROM (SELECT unnest(CAST(:keys AS bigint[])) AS k, "
            "unnest(CAST(:firsts AS timestamptz[])) AS first_seen) v WHERE s.station_key = v.k"
        ),
        {
            "keys": [mapped[str(s)] for s in legacy["source_id"]],
            "firsts": [ts.to_pydatetime() for ts in legacy["first_seen"]],
        },
    )
    session.flush()
    return mapped


def copy_raw_rows(engine: Engine, df: pd.DataFrame) -> int:
    """Bulk-load rows via ``COPY`` into a temp table, then insert ignoring duplicates.

    Args:
        engine: Database engine.
        df: Frame with ``RAW_COLUMNS``.

    Returns:
        Rows inserted.
    """
    buffer = io.StringIO()
    df[RAW_COLUMNS].to_csv(buffer, index=False, header=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    buffer.seek(0)
    cols = ", ".join(RAW_COLUMNS)
    with engine.begin() as conn:
        raw = conn.connection.driver_connection
        assert raw is not None
        with raw.cursor() as cur:
            cur.execute(
                "CREATE TEMP TABLE tmp_raw (LIKE station_status_raw INCLUDING DEFAULTS) "
                "ON COMMIT DROP"
            )
            with cur.copy(f"COPY tmp_raw ({cols}) FROM STDIN WITH (FORMAT csv)") as copy:
                while chunk := buffer.read(1 << 20):
                    copy.write(chunk)
            cur.execute(
                f"INSERT INTO station_status_raw ({cols}) SELECT {cols} FROM tmp_raw "
                "ON CONFLICT (station_key, observed_at) DO NOTHING"
            )
            return int(cur.rowcount)


def backfill(
    hist_dir: Path,
    engine: Engine,
    city: CityConfig,
    client: httpx.Client,
    report_path: Path = PROJECT_ROOT / "reports" / "data_profile.md",
) -> list[FileProfile]:
    """Load every in-scope CSV in ``hist_dir`` and write the profile report.

    Args:
        hist_dir: Directory of downloaded CSVs.
        engine: Database engine.
        city: City configuration.
        client: HTTP client used to seed stations from the live feed.
        report_path: Where to write the markdown report.

    Returns:
        Profiles of all files.
    """
    now = datetime.now(UTC)
    backoff = load_project_config().collector.retry_backoff_s
    with Session(engine) as session:
        sync_station_information(session, client, city, backoff, now)
        session.commit()
    files = sorted(
        p
        for p in hist_dir.glob("*.csv")
        if FORMAT_A_FILE.match(p.name) or FORMAT_B_FILE.match(p.name)
    )
    profiles: list[FileProfile] = []
    notes: list[str] = []
    for path in files:
        df, profile = load_file(path)
        profiles.append(profile)
        with Session(engine) as session:
            if not df.empty:
                keys = map_station_keys(session, city.city_code, df, notes)
                session.commit()
                df = df.assign(station_key=df["source_id"].map(keys).astype("int64"))
                inserted = copy_raw_rows(engine, df)
                log.info("loaded", file=path.name, rows=len(df), inserted=inserted)
            row = profile.db_row(now)
            stmt = insert(DataQualityFile).values(row)
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[DataQualityFile.file_name],
                    set_={k: stmt.excluded[k] for k in row if k != "file_name"},
                )
            )
            session.commit()
    out_of_scope = [r.name for r in list_resources(city.ckan_package_url, client) if not r.in_scope]
    with Session(engine) as session:
        methods = session.execute(
            text("SELECT method, count(*) FROM station_id_map GROUP BY method ORDER BY method")
        ).all()
    summary = [f"{method}: {count} legacy IDs" for method, count in methods] + notes
    write_report(render_report(profiles, out_of_scope, summary, now), report_path)
    return profiles


def main() -> None:
    """Entry point for ``make backfill`` (download first, then load)."""
    from dockcast.ingest.historical.download import download_all

    settings = get_env_settings()
    download_all()
    with httpx.Client(headers={"User-Agent": settings.user_agent}, timeout=60) as client:
        backfill(
            settings.data_dir / "raw" / "hist",
            make_engine(),
            load_city_config(settings.city),
            client,
        )


if __name__ == "__main__":
    main()
