"""Train the production champion (``make train``; PRD 6.2, 12.5, M5 owner decision 2026-10-26).

Same procedure as an E1 fold, with ``train_end`` at the end of the last complete Format B month:
hourly training issue times on all Format B history, early stopping on the last training week.
Only horizons whose latest full E1 run names ``lgbm_global`` champion are trained. The bundle is
written to ``<data_dir>/models/<bundle_id>/`` and logged to MLflow (experiment ``train``); the
forecast job registers it in ``model_versions`` of the database it serves.
"""

import argparse
import io
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import mlflow
import pandas as pd
import structlog
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from dockcast.config import get_env_settings, load_project_config
from dockcast.db.engine import make_engine
from dockcast.evaluation.reports import git_commit
from dockcast.evaluation.splits import last_complete_month_end
from dockcast.evaluation.training import prepare_training
from dockcast.experiments.e1 import b_span, reference_tables
from dockcast.features.matrix import feature_columns
from dockcast.models.lgbm_quantile import LgbmQuantile
from dockcast.quality.gaps import load_gaps
from dockcast.serving.bundle import BundleMeta, save_bundle
from dockcast.targets.regression import load_panel
from dockcast.tracking import setup_mlflow

log = structlog.get_logger(job="train")
MODEL = "lgbm_global"


def latest_e1(horizons: Sequence[int]) -> tuple[str, dict[str, dict[str, float | str]]]:
    """Newest finished full E1 run and its champion metrics per horizon.

    Args:
        horizons: Horizons that must all have ``lgbm_global`` as champion.

    Returns:
        Run id and ``{str(horizon): {mae, mase, coverage_80, e1_run_id}}``.

    Raises:
        LookupError: No full E1 run, or ``lgbm_global`` is not champion at some horizon.
    """
    runs = mlflow.search_runs(
        experiment_names=["E1"],
        filter_string=(
            f"params.n_folds = '{load_project_config().backtest.n_folds}' "
            "and attributes.status = 'FINISHED'"
        ),
        order_by=["attributes.start_time DESC"],
        output_format="list",
    )
    full = [r for r in runs if r.data.params.get("horizons") == ",".join(map(str, horizons))]
    if not full:
        raise LookupError("no finished full E1 run; run `make backtest E=E1` first")
    run = full[0]
    champions = pd.read_csv(
        io.StringIO(mlflow.artifacts.load_text(f"{run.info.artifact_uri}/champions.csv"))
    )
    metrics: dict[str, dict[str, float | str]] = {}
    for h in horizons:
        pick = champions.loc[champions.horizon_min == h, "champion"]
        if pick.empty or pick.iloc[0] != MODEL:
            raise LookupError(f"E1 run {run.info.run_id}: champion at +{h} is not {MODEL}")
        key = f"{MODEL}_h{h}"
        metrics[str(h)] = {
            "mae": run.data.metrics[f"mae_{key}"],
            "mase": run.data.metrics[f"mase_{key}"],
            "coverage_80": run.data.metrics[f"coverage80_{key}"],
            "e1_run_id": run.info.run_id,
        }
    return run.info.run_id, metrics


def source_ids(engine: Engine) -> dict[int, str]:
    """``station_key -> source_id`` of the research database."""
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT station_key, source_id FROM stations")).all()
    return {int(k): str(s) for k, s in rows}


def train(engine: Engine, horizons: Sequence[int], num_threads: int) -> str:
    """Train, save and log a bundle.

    Args:
        engine: Research database (Format B history).
        horizons: Horizons to train.
        num_threads: LightGBM threads.

    Returns:
        The bundle directory.
    """
    commit = git_commit()
    e1_run, backtest = latest_e1(horizons)
    data_start, last_obs = b_span(engine)
    train_end = last_complete_month_end(last_obs, timedelta(minutes=30))
    with Session(engine) as session:
        gaps = load_gaps(session)
    calendar, info = reference_tables(engine)
    panel = load_panel(engine, data_start, train_end)
    stations = sorted(int(s) for s in panel["station_key"].unique())
    ids = source_ids(engine)
    features = feature_columns()
    models: dict[int, LgbmQuantile] = {}
    encoding = pd.Series(dtype=float)
    for h in horizons:
        rows_train, rows_valid, encoding = prepare_training(
            panel, train_end, h, gaps, calendar, info, data_start
        )
        model = LgbmQuantile(features, stations, num_threads=num_threads)
        model.fit(rows_train, rows_train["y"], rows_valid, rows_valid["y"])
        models[h] = model
        log.info("trained", horizon=h, train=len(rows_train), valid=len(rows_valid),
                 iterations=model.best_iterations)  # fmt: skip
    trained_at = datetime.now(UTC)
    bundle_id = f"lgbm-q-{train_end - timedelta(days=1):%Y-%m-%d}-{commit[:7]}"
    enc = encoding.rename("value").reset_index()
    enc.columns = ["station_key", "hour", "value"]
    enc["source_id"] = enc["station_key"].map(ids)
    with mlflow.start_run(run_name="train") as active:
        meta = BundleMeta(
            bundle_id=bundle_id,
            model_name=MODEL,
            features=features,
            horizons_min=list(horizons),
            station_keys={ids[k]: k for k in stations},
            data_start=data_start,
            train_end=train_end,
            trained_at=trained_at,
            git_commit=commit,
            mlflow_run_id=active.info.run_id,
            best_iterations={
                f"h{h}_q{q:g}": it for h, m in models.items() for q, it in m.best_iterations.items()
            },
            backtest=backtest,
        )
        path = save_bundle(
            get_env_settings().models_dir, meta, models, enc[["source_id", "hour", "value"]]
        )
        mlflow.log_params(
            {
                "bundle_id": bundle_id,
                "model": MODEL,
                "data_start": data_start.isoformat(),
                "train_end": train_end.isoformat(),
                "git_commit": commit,
                "e1_run_id": e1_run,
                "horizons": ",".join(map(str, horizons)),
            }
        )
        mlflow.log_metrics({f"best_iteration_{k}": v for k, v in meta.best_iterations.items()})
        mlflow.log_artifacts(str(path), artifact_path="bundle")
    log.info("bundle_saved", path=str(path), mlflow_run_id=meta.mlflow_run_id)
    return str(path)


def main(argv: Sequence[str] | None = None) -> None:
    """``make train``."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--threads", type=int, default=10)
    args = parser.parse_args(argv)
    setup_mlflow("train")
    train(make_engine(), load_project_config().forecast.horizons_min, args.threads)


if __name__ == "__main__":
    main()
