"""Write helpers shared by ingestion jobs."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from dockcast.config import CityConfig
from dockcast.db.models import City, Station, StationCapacity, StationStatusRaw


@dataclass(frozen=True)
class StationRecord:
    """Attributes needed to create or refresh a ``stations`` row."""

    source_id: str
    name: str
    lat: float
    lon: float
    capacity: int


def ensure_city(session: Session, city: CityConfig) -> None:
    """Insert or update the ``cities`` row from config.

    Args:
        session: Open session (caller commits).
        city: City configuration.
    """
    values = {
        "city_code": city.city_code,
        "name": city.name,
        "timezone": city.timezone,
        "gbfs_root_url": city.gbfs_root_url or None,
        "centre_lat": city.centre_lat,
        "centre_lon": city.centre_lon,
        "default_zoom": city.default_zoom,
    }
    stmt = insert(City).values(values)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[City.city_code],
            set_={k: stmt.excluded[k] for k in values if k != "city_code"},
        )
    )


def upsert_stations(
    session: Session, city_code: str, stations: Iterable[StationRecord], seen_at: datetime
) -> dict[str, int]:
    """Insert new stations and refresh attributes and ``last_seen`` of known ones.

    Args:
        session: Open session (caller commits).
        city_code: City the stations belong to.
        stations: Current station attributes.
        seen_at: Timestamp to record as first/last seen.

    Returns:
        ``{source_id: station_key}`` for the given stations.
    """
    rows = [
        {
            "city_code": city_code,
            "source_id": s.source_id,
            "name": s.name,
            "lat": s.lat,
            "lon": s.lon,
            "capacity": s.capacity,
            "first_seen": seen_at,
            "last_seen": seen_at,
            "is_active": True,
        }
        for s in stations
    ]
    if not rows:
        return {}
    base = insert(Station).values(rows)
    stmt = base.on_conflict_do_update(
        index_elements=[Station.city_code, Station.source_id],
        set_={
            "name": base.excluded.name,
            "lat": base.excluded.lat,
            "lon": base.excluded.lon,
            "capacity": base.excluded.capacity,
            "last_seen": base.excluded.last_seen,
            "is_active": True,
        },
    ).returning(Station.source_id, Station.station_key)
    return {source_id: key for source_id, key in session.execute(stmt).all()}


def station_keys(session: Session, city_code: str) -> dict[str, int]:
    """Return ``{source_id: station_key}`` for all stations of a city.

    Args:
        session: Open session.
        city_code: City code.

    Returns:
        Mapping of GBFS station IDs to internal keys.
    """
    stmt = select(Station.source_id, Station.station_key).where(Station.city_code == city_code)
    return {source_id: key for source_id, key in session.execute(stmt).all()}


def insert_status_rows(session: Session, rows: Sequence[dict[str, Any]]) -> int:
    """Insert raw status rows, ignoring duplicates on ``(station_key, observed_at)``.

    Args:
        session: Open session (caller commits).
        rows: Dicts with ``station_status_raw`` columns.

    Returns:
        Number of rows actually inserted.
    """
    if not rows:
        return 0
    stmt = (
        insert(StationStatusRaw)
        .values(list(rows))
        .on_conflict_do_nothing(index_elements=["station_key", "observed_at"])
        .returning(StationStatusRaw.station_key)
    )
    return len(session.execute(stmt).all())


def record_capacity(
    session: Session, station_key: int, valid_from: datetime, capacity: int, source: str
) -> bool:
    """Insert a change point if it differs from the capacity in force at ``valid_from``.

    Args:
        session: Open session (caller commits).
        station_key: Station.
        valid_from: When the capacity was observed.
        capacity: Observed capacity.
        source: ``live`` / ``hist_a`` / ``hist_b``.

    Returns:
        True if a row was inserted.
    """
    current = session.scalar(
        select(StationCapacity.capacity)
        .where(StationCapacity.station_key == station_key, StationCapacity.valid_from <= valid_from)
        .order_by(StationCapacity.valid_from.desc())
        .limit(1)
    )
    if current == capacity:
        return False
    session.execute(
        insert(StationCapacity)
        .values(station_key=station_key, valid_from=valid_from, capacity=capacity, source=source)
        .on_conflict_do_update(
            index_elements=["station_key", "valid_from"],
            set_={"capacity": capacity, "source": source},
        )
    )
    return True
