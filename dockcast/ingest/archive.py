"""Nightly archive of live raw rows to Parquet, then retention pruning (PRD 18.4).

Exports carry ``city_code`` and the GBFS ``source_id`` (not only ``station_key``) so they can be
re-imported into a database whose station keys differ, e.g. the local research DB.
Upload to object storage (R2) is done by the deployment script between ``export`` and ``prune``.
"""

import argparse
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
import structlog
from sqlalchemy import Engine, text

from dockcast.config import get_env_settings, load_project_config
from dockcast.db.engine import make_engine

log = structlog.get_logger(job="archive")

EXPORT_SQL = text(
    "SELECT s.city_code, s.source_id, r.station_key, r.observed_at, r.last_reported, "
    "r.bikes_available, r.docks_available, r.is_renting, r.is_returning, r.source "
    "FROM station_status_raw r JOIN stations s USING (station_key) "
    "WHERE r.source = 'live' AND r.observed_at >= :start AND r.observed_at < :end "
    "ORDER BY r.station_key, r.observed_at"
)


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


def days_before(engine: Engine, cutoff: datetime) -> list[date]:
    """UTC dates that still hold live rows older than ``cutoff``.

    Args:
        engine: Database engine.
        cutoff: Exclusive upper bound.

    Returns:
        Dates in ascending order.
    """
    query = text(
        "SELECT DISTINCT (observed_at AT TIME ZONE 'UTC')::date FROM station_status_raw "
        "WHERE source = 'live' AND observed_at < :cutoff ORDER BY 1"
    )
    with engine.connect() as conn:
        return [row[0] for row in conn.execute(query, {"cutoff": cutoff})]


def archive_path(root: Path, day: date) -> Path:
    """Hive-style path: ``<root>/station_status_raw/source=live/date=YYYY-MM-DD/part-0.parquet``.

    Args:
        root: Archive root.
        day: UTC date.

    Returns:
        Parquet file path.
    """
    return root / "station_status_raw" / "source=live" / f"date={day:%Y-%m-%d}" / "part-0.parquet"


def export_day(engine: Engine, day: date, root: Path) -> int:
    """Write one UTC day of live rows to Parquet (overwrites).

    Args:
        engine: Database engine.
        day: UTC date.
        root: Archive root.

    Returns:
        Number of rows written.
    """
    start, end = day_bounds(day)
    with engine.connect() as conn:
        frame = pd.read_sql(EXPORT_SQL, conn, params={"start": start, "end": end})
    path = archive_path(root, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    log.info("exported", day=str(day), rows=len(frame), path=str(path))
    return len(frame)


def prune_day(engine: Engine, day: date, root: Path) -> int:
    """Delete one day of live rows, only if its Parquet file holds the same row count.

    Args:
        engine: Database engine.
        day: UTC date.
        root: Archive root.

    Returns:
        Rows deleted (0 if the archive is missing or incomplete).
    """
    path = archive_path(root, day)
    start, end = day_bounds(day)
    count_sql = text(
        "SELECT count(*) FROM station_status_raw "
        "WHERE source = 'live' AND observed_at >= :start AND observed_at < :end"
    )
    with engine.begin() as conn:
        in_db = int(conn.execute(count_sql, {"start": start, "end": end}).scalar_one())
        archived = len(pd.read_parquet(path, columns=["station_key"])) if path.exists() else -1
        if archived != in_db:
            log.error("prune_refused", day=str(day), in_db=in_db, archived=archived)
            return 0
        deleted = conn.execute(
            text(
                "DELETE FROM station_status_raw "
                "WHERE source = 'live' AND observed_at >= :start AND observed_at < :end"
            ),
            {"start": start, "end": end},
        ).rowcount
    log.info("pruned", day=str(day), rows=deleted)
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
    keep = load_project_config().retention.raw_live_days
    engine = make_engine()
    cutoff = retention_cutoff(datetime.now(UTC), keep)
    for day in days_before(engine, cutoff):
        if args.action == "export":
            export_day(engine, day, root)
        else:
            prune_day(engine, day, root)


if __name__ == "__main__":
    main()
