from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from dockcast.db.models import CollectorRun
from dockcast.quality.health import collector_uptime

pytestmark = pytest.mark.integration


def test_uptime_counts_distinct_successful_slots(db_engine: Engine) -> None:
    start = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    runs = [
        (0, "ok", 115),
        (0, "ok", 0),  # duplicate slot
        (1, "partial", 110),
        (2, "error", None),
        (3, "ok", 0),  # nothing stored
        (4, "ok", 115),
    ]
    with Session(db_engine) as session:
        for minute, status, rows in runs:
            started = start + timedelta(minutes=minute, seconds=1)
            session.add(
                CollectorRun(
                    city_code="dublin", started_at=started, status=status, rows_written=rows
                )
            )
        session.commit()
        stored, scheduled = collector_uptime(
            session, "dublin", start, start + timedelta(minutes=10), 60
        )
    assert (stored, scheduled) == (3, 10)


def test_uptime_never_exceeds_100_percent_for_unaligned_window(db_engine: Engine) -> None:
    start = datetime(2026, 10, 15, 12, 0, 5, tzinfo=UTC)
    end = start + timedelta(minutes=3, seconds=30)
    with Session(db_engine) as session:
        for minute in range(4):
            session.add(
                CollectorRun(
                    city_code="dublin",
                    started_at=start + timedelta(minutes=minute),
                    status="ok",
                    rows_written=115,
                )
            )
        session.commit()
        stored, scheduled = collector_uptime(session, "dublin", start, end, 60)
    assert stored <= scheduled
    assert (stored, scheduled) == (4, 4)
