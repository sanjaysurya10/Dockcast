"""Raw observations → ``station_status_15m`` (PRD 9.3 gaps rule, 9.4, 9.8).

All in SQL inside Postgres (≈20 M raw rows):

1. Bucket raw rows with ``date_bin('15 minutes', observed_at, epoch)`` in UTC; per bucket keep
   the last, min and max bikes and docks, the observation count, and ``is_closed`` if any
   observation in the bucket had ``is_renting = false``.
2. Emit one row per station per bucket for the station's active period (first to last
   observation), including empty buckets (``n_obs = 0``).
3. Forward-fill an empty bucket from the last observed bucket at most 2 buckets (30 min) earlier,
   marking ``is_imputed``; never when the bucket overlaps a data gap (PRD 9.8). Empty buckets that
   cannot be filled stay NULL. ``bikes_min/max`` and ``docks_min`` are never imputed.

Timestamps are UTC end to end, so DST changes cannot create duplicate or missing buckets.
"""

import argparse
from collections.abc import Sequence
from datetime import datetime, timedelta

import structlog
from sqlalchemy import Engine, text

from dockcast.db.engine import make_engine

log = structlog.get_logger(job="resample")

BUCKET = timedelta(minutes=15)
MAX_FILL_BUCKETS = 2

RESAMPLE_SQL = text(
    """
WITH obs AS (
    SELECT station_key,
           date_bin('15 minutes', observed_at, TIMESTAMPTZ '2000-01-01 00:00+00') AS ts,
           (array_agg(bikes_available ORDER BY observed_at DESC))[1] AS bikes_last,
           min(bikes_available) AS bikes_min,
           max(bikes_available) AS bikes_max,
           (array_agg(docks_available ORDER BY observed_at DESC))[1] AS docks_last,
           min(docks_available) AS docks_min,
           count(*) AS n_obs,
           bool_or(is_renting IS FALSE) AS is_closed
    FROM station_status_raw
    WHERE observed_at >= :read_from AND observed_at < :until
      AND (CAST(:station_keys AS bigint[]) IS NULL
           OR station_key = ANY(CAST(:station_keys AS bigint[])))
    GROUP BY 1, 2
),
span AS (
    SELECT station_key, min(ts) AS first_ts, max(ts) AS last_ts
    FROM obs GROUP BY 1
),
grid AS (
    SELECT s.station_key, g.ts
    FROM span s,
         LATERAL generate_series(s.first_ts, s.last_ts, INTERVAL '15 minutes') AS g(ts)
),
joined AS (
    SELECT g.station_key, g.ts, o.bikes_last, o.bikes_min, o.bikes_max, o.docks_last,
           o.docks_min, COALESCE(o.n_obs, 0) AS n_obs, COALESCE(o.is_closed, false) AS is_closed,
           count(o.n_obs) OVER w AS grp
    FROM grid g LEFT JOIN obs o USING (station_key, ts)
    WINDOW w AS (PARTITION BY g.station_key ORDER BY g.ts)
),
filled AS (
    SELECT j.*,
           first_value(j.ts) OVER p AS src_ts,
           first_value(j.bikes_last) OVER p AS src_bikes,
           first_value(j.docks_last) OVER p AS src_docks,
           first_value(j.is_closed) OVER p AS src_closed,
           first_value(j.n_obs) OVER p AS src_n
    FROM joined j
    WINDOW p AS (PARTITION BY j.station_key, j.grp ORDER BY j.ts)
)
INSERT INTO station_status_15m (station_key, ts, bikes_last, bikes_min, bikes_max, docks_last,
                                docks_min, n_obs, is_imputed, is_closed)
SELECT f.station_key, f.ts,
       CASE WHEN f.n_obs > 0 THEN f.bikes_last WHEN imp.ok THEN f.src_bikes END,
       f.bikes_min, f.bikes_max,
       CASE WHEN f.n_obs > 0 THEN f.docks_last WHEN imp.ok THEN f.src_docks END,
       f.docks_min, f.n_obs,
       f.n_obs = 0 AND imp.ok,
       CASE WHEN f.n_obs > 0 THEN f.is_closed WHEN imp.ok THEN f.src_closed ELSE false END
FROM filled f
CROSS JOIN LATERAL (
    SELECT f.n_obs = 0 AND f.src_n > 0
           AND f.ts - f.src_ts <= :max_fill
           AND NOT EXISTS (
               SELECT 1 FROM data_gaps d
               WHERE d.gap_start < f.ts + INTERVAL '15 minutes' AND d.gap_end > f.ts
           ) AS ok
) imp
WHERE f.ts >= :since
ON CONFLICT (station_key, ts) DO UPDATE SET
    bikes_last = EXCLUDED.bikes_last, bikes_min = EXCLUDED.bikes_min,
    bikes_max = EXCLUDED.bikes_max, docks_last = EXCLUDED.docks_last,
    docks_min = EXCLUDED.docks_min, n_obs = EXCLUDED.n_obs,
    is_imputed = EXCLUDED.is_imputed, is_closed = EXCLUDED.is_closed
"""
)


def resample(
    engine: Engine,
    since: datetime | None = None,
    until: datetime | None = None,
    station_keys: Sequence[int] | None = None,
) -> int:
    """Rebuild 15-min buckets with ``ts >= since`` (everything when ``since`` is None).

    Raw rows from ``MAX_FILL_BUCKETS`` buckets before ``since`` are read so the first rebuilt
    buckets can still be forward-filled.

    Args:
        engine: Database engine.
        since: First bucket to (re)write; None rebuilds the whole table.
        until: Exclusive upper bound on raw ``observed_at``; None = no bound.
        station_keys: Restrict to these stations (tests / partial rebuilds).

    Returns:
        Number of buckets written.
    """
    floor = datetime.fromisoformat("1970-01-01T00:00:00+00:00")
    start = since or floor
    params = {
        "since": start,
        "read_from": start - BUCKET * (MAX_FILL_BUCKETS + 1) if since else floor,
        "until": until or datetime.fromisoformat("9999-01-01T00:00:00+00:00"),
        "station_keys": list(station_keys) if station_keys else None,
        "max_fill": BUCKET * MAX_FILL_BUCKETS,
    }
    with engine.begin() as conn:
        if since is None and station_keys is None:
            conn.execute(text("TRUNCATE station_status_15m"))
        written = conn.execute(RESAMPLE_SQL, params).rowcount
    log.info("resampled", since=str(since), buckets=written)
    return int(written)


def incremental_start(engine: Engine, lookback: timedelta = timedelta(hours=2)) -> datetime | None:
    """Where an incremental run starts: ``lookback`` before the newest bucket (None if empty).

    Args:
        engine: Database engine.
        lookback: How far back to recompute (late rows, partial last bucket).

    Returns:
        Start time or None when the table is empty.
    """
    with engine.connect() as conn:
        newest = conn.execute(text("SELECT max(ts) FROM station_status_15m")).scalar()
    return None if newest is None else newest - lookback


def resample_per_station(engine: Engine, since: datetime | None = None) -> int:
    """Run :func:`resample` one station at a time to keep sort/temp space small.

    Args:
        engine: Database engine.
        since: As in :func:`resample`; None rebuilds everything (table truncated first).

    Returns:
        Total buckets written.
    """
    with engine.begin() as conn:
        keys = [row[0] for row in conn.execute(text("SELECT station_key FROM stations ORDER BY 1"))]
        if since is None:
            conn.execute(text("TRUNCATE station_status_15m"))
    total = 0
    for key in keys:
        total += resample(engine, since, station_keys=[key])
    log.info("resampled_all", stations=len(keys), buckets=total)
    return total


def main(argv: Sequence[str] | None = None) -> None:
    """``python -m dockcast.transform.resample [--full]`` (``make resample``)."""
    parser = argparse.ArgumentParser(description="Rebuild station_status_15m (PRD 9.4).")
    parser.add_argument("--full", action="store_true", help="rebuild everything")
    args = parser.parse_args(argv)
    engine = make_engine()
    resample_per_station(engine, None if args.full else incremental_start(engine))


if __name__ == "__main__":
    main()
