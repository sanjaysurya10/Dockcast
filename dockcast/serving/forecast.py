"""Forecast job (``make forecast``; PRD 6.2): every 15 min write ``forecasts`` for each station.

One cycle at issue time ``t`` (the latest 15-min boundary):

1. Resample recent live rows into ``station_status_15m``.
2. Skip the cycle when the newest live observation is older than ``serving.stale_after_min``.
3. Build features from states at or before ``t`` (same code as the backtest, PRD 10.1).
4. Predict P10/P50/P90 per horizon, post-process (PRD 12.4), upsert ``forecasts``.

Stations with no state at ``t`` get no forecast. Station keys of the served database are mapped
to the bundle's training keys through ``source_id`` (:mod:`dockcast.serving.bundle`).
"""

import argparse
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import structlog
from sqlalchemy import Engine, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from dockcast.config import get_env_settings, load_project_config
from dockcast.db.engine import make_engine
from dockcast.db.models import Forecast, ModelVersion
from dockcast.evaluation.splits import floor_to_grid
from dockcast.features.matrix import build_grid, feature_matrix
from dockcast.models.postprocess import postprocess
from dockcast.quality.gaps import Gap, load_gaps
from dockcast.serving.bundle import Bundle, latest_bundle, model_version
from dockcast.targets.regression import load_panel
from dockcast.transform.resample import incremental_start, resample_per_station

log = structlog.get_logger(job="forecast")
HISTORY = timedelta(days=8)  # 7-day seasonal lag + 24 h zero counts + margin
STEP = timedelta(minutes=15)
UPDATE_COLUMNS = ("bikes_p10", "bikes_p50", "bikes_p90", "model_version")


def register(engine: Engine, bundle: Bundle) -> None:
    """Upsert the bundle's ``model_versions`` rows and make them the champions."""
    meta = bundle.meta
    rows = [
        {
            "model_version": model_version(meta.bundle_id, h),
            "mlflow_run_id": meta.mlflow_run_id,
            "kind": "regression",
            "horizon_min": h,
            "trained_at": meta.trained_at,
            "train_end": meta.train_end,
            "is_champion": True,
            "metrics": {**meta.backtest[str(h)], "model_name": meta.model_name},
        }
        for h in meta.horizons_min
    ]
    stmt = insert(ModelVersion).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["model_version"],
        set_={"is_champion": True, "metrics": stmt.excluded.metrics},
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE model_versions SET is_champion = false "
                "WHERE kind = 'regression' AND NOT (model_version = ANY(:keep))"
            ),
            {"keep": [r["model_version"] for r in rows]},
        )
        conn.execute(stmt)


def newest_live(engine: Engine) -> datetime | None:
    """Newest live observation time."""
    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT max(observed_at) FROM station_status_raw WHERE source = 'live'")
        ).scalar()
    return None if value is None else value.astimezone(UTC)


def serving_inputs(engine: Engine) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Active stations (``station_key, source_id, lat, lon``) and ``calendar_days``."""
    with engine.connect() as conn:
        stations = pd.read_sql(
            text("SELECT station_key, source_id, lat, lon FROM stations WHERE is_active"), conn
        )
        calendar = pd.read_sql(
            text("SELECT date, is_public_holiday, is_school_term, is_uni_term FROM calendar_days"),
            conn,
        )
    return stations, calendar


def predict(
    bundle: Bundle,
    panel: pd.DataFrame,
    stations: pd.DataFrame,
    calendar: pd.DataFrame,
    issued_at: pd.Timestamp,
    gaps: Sequence[Gap] = (),
) -> pd.DataFrame:
    """Forecast rows for every station with a state at ``issued_at``.

    Args:
        bundle: Loaded bundle.
        panel: States (served keys) up to ``issued_at``; later states are ignored.
        stations: ``station_key, source_id, lat, lon`` of the served database.
        calendar: ``calendar_days`` rows.
        issued_at: Issue time on the 15-min grid.
        gaps: Data gaps of the served database.

    Returns:
        Columns of ``forecasts``.
    """
    grid = build_grid(panel, gaps, issued_at)
    to_train = stations["source_id"].map(bundle.meta.station_keys)
    enc = bundle.encoding.merge(stations[["source_id", "station_key"]], on="source_id")
    encoding = enc.set_index(["station_key", "hour"])["value"]
    info = stations[["station_key", "lat", "lon"]]
    keys = stations["station_key"].astype(int)
    rows = pd.DataFrame({"station_key": keys, "issued_at": issued_at})
    frames = []
    for horizon, model in bundle.models.items():
        features = feature_matrix(grid, rows, horizon, calendar, info, encoding)
        features = features[features["bikes_now"].notna()]
        if features.empty:
            continue
        model_input = features.assign(station_key=to_train.loc[features.index].to_numpy())
        known = model_input["station_key"].notna()
        model_input = model_input[known].assign(station_key=lambda f: f["station_key"].astype(int))
        quantiles = postprocess(model.predict(model_input), model_input["capacity"])
        frames.append(
            pd.DataFrame(
                {
                    "station_key": features.loc[known, "station_key"].astype(int).to_numpy(),
                    "issued_at": issued_at,
                    "horizon_min": horizon,
                    "target_ts": issued_at + pd.Timedelta(minutes=horizon),
                    "bikes_p10": quantiles["p10"].to_numpy(),
                    "bikes_p50": quantiles["p50"].to_numpy(),
                    "bikes_p90": quantiles["p90"].to_numpy(),
                    "model_version": model_version(bundle.meta.bundle_id, horizon),
                }
            )
        )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def store(engine: Engine, frame: pd.DataFrame) -> int:
    """Upsert forecast rows (re-running a cycle overwrites it)."""
    if frame.empty:
        return 0
    records = [
        {k: (v.to_pydatetime() if isinstance(v, pd.Timestamp) else v) for k, v in r.items()}
        for r in frame.astype({"bikes_p10": float, "bikes_p50": float, "bikes_p90": float})
        .replace({np.nan: None})
        .to_dict("records")
    ]
    stmt = insert(Forecast).values(records)
    stmt = stmt.on_conflict_do_update(
        index_elements=["station_key", "issued_at", "horizon_min"],
        set_={c: stmt.excluded[c] for c in UPDATE_COLUMNS},
    )
    with engine.begin() as conn:
        conn.execute(stmt)
    return len(records)


def run_cycle(engine: Engine, bundle: Bundle, now: datetime) -> int:
    """One forecast cycle for the latest 15-min boundary before ``now``.

    Returns:
        Forecast rows written (0 when skipped as stale).
    """
    issued = floor_to_grid(now)
    resample_per_station(engine, incremental_start(engine))
    newest = newest_live(engine)
    stale_after = timedelta(minutes=load_project_config().serving.stale_after_min)
    if newest is None or issued - newest > stale_after:
        log.warning("stale_skip", issued_at=issued.isoformat(), newest_live=str(newest))
        return 0
    stations, calendar = serving_inputs(engine)
    panel = load_panel(engine, issued - HISTORY, issued)
    with Session(engine) as session:
        gaps = load_gaps(session)
    frame = predict(bundle, panel, stations, calendar, pd.Timestamp(issued), gaps)
    written = store(engine, frame)
    log.info("forecast_written", issued_at=issued.isoformat(), rows=written)
    return written


def next_run(now: datetime, offset_s: int) -> datetime:
    """The next ``boundary + offset`` strictly after ``now``."""
    candidate = floor_to_grid(now) + timedelta(seconds=offset_s)
    return candidate if candidate > now else candidate + STEP


def main(argv: Sequence[str] | None = None) -> None:
    """``python -m dockcast.serving.forecast [--loop] [--bundle PATH]`` (``make forecast``)."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="run every 15 min")
    parser.add_argument("--bundle", default=None, help="bundle directory (default: newest)")
    args = parser.parse_args(argv)
    engine = make_engine()
    path = Path(args.bundle) if args.bundle else latest_bundle(get_env_settings().models_dir)
    bundle = Bundle(path)
    register(engine, bundle)
    log.info("bundle_loaded", bundle_id=bundle.meta.bundle_id)
    offset = load_project_config().serving.run_offset_s
    while True:
        try:
            run_cycle(engine, bundle, datetime.now(UTC))
        except Exception:
            if not args.loop:
                raise
            log.exception("cycle_failed")
        if not args.loop:
            return
        wake = next_run(datetime.now(UTC), offset)
        time.sleep(max(0.0, (wake - datetime.now(UTC)).total_seconds()))


if __name__ == "__main__":
    main()
