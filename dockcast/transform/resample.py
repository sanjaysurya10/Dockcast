"""Raw observations → ``station_status_15m`` (PRD 9.3, 9.4, 9.8).

All in SQL inside Postgres (≈20 M raw rows), one station at a time for full rebuilds:

1. **Spikes** (owner decision 2026-10-25): an observation that differs by at least
   ``spike_min_delta`` from both neighbours, in the same direction (a V-shaped single-reading
   dip/peak), with both neighbours within ``spike_max_gap_min``, is excluded from buckets (it stays
   in ``station_status_raw``). Removes e.g. the nightly 03:15 local Format B glitch.
2. Bucket remaining rows with ``date_bin('15 minutes', ...)`` in UTC: last/min/max bikes and docks,
   observation count, ``is_closed`` if any observation had ``is_renting = false``, and flags:
   ``rebalance_flag`` when bikes swing by at least ``rebalance_min_delta`` within
   ``rebalance_window_min``; ``flatline_flag`` when the observation belongs to a run of unchanged
   bikes (while renting, broken by silences > ``run_break_gap_min``) lasting at least
   ``flatline_min_hours``; ``capacity_mismatch`` when bikes + docks exceed the capacity in force
   at the time (``station_capacity``) by more than ``capacity_tolerance``.
3. One row per station per bucket for its active period, including empty buckets (``n_obs = 0``).
4. Forward-fill an empty bucket from the last observed bucket at most 2 buckets (30 min) earlier,
   marking ``is_imputed``; never when the bucket overlaps a data gap (PRD 9.8). Flags and
   ``bikes_min/max``/``docks_min`` are never imputed.

Timestamps are UTC end to end, so DST changes cannot create duplicate or missing buckets.
"""

import argparse
from collections.abc import Sequence
from datetime import datetime, timedelta

import structlog
from sqlalchemy import Engine, TextClause, text

from dockcast.config import CleaningConfig, load_project_config
from dockcast.db.engine import make_engine

log = structlog.get_logger(job="resample")

BUCKET = timedelta(minutes=15)
MAX_FILL_BUCKETS = 2


def build_resample_sql(cfg: CleaningConfig) -> TextClause:
    """The resample statement with cleaning thresholds inlined (validated integers).

    Args:
        cfg: Cleaning thresholds.

    Returns:
        SQL statement taking ``since, read_from, until, station_keys, max_fill``.
    """
    return text(
        f"""
WITH raw AS (
    SELECT station_key, observed_at, bikes_available AS b, docks_available AS d, is_renting,
           lag(bikes_available) OVER w AS pb, lag(observed_at) OVER w AS pt,
           lead(bikes_available) OVER w AS nb, lead(observed_at) OVER w AS nt
    FROM station_status_raw
    WHERE observed_at >= :read_from AND observed_at < :until
      AND (CAST(:station_keys AS bigint[]) IS NULL
           OR station_key = ANY(CAST(:station_keys AS bigint[])))
    WINDOW w AS (PARTITION BY station_key ORDER BY observed_at)
),
kept AS (
    SELECT station_key, observed_at, b, d, is_renting
    FROM raw
    WHERE NOT COALESCE(
        observed_at - pt <= INTERVAL '{cfg.spike_max_gap_min} minutes'
        AND nt - observed_at <= INTERVAL '{cfg.spike_max_gap_min} minutes'
        AND abs(b - pb) >= {cfg.spike_min_delta} AND abs(b - nb) >= {cfg.spike_min_delta}
        AND sign(b - pb) = sign(b - nb), false)
),
marked AS (
    SELECT k.*,
           max(b) OVER r - min(b) OVER r AS swing,
           (b IS DISTINCT FROM lag(b) OVER w
            OR is_renting IS DISTINCT FROM lag(is_renting) OVER w
            OR observed_at - lag(observed_at) OVER w
               > INTERVAL '{cfg.run_break_gap_min} minutes')::int AS brk
    FROM kept k
    WINDOW w AS (PARTITION BY station_key ORDER BY observed_at),
           r AS (PARTITION BY station_key ORDER BY observed_at
                 RANGE BETWEEN INTERVAL '{cfg.rebalance_window_min} minutes' PRECEDING
                 AND CURRENT ROW)
),
runs AS (
    SELECT m.*, sum(brk) OVER (PARTITION BY station_key ORDER BY observed_at) AS run
    FROM marked m
),
runlen AS (
    SELECT r.*,
           max(observed_at) OVER (PARTITION BY station_key, run)
           - min(observed_at) OVER (PARTITION BY station_key, run) AS run_len
    FROM runs r
),
obs AS (
    SELECT station_key,
           date_bin('15 minutes', observed_at, TIMESTAMPTZ '2000-01-01 00:00+00') AS ts,
           (array_agg(b ORDER BY observed_at DESC))[1] AS bikes_last,
           min(b) AS bikes_min, max(b) AS bikes_max,
           (array_agg(d ORDER BY observed_at DESC))[1] AS docks_last,
           min(d) AS docks_min,
           count(*) AS n_obs,
           bool_or(is_renting IS FALSE) AS is_closed,
           bool_or(swing >= {cfg.rebalance_min_delta}) AS rebalance_flag,
           bool_or(run_len >= INTERVAL '{cfg.flatline_min_hours} hours'
                   AND is_renting IS NOT FALSE) AS flatline_flag
    FROM runlen
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
           COALESCE(o.rebalance_flag, false) AS rebalance_flag,
           COALESCE(o.flatline_flag, false) AS flatline_flag,
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
                                docks_min, n_obs, is_imputed, is_closed, rebalance_flag,
                                capacity_mismatch, flatline_flag)
SELECT f.station_key, f.ts,
       CASE WHEN f.n_obs > 0 THEN f.bikes_last WHEN imp.ok THEN f.src_bikes END,
       f.bikes_min, f.bikes_max,
       CASE WHEN f.n_obs > 0 THEN f.docks_last WHEN imp.ok THEN f.src_docks END,
       f.docks_min, f.n_obs,
       f.n_obs = 0 AND imp.ok,
       CASE WHEN f.n_obs > 0 THEN f.is_closed WHEN imp.ok THEN f.src_closed ELSE false END,
       f.rebalance_flag,
       COALESCE(f.n_obs > 0
                AND f.bikes_last + f.docks_last > cap.capacity + {cfg.capacity_tolerance}, false),
       f.flatline_flag
FROM filled f
CROSS JOIN LATERAL (
    SELECT f.n_obs = 0 AND f.src_n > 0
           AND f.ts - f.src_ts <= :max_fill
           AND NOT EXISTS (
               SELECT 1 FROM data_gaps g
               WHERE g.gap_start < f.ts + INTERVAL '15 minutes' AND g.gap_end > f.ts
           ) AS ok
) imp
LEFT JOIN LATERAL (
    SELECT c.capacity FROM station_capacity c
    WHERE c.station_key = f.station_key AND c.valid_from < f.ts + INTERVAL '15 minutes'
    ORDER BY c.valid_from DESC LIMIT 1
) cap ON true
WHERE f.ts >= :since
ON CONFLICT (station_key, ts) DO UPDATE SET
    bikes_last = EXCLUDED.bikes_last, bikes_min = EXCLUDED.bikes_min,
    bikes_max = EXCLUDED.bikes_max, docks_last = EXCLUDED.docks_last,
    docks_min = EXCLUDED.docks_min, n_obs = EXCLUDED.n_obs,
    is_imputed = EXCLUDED.is_imputed, is_closed = EXCLUDED.is_closed,
    rebalance_flag = EXCLUDED.rebalance_flag, capacity_mismatch = EXCLUDED.capacity_mismatch,
    flatline_flag = EXCLUDED.flatline_flag
"""
    )


def resample(
    engine: Engine,
    since: datetime | None = None,
    until: datetime | None = None,
    station_keys: Sequence[int] | None = None,
) -> int:
    """Rebuild 15-min buckets with ``ts >= since`` (everything when ``since`` is None).

    Raw rows from ``flatline_min_hours + 1`` hours before ``since`` are read so the first rebuilt
    buckets still see their neighbours, fill sources and flat-line runs.

    Args:
        engine: Database engine.
        since: First bucket to (re)write; None rebuilds the whole table.
        until: Exclusive upper bound on raw ``observed_at``; None = no bound.
        station_keys: Restrict to these stations (tests / partial rebuilds).

    Returns:
        Number of buckets written.
    """
    cfg = load_project_config().cleaning
    floor = datetime.fromisoformat("1970-01-01T00:00:00+00:00")
    start = since or floor
    lookback = max(BUCKET * (MAX_FILL_BUCKETS + 1), timedelta(hours=cfg.flatline_min_hours + 1))
    params = {
        "since": start,
        "read_from": start - lookback if since else floor,
        "until": until or datetime.fromisoformat("9999-01-01T00:00:00+00:00"),
        "station_keys": list(station_keys) if station_keys else None,
        "max_fill": BUCKET * MAX_FILL_BUCKETS,
    }
    with engine.begin() as conn:
        if since is None and station_keys is None:
            conn.execute(text("TRUNCATE station_status_15m"))
        written = conn.execute(build_resample_sql(cfg), params).rowcount
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
