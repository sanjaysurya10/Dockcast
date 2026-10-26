from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from dockcast.evaluation.backtest import score_fold, summarise
from dockcast.evaluation.champion import select_champions
from dockcast.evaluation.splits import Fold
from dockcast.evaluation.training import prepare_fold
from dockcast.features.matrix import feature_columns
from dockcast.models.baselines import Persistence, SeasonalNaive7d
from dockcast.models.lgbm_quantile import LgbmQuantile
from dockcast.models.linear import RidgeForecaster
from dockcast.models.postprocess import postprocess
from tests.unit.test_targets_backtest import T0, make_panel

pytestmark = pytest.mark.unit
CAL = pd.DataFrame(
    {
        "date": [date(2025, 10, 20) + timedelta(days=i) for i in range(40)],
        "is_public_holiday": False,
        "is_school_term": True,
        "is_uni_term": None,
    }
)
INFO = pd.DataFrame({"station_key": [1, 2], "lat": [53.34, 53.35], "lon": [-6.26, -6.27]})


def test_postprocess_sorts_and_clips() -> None:
    pred = pd.DataFrame({"p10": [5.0, -2.0], "p50": [3.0, 1.0], "p90": [40.0, 2.0]})
    out = postprocess(pred, pd.Series([30.0, np.nan]))
    assert out.iloc[0].tolist() == [3.0, 5.0, 30.0]
    assert out.iloc[1].tolist() == [0.0, 1.0, 2.0]


def test_champion_needs_coverage_and_prefers_simpler_on_ties() -> None:
    summary = pd.DataFrame(
        {
            "model_name": ["persistence", "ridge", "lgbm_global", "persistence", "lgbm_global"],
            "horizon_min": [60, 60, 60, 120, 120],
            "mae": [1.7, 1.5, 1.4, 2.7, 2.0],
            "coverage_80": [np.nan, np.nan, 0.79, np.nan, 0.55],
        }
    )
    champ = select_champions(summary).set_index("horizon_min")
    assert champ.loc[60, "champion"] == "lgbm_global"
    assert champ.loc[120, "champion"] is None and "coverage" in champ.loc[120, "reason"]


@pytest.fixture(scope="module")
def fold_data() -> tuple[Fold, object]:
    rng = np.random.default_rng(3)
    panel = make_panel(days=24)
    panel["bikes"] = np.clip(panel["bikes"] + rng.normal(0, 1, len(panel)).round(), 0, 30)
    panel["docks"] = 30 - panel["bikes"]
    test_start = (T0 + pd.Timedelta(days=21)).to_pydatetime()
    fold = Fold(1, test_start - timedelta(minutes=120), test_start, test_start + timedelta(days=2))
    data = prepare_fold(panel, fold, 60, [], CAL, INFO, T0.to_pydatetime())
    return fold, data


def test_prepare_fold_respects_train_end_and_resolution(fold_data: tuple[Fold, object]) -> None:
    fold, data = fold_data
    assert data.train["target_ts"].max() < fold.train_end - timedelta(days=7)
    assert data.valid["target_ts"].max() < fold.train_end
    assert (data.train["issued_at"].dt.minute == 0).all()
    assert data.valid["issued_at"].dt.minute.nunique() == 4  # every 15 min
    assert data.test["issued_at"].min() == fold.test_start


def test_score_fold_trains_ridge_and_lgbm(fold_data: tuple[Fold, object]) -> None:
    fold, data = fold_data
    cols = feature_columns()
    models = [
        Persistence(),
        SeasonalNaive7d(),
        RidgeForecaster(cols),
        LgbmQuantile(
            cols, [1, 2], n_estimators=40, early_stopping=10, params={"min_data_in_leaf": 5}
        ),
    ]
    outcome = score_fold(data, fold, 60, models, cols)
    summary = summarise(pd.DataFrame(outcome.metrics)).set_index("model_name")
    assert summary.loc["persistence", "mase"] == 1.0
    assert 0.0 <= summary.loc["lgbm_global", "coverage_80"] <= 1.0
    assert np.isnan(summary.loc["ridge", "coverage_80"])
    scored = outcome.scored
    assert (scored["p10_lgbm_global"] <= scored["pred_lgbm_global"]).all()
    assert (scored["pred_lgbm_global"] <= scored["p90_lgbm_global"]).all()
    assert scored["pred_lgbm_global"].between(0, 30).all()
