from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dockcast.evaluation.training import prepare_training
from dockcast.features.matrix import feature_columns
from dockcast.models.lgbm_quantile import LgbmQuantile
from dockcast.serving.bundle import Bundle, BundleMeta, latest_bundle, model_version, save_bundle
from dockcast.serving.forecast import next_run, predict
from tests.unit.test_models_m4 import CAL, INFO
from tests.unit.test_targets_backtest import T0, make_panel

pytestmark = pytest.mark.unit
HORIZONS = [30, 60, 120]


def tiny_bundle(folder: Path, days: int = 20, bundle_id: str = "lgbm-q-test") -> Path:
    """A real (small) bundle trained on the synthetic panel; stations 'A' -> 1, 'B' -> 2."""
    panel = make_panel(days=days)
    train_end = (T0 + pd.Timedelta(days=days - 1)).to_pydatetime()
    cols = feature_columns()
    models, encoding = {}, pd.Series(dtype=float)
    for h in HORIZONS:
        train, valid, encoding = prepare_training(panel, train_end, h, [], CAL, INFO, T0)
        models[h] = LgbmQuantile(
            cols, [1, 2], n_estimators=20, early_stopping=5, params={"min_data_in_leaf": 5}
        ).fit(train, train["y"], valid, valid["y"])
    enc = encoding.rename("value").reset_index()
    enc.columns = ["station_key", "hour", "value"]
    enc["source_id"] = enc["station_key"].map({1: "A", 2: "B"})
    meta = BundleMeta(
        bundle_id=bundle_id,
        model_name="lgbm_global",
        features=cols,
        horizons_min=HORIZONS,
        station_keys={"A": 1, "B": 2},
        data_start=T0.to_pydatetime(),
        train_end=train_end,
        trained_at=datetime(2026, 10, 26, tzinfo=UTC),
        git_commit="abc1234",
        mlflow_run_id="run-test",
        best_iterations={
            f"h{h}_q{q:g}": i for h, m in models.items() for q, i in m.best_iterations.items()
        },
        backtest={str(h): {"mae": 1.0, "e1_run_id": "e1-test"} for h in HORIZONS},
    )
    return save_bundle(folder, meta, models, enc[["source_id", "hour", "value"]])


@pytest.fixture(scope="module")
def bundle(tmp_path_factory: pytest.TempPathFactory) -> Bundle:
    return Bundle(tiny_bundle(tmp_path_factory.mktemp("models")))


def test_bundle_round_trip_predicts_like_the_fitted_model(tmp_path: Path) -> None:
    path = tiny_bundle(tmp_path)
    loaded = Bundle(path)
    assert latest_bundle(tmp_path) == path
    assert model_version("lgbm-q-test", 60) == "lgbm-q-test-h60"
    panel = make_panel(days=20)
    end = (T0 + pd.Timedelta(days=19)).to_pydatetime()
    _, valid, _ = prepare_training(panel, end, 60, [], CAL, INFO, T0)
    pred = loaded.models[60].predict(valid)
    assert pred.notna().all().all() and len(pred) == len(valid)


def test_predict_maps_served_keys_through_source_id(bundle: Bundle) -> None:
    # Served database numbers the same stations 7 ('B') and 9 ('A'); 'Z' is unknown to the bundle.
    panel = make_panel(days=24, stations=(1, 2, 3))
    panel["station_key"] = panel["station_key"].map({1: 9, 2: 7, 3: 5})
    stations = pd.DataFrame(
        {"station_key": [5, 7, 9], "source_id": ["Z", "B", "A"],
         "lat": [53.3, 53.35, 53.34], "lon": [-6.2, -6.27, -6.26]}
    )  # fmt: skip
    issued = T0 + pd.Timedelta(days=22)
    out = predict(bundle, panel, stations, CAL, issued)
    assert set(out["station_key"]) == {7, 9}  # unknown station skipped
    assert sorted(out["horizon_min"].unique()) == HORIZONS and len(out) == 6
    assert (out["bikes_p10"] <= out["bikes_p50"]).all()
    assert (out["bikes_p50"] <= out["bikes_p90"]).all()
    assert out["bikes_p90"].le(30).all() and out["bikes_p10"].ge(0).all()
    assert (out["target_ts"] == issued + pd.to_timedelta(out["horizon_min"], unit="min")).all()
    assert set(out["model_version"]) == {f"lgbm-q-test-h{h}" for h in HORIZONS}


def test_predict_ignores_states_after_issue_time(bundle: Bundle) -> None:
    panel = make_panel(days=24)
    stations = pd.DataFrame({"station_key": [1, 2], "source_id": ["A", "B"],
                             "lat": [53.34, 53.35], "lon": [-6.26, -6.27]})  # fmt: skip
    issued = T0 + pd.Timedelta(days=22)
    poisoned = panel.copy()
    poisoned.loc[poisoned.state_ts > issued, "bikes"] = 1e6
    a = predict(bundle, panel, stations, CAL, issued)
    b = predict(bundle, poisoned, stations, CAL, issued)
    pd.testing.assert_frame_equal(a, b)


def test_station_without_current_state_gets_no_forecast(bundle: Bundle) -> None:
    panel = make_panel(days=24)
    issued = T0 + pd.Timedelta(days=22)
    panel.loc[(panel.station_key == 2) & (panel.state_ts == issued), "bikes"] = np.nan
    stations = pd.DataFrame({"station_key": [1, 2], "source_id": ["A", "B"],
                             "lat": [53.34, 53.35], "lon": [-6.26, -6.27]})  # fmt: skip
    out = predict(bundle, panel, stations, CAL, issued)
    assert set(out["station_key"]) == {1}


def test_next_run_is_offset_after_each_boundary() -> None:
    now = datetime(2026, 10, 26, 10, 0, 30, tzinfo=UTC)
    assert next_run(now, 60) == datetime(2026, 10, 26, 10, 1, tzinfo=UTC)
    assert next_run(now + timedelta(minutes=1), 60) == datetime(2026, 10, 26, 10, 16, tzinfo=UTC)
