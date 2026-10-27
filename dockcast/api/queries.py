"""SQL behind the API. Every list query is bounded by station count or ``limit``."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, text

LATEST_STATUS = text(
    """
    SELECT DISTINCT ON (station_key)
           station_key, observed_at, bikes_available, docks_available, is_renting
    FROM station_status_raw
    WHERE observed_at > now() - INTERVAL '1 day'
      AND (CAST(:station_key AS bigint) IS NULL OR station_key = :station_key)
    ORDER BY station_key, observed_at DESC
    """
)

STATIONS = text(
    """
    SELECT station_key, name, lat, lon, capacity, is_active
    FROM stations
    WHERE (CAST(:city AS text) IS NULL OR city_code = :city)
      AND (CAST(:station_key AS bigint) IS NULL OR station_key = :station_key)
    ORDER BY station_key
    """
)

LATEST_FORECAST = text(
    """
    SELECT issued_at, horizon_min, target_ts, bikes_p10, bikes_p50, bikes_p90, model_version
    FROM forecasts
    WHERE station_key = :station_key
      AND issued_at = (SELECT max(issued_at) FROM forecasts WHERE station_key = :station_key)
    ORDER BY horizon_min
    """
)


def _utc(value: datetime | None) -> datetime | None:
    return None if value is None else value.astimezone(UTC)


def stations(
    conn: Connection, city: str | None = None, station_key: int | None = None
) -> list[dict[str, Any]]:
    """Stations with their latest status (``now`` is None after a day without data)."""
    rows = conn.execute(STATIONS, {"city": city, "station_key": station_key}).mappings().all()
    status = {
        r["station_key"]: {
            "bikes": r["bikes_available"],
            "docks": r["docks_available"],
            "observed_at": _utc(r["observed_at"]),
            "is_renting": r["is_renting"],
        }
        for r in conn.execute(LATEST_STATUS, {"station_key": station_key}).mappings()
    }
    return [{**r, "now": status.get(r["station_key"]), "risk": None} for r in rows]


def latest_forecast(conn: Connection, station_key: int) -> list[dict[str, Any]]:
    """Rows of the newest forecast cycle for one station."""
    rows = conn.execute(LATEST_FORECAST, {"station_key": station_key}).mappings().all()
    return [
        {**r, "issued_at": _utc(r["issued_at"]), "target_ts": _utc(r["target_ts"])} for r in rows
    ]


def health(conn: Connection) -> tuple[datetime | None, datetime | None]:
    """Newest collector run start and newest forecast issue time."""
    run = conn.execute(text("SELECT max(started_at) FROM collector_runs")).scalar()
    issued = conn.execute(text("SELECT max(issued_at) FROM forecasts")).scalar()
    return _utc(run), _utc(issued)


def cities(conn: Connection) -> list[dict[str, Any]]:
    """Every city."""
    sql = text(
        "SELECT city_code, name, timezone, centre_lat, centre_lon, default_zoom "
        "FROM cities ORDER BY city_code"
    )
    return [dict(r) for r in conn.execute(sql).mappings()]


def champions(conn: Connection) -> list[dict[str, Any]]:
    """Champion model versions, by horizon."""
    sql = text(
        "SELECT model_version, horizon_min, trained_at, train_end, metrics FROM model_versions "
        "WHERE is_champion ORDER BY horizon_min NULLS LAST, model_version"
    )
    return [
        {**r, "trained_at": _utc(r["trained_at"]), "train_end": _utc(r["train_end"])}
        for r in conn.execute(sql).mappings()
    ]
