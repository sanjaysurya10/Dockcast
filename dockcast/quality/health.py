"""Collector health: uptime as the share of scheduled polls stored (PRD S5)."""

import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dockcast.config import get_env_settings, load_project_config
from dockcast.db.engine import make_engine
from dockcast.db.models import CollectorRun


def collector_uptime(
    session: Session, city_code: str, start: datetime, end: datetime, interval_s: int
) -> tuple[int, int]:
    """Count scheduled poll slots in ``[start, end)`` that have a stored (ok/partial) run.

    Args:
        session: Open session.
        city_code: City code.
        start: Window start (UTC).
        end: Window end (UTC).
        interval_s: Poll interval in seconds.

    Returns:
        ``(slots_with_stored_poll, scheduled_slots)``.
    """
    slot = func.floor(func.extract("epoch", CollectorRun.started_at) / interval_s)
    stored = session.scalar(
        select(func.count(func.distinct(slot))).where(
            CollectorRun.city_code == city_code,
            CollectorRun.started_at >= start,
            CollectorRun.started_at < end,
            CollectorRun.status.in_(("ok", "partial")),
            CollectorRun.rows_written > 0,
        )
    )
    first_slot = math.floor(start.timestamp() / interval_s)
    last_slot = math.ceil(end.timestamp() / interval_s)
    return int(stored or 0), last_slot - first_slot


def main() -> None:
    """Print collector uptime for the last 24 hours."""
    settings = get_env_settings()
    interval = load_project_config().collector.poll_interval_s
    end = datetime.now(UTC)
    start = end - timedelta(hours=24)
    with Session(make_engine()) as session:
        first = session.scalar(
            select(func.min(CollectorRun.started_at)).where(CollectorRun.city_code == settings.city)
        )
        if first is not None and first > start:
            start = first
        stored, scheduled = collector_uptime(session, settings.city, start, end, interval)
    pct = 100 * stored / scheduled if scheduled else 0.0
    print(f"{start:%Y-%m-%d %H:%M} -> {end:%Y-%m-%d %H:%M} UTC: {stored}/{scheduled} = {pct:.2f}%")


if __name__ == "__main__":
    main()
