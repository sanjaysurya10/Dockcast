"""Production model bundle: one LightGBM booster per horizon and quantile, plus serving inputs.

Layout of ``<models_dir>/<bundle_id>/``:

- ``meta.json``: :class:`BundleMeta` (features, training window, MLflow runs, backtest metrics).
- ``h<H>_q<Q>.txt``: LightGBM model text (saved at its best iteration).
- ``encoding.parquet``: station x local hour occupancy encoding, keyed by ``source_id``.

Stations are stored by the feed's ``source_id`` so a bundle trained on the research database
can serve a database whose surrogate ``station_key`` values differ.
"""

from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import pandas as pd
from pydantic import BaseModel

from dockcast.models.lgbm_quantile import QUANTILES, LgbmQuantile

META_FILE = "meta.json"
ENCODING_FILE = "encoding.parquet"


class BundleMeta(BaseModel):
    """What a bundle was trained on and how it backtested."""

    bundle_id: str
    model_name: str
    features: list[str]
    horizons_min: list[int]
    station_keys: dict[str, int]  # source_id -> station_key used as the training category
    data_start: datetime
    train_end: datetime
    trained_at: datetime
    git_commit: str
    mlflow_run_id: str
    best_iterations: dict[str, int]  # "h<H>_q<Q>" -> rounds
    backtest: dict[str, dict[str, float | str]]  # str(horizon) -> E1 metrics + run id


def model_version(bundle_id: str, horizon_min: int) -> str:
    """``model_versions`` key for one horizon of a bundle."""
    return f"{bundle_id}-h{horizon_min}"


def _booster_file(horizon_min: int, quantile: float) -> str:
    return f"h{horizon_min}_q{quantile:g}.txt"


def save_bundle(
    folder: Path,
    meta: BundleMeta,
    models: dict[int, LgbmQuantile],
    encoding: pd.DataFrame,
) -> Path:
    """Write a bundle.

    Args:
        folder: Parent directory (``models_dir``).
        meta: Bundle metadata.
        models: Fitted model per horizon.
        encoding: Columns ``source_id, hour, value``.

    Returns:
        The bundle directory.
    """
    path = folder / meta.bundle_id
    path.mkdir(parents=True, exist_ok=True)
    for horizon, model in models.items():
        for q, booster in model.boosters.items():
            booster.save_model(
                str(path / _booster_file(horizon, q)), num_iteration=model.best_iterations[q]
            )
    encoding.to_parquet(path / ENCODING_FILE, index=False)
    (path / META_FILE).write_text(meta.model_dump_json(indent=1), encoding="utf-8")
    return path


class Bundle:
    """A loaded bundle ready to predict."""

    def __init__(self, path: Path) -> None:
        """Load ``meta.json``, the encoding and every booster under ``path``."""
        self.path = path
        self.meta = BundleMeta.model_validate_json((path / META_FILE).read_text("utf-8"))
        self.encoding = pd.read_parquet(path / ENCODING_FILE)
        self.models: dict[int, LgbmQuantile] = {}
        stations = sorted(self.meta.station_keys.values())
        for horizon in self.meta.horizons_min:
            model = LgbmQuantile(self.meta.features, stations)
            for q in QUANTILES:
                booster = lgb.Booster(model_file=str(path / _booster_file(horizon, q)))
                model.boosters[q] = booster
                model.best_iterations[q] = booster.current_iteration()
            self.models[horizon] = model


def latest_bundle(folder: Path) -> Path:
    """Newest bundle directory by ``trained_at``.

    Raises:
        FileNotFoundError: When no bundle exists.
    """
    metas = [
        (BundleMeta.model_validate_json((p / META_FILE).read_text("utf-8")).trained_at, p)
        for p in folder.glob("*")
        if (p / META_FILE).exists()
    ]
    if not metas:
        raise FileNotFoundError(f"no model bundle in {folder}")
    return max(metas)[1]
