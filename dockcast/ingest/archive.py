"""Nightly archive of hosted rows to Parquet, then retention pruning (PRD 18.4).

Two tables are archived: live raw rows (by ``observed_at``) and forecasts (by ``issued_at``,
owner decision 2026-11-01: 14 days hosted). Exports carry ``city_code`` and the GBFS
``source_id`` (not only ``station_key``) so they can be re-imported into a database whose
station keys differ, e.g. the local research DB. Upload to object storage (R2) is done by the
deployment script between ``export`` and ``prune``.
"""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
import structlog
from sqlalchemy import Engine, text

from dockcast.config import city_codes, get_env_settings, load_city_config, load_project_config
from dockcast.db.engine import make_engine

log = structlog.get_logger(job="archive")


@dataclass(frozen=True)
class ArchiveTable:
    """One archived table: its day column, row filter, export columns and Parquet folder."""

    table: str
    ts_column: str
    where: str
    columns: str
    folder: str


RAW = ArchiveTable(
    table="station_status_raw",
    ts_column="observed_at",
    where="t.source = 'live'",
    columns="t.station_key, t.observed_at, t.last_reported, t.bikes_available, "
    "t.docks_available, t.is_renting, t.is_returning, t.source",
    folder="station_status_raw/source=live",
)

FORECASTS = ArchiveTable(
    table="forecasts",
    ts_column="issued_at",
    where="true",
    columns="t.station_key, t.issued_at, t.horizon_min, t.target_ts, t.bikes_p10, "
    "t.bikes_p50, t.bikes_p90, t.model_version",
    folder="forecasts",
)


CITY_FILTER = (
    " AND (CAST(:city AS text) IS NULL OR t.station_key IN "
    "(SELECT station_key FROM stations WHERE city_code = :city))"
)


def _day_filter(spec: ArchiveTable) -> str:
    day = f"t.{spec.ts_column} >= :start AND t.{spec.ts_column} < :end"
    return f"{spec.where} AND {day}{CITY_FILTER}"


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """UTC start and end of a calendar day.

    Args:
        day: UTC date.

    Returns:
        ``(start, end)``.
    """
    start = datetime.combine(day, time(0), tzinfo=UTC)
    return start, start + timedelta(days=1)


def retention_cutoff(now: datetime, keep_days: int) -> datetime:
    """Midnight UTC before which live rows leave the hosted database.

    Args:
        now: Current time (UTC).
        keep_days: Whole days to keep.

    Returns:
        The cutoff (start of a UTC day).
    """
    today = datetime.combine(now.astimezone(UTC).date(), time(0), tzinfo=UTC)
    return today - timedelta(days=keep_days)


def days_before(
    engine: Engine, cutoff: datetime, spec: ArchiveTable = RAW, city: str | None = None
) -> list[date]:
    """UTC dates that still hold rows of ``spec`` older than ``cutoff``.

    Args:
        engine: Database engine.
        cutoff: Exclusive upper bound.
        spec: Table to look at.
        city: Only this city's stations (None: all).

    Returns:
        Dates in ascending order.
    """
    query = text(
        f"SELECT DISTINCT (t.{spec.ts_column} AT TIME ZONE 'UTC')::date FROM {spec.table} t "
        f"WHERE {spec.where} AND t.{spec.ts_column} < :cutoff{CITY_FILTER} ORDER BY 1"
    )
    with engine.connect() as conn:
        return [row[0] for row in conn.execute(query, {"cutoff": cutoff, "city": city})]


def archive_path(root: Path, day: date, spec: ArchiveTable = RAW, city: str | None = None) -> Path:
    """Hive-style path: ``<root>/<folder>[/city=<code>]/date=YYYY-MM-DD/part-0.parquet``.

    Args:
        root: Archive root.
        day: UTC date.
        spec: Archived table.
        city: City partition (None: all cities in one file).

    Returns:
        Parquet file path.
    """
    folder = root / spec.folder if city is None else root / spec.folder / f"city={city}"
    return folder / f"date={day:%Y-%m-%d}" / "part-0.parquet"


def export_day(
    engine: Engine, day: date, root: Path, spec: ArchiveTable = RAW, city: str | None = None
) -> int:
    """Write one UTC day of ``spec`` rows to Parquet (overwrites).

    Args:
        engine: Database engine.
        day: UTC date.
        root: Archive root.
        spec: Table to export.
        city: Only this city's stations (None: all).

    Returns:
        Number of rows written.
    """
    start, end = day_bounds(day)
    query = text(
        f"SELECT s.city_code, s.source_id, {spec.columns} "
        f"FROM {spec.table} t JOIN stations s USING (station_key) "
        f"WHERE {_day_filter(spec)} ORDER BY t.station_key, t.{spec.ts_column}"
    )
    with engine.connect() as conn:
        result = conn.execute(query, {"start": start, "end": end, "city": city})
        frame = pd.DataFrame(result.fetchall(), columns=list(result.keys()))
    path = archive_path(root, day, spec, city)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    log.info("exported", table=spec.table, city=city, day=str(day), rows=len(frame),
             path=str(path))  # fmt: skip
    return len(frame)


def prune_day(
    engine: Engine, day: date, root: Path, spec: ArchiveTable = RAW, city: str | None = None
) -> int:
    """Delete one day of ``spec`` rows, only if its Parquet file holds the same row count.

    Args:
        engine: Database engine.
        day: UTC date.
        root: Archive root.
        spec: Table to prune.
        city: Only this city's stations (None: all).

    Returns:
        Rows deleted (0 if the archive is missing or incomplete).
    """
    path = archive_path(root, day, spec, city)
    params: dict[str, object] = dict(zip(("start", "end"), day_bounds(day), strict=True))
    params["city"] = city
    with engine.begin() as conn:
        count_sql = text(f"SELECT count(*) FROM {spec.table} t WHERE {_day_filter(spec)}")
        in_db = int(conn.execute(count_sql, params).scalar_one())
        archived = len(pd.read_parquet(path, columns=["station_key"])) if path.exists() else -1
        if archived != in_db:
            log.error("prune_refused", table=spec.table, city=city, day=str(day), in_db=in_db,
                      archived=archived)  # fmt: skip
            return 0
        delete_sql = text(f"DELETE FROM {spec.table} t WHERE {_day_filter(spec)}")
        deleted = conn.execute(delete_sql, params).rowcount
    log.info("pruned", table=spec.table, city=city, day=str(day), rows=deleted)
    return int(deleted)


def main(argv: Sequence[str] | None = None) -> None:
    """``python -m dockcast.ingest.archive {export,prune}``."""
    parser = argparse.ArgumentParser(description="Archive and prune live raw rows (PRD 18.4).")
    parser.add_argument("action", choices=["export", "prune"])
    parser.add_argument("--root", type=Path, default=None, help="archive root directory")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="required for prune; only run prune against the hosted database",
    )
    args = parser.parse_args(argv)
    if args.action == "prune" and not args.confirm:
        parser.error("prune deletes rows; pass --confirm (hosted database only)")
    settings = get_env_settings()
    root = args.root or settings.data_dir / "archive"
    retention = load_project_config().retention
    engine = make_engine()
    now = datetime.now(UTC)
    # Raw rows per city (each city may keep fewer days, M20); forecasts in one file per day.
    jobs: list[tuple[ArchiveTable, int, str | None]] = []
    for code in city_codes():
        keep = load_city_config(code).raw_live_days
        jobs.append((RAW, retention.raw_live_days if keep is None else keep, code))
    jobs.append((FORECASTS, retention.forecasts_days, None))
    for spec, keep, city in jobs:
        for day in days_before(engine, retention_cutoff(now, keep), spec, city):
            if args.action == "export":
                export_day(engine, day, root, spec, city)
            else:
                prune_day(engine, day, root, spec, city)


if __name__ == "__main__":
    main()
