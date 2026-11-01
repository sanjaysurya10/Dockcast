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


CITY_FORECAST = text(
    """
    SELECT f.station_key, f.issued_at, f.horizon_min, f.bikes_p10, f.bikes_p50, f.bikes_p90,
           f.model_version
    FROM forecasts f
    JOIN stations s USING (station_key)
    WHERE s.city_code = :city
      AND f.issued_at = (
          SELECT max(f2.issued_at) FROM forecasts f2
          JOIN stations s2 USING (station_key)
          WHERE s2.city_code = :city
      )
    ORDER BY f.station_key, f.horizon_min
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


def city_forecast(conn: Connection, city: str) -> list[dict[str, Any]]:
    """Rows of the newest forecast cycle for every station of a city."""
    rows = conn.execute(CITY_FORECAST, {"city": city}).mappings().all()
    return [{**r, "issued_at": _utc(r["issued_at"])} for r in rows]


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


HISTORY = text(
    """
    SELECT ts, bikes_last, docks_last, is_imputed
    FROM station_status_15m
    WHERE station_key = :station_key
      AND ts > (SELECT max(ts) FROM station_status_15m WHERE station_key = :station_key)
               - make_interval(hours => :hours)
    ORDER BY ts
    """
)


def history(conn: Connection, station_key: int, hours: int) -> list[dict[str, Any]]:
    """The station's last ``hours`` of 15-min states, ending at its newest bucket."""
    rows = conn.execute(HISTORY, {"station_key": station_key, "hours": hours}).mappings().all()
    return [
        {
            "ts": _utc(r["ts"]),
            "bikes": r["bikes_last"],
            "docks": r["docks_last"],
            "is_imputed": r["is_imputed"],
        }
        for r in rows
    ]


DRIVERS = text(
    """
    SELECT issued_at, feature_group, contribution
    FROM forecast_drivers
    WHERE station_key = :station_key AND horizon_min = :horizon
      AND issued_at = (SELECT max(issued_at) FROM forecast_drivers WHERE station_key = :station_key)
    """
)


def drivers(conn: Connection, station_key: int, horizon: int) -> list[dict[str, Any]]:
    """Feature-group drivers of the station's newest explained forecast."""
    rows = conn.execute(DRIVERS, {"station_key": station_key, "horizon": horizon}).mappings()
    return [{**r, "issued_at": _utc(r["issued_at"])} for r in rows]


DEFAULT_RUN = text(
    """
    SELECT run_id FROM backtest_results
    WHERE experiment = :experiment AND slice_kind = 'overall'
    GROUP BY run_id
    ORDER BY count(DISTINCT fold) DESC, max(created_at) DESC
    LIMIT 1
    """
)

BACKTEST = text(
    """
    SELECT model_name, horizon_min, slice_value,
           count(DISTINCT fold) AS folds, sum(n) AS n,
           avg(mae) AS mae, avg(rmse) AS rmse, avg(mase) AS mase,
           avg(coverage_80) AS coverage_80, avg(interval_width) AS interval_width
    FROM backtest_results
    WHERE experiment = :experiment AND run_id = :run_id AND slice_kind = :slice_kind
    GROUP BY model_name, horizon_min, slice_value
    ORDER BY horizon_min, model_name, slice_value
    """
)


def default_run(conn: Connection, experiment: str) -> str | None:
    """The experiment's run with the most folds, newest first."""
    value = conn.execute(DEFAULT_RUN, {"experiment": experiment}).scalar()
    return None if value is None else str(value)


def backtest(
    conn: Connection, experiment: str, run_id: str, slice_kind: str
) -> list[dict[str, Any]]:
    """Mean over folds per model, horizon and slice value."""
    params = {"experiment": experiment, "run_id": run_id, "slice_kind": slice_kind}
    return [dict(r) for r in conn.execute(BACKTEST, params).mappings()]


def collector_polls(conn: Connection, days: int) -> int:
    """Successful collector polls in the last ``days`` days."""
    sql = text(
        "SELECT count(*) FROM collector_runs "
        "WHERE status = 'ok' AND started_at > now() - make_interval(days => :days)"
    )
    return int(conn.execute(sql, {"days": days}).scalar() or 0)


def stations_modelled(conn: Connection) -> int:
    """Stations with a forecast in the newest issue."""
    sql = text(
        "SELECT count(DISTINCT station_key) FROM forecasts "
        "WHERE issued_at = (SELECT max(issued_at) FROM forecasts)"
    )
    return int(conn.execute(sql).scalar() or 0)
