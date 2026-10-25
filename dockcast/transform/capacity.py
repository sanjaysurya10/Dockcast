"""Capacity history (``station_capacity``) from the historical files and the live feed.

Each source row carries the station capacity at the time (Format A ``BIKE_STANDS``, Format B
``capacity``, live ``station_information``). Only change points are stored; the capacity of an
observation is the latest change point at or before it.
"""

from pathlib import Path

import pandas as pd
import structlog
from sqlalchemy import Engine, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from dockcast.config import get_env_settings, load_city_config
from dockcast.db.engine import make_engine
from dockcast.db.models import Station, StationCapacity, StationIdMap
from dockcast.ingest.historical.backfill import in_scope_files, load_file
from dockcast.transform.capacity_points import change_points, merge_points, point_records

log = structlog.get_logger(job="capacity")


def build_history(engine: Engine, hist_dir: Path, city_code: str) -> int:
    """Rebuild ``station_capacity`` from every in-scope historical file plus live capacities.

    Args:
        engine: Database engine.
        hist_dir: Directory of downloaded CSVs.
        city_code: City code.

    Returns:
        Number of change points stored.
    """
    with Session(engine) as session:
        legacy = dict(
            session.execute(
                select(StationIdMap.legacy_id, StationIdMap.station_key).where(
                    StationIdMap.city_code == city_code
                )
            ).all()
        )
        live = session.execute(
            select(Station.station_key, Station.capacity).where(Station.city_code == city_code)
        ).all()
    points = []
    for path in in_scope_files(hist_dir):
        df, _ = load_file(path)
        if df.empty:
            continue
        df = df.assign(station_key=df["source_id"].map(legacy)).dropna(subset=["station_key"])
        points.append(change_points(df[["station_key", "observed_at", "capacity", "source"]]))
        log.info("capacity_scanned", file=path.name)
    with engine.connect() as conn:
        first_live: dict[int, object] = dict(
            conn.execute(
                text(
                    "SELECT station_key, min(observed_at) FROM station_status_raw "
                    "WHERE source = 'live' GROUP BY 1"
                )
            ).all()
        )
    live_points = pd.DataFrame(
        [
            {"station_key": key, "valid_from": first_live[key], "capacity": cap, "source": "live"}
            for key, cap in live
            if key in first_live
        ]
    )
    merged = merge_points([*points, live_points])
    records = point_records(merged)
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE station_capacity"))
        if records:
            conn.execute(insert(StationCapacity), records)
    log.info("capacity_history_built", change_points=len(records))
    return len(records)


def main() -> None:
    """``python -m dockcast.transform.capacity`` (``make capacity``)."""
    settings = get_env_settings()
    city = load_city_config(settings.city)
    build_history(make_engine(), settings.data_dir / "raw" / "hist", city.city_code)


if __name__ == "__main__":
    main()
