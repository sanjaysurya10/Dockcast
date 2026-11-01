import numpy as np
import pandas as pd
import pytest

from dockcast.evaluation.training import prepare_training
from dockcast.features.registry import FEATURE_GROUPS
from dockcast.serving.bundle import Bundle
from dockcast.serving.drivers import OTHER_GROUP, STATION_GROUP, driver_rows, grouped_contributions
from dockcast.serving.forecast import predict_with_drivers
from tests.unit.test_models_m4 import CAL, INFO
from tests.unit.test_serving import bundle  # noqa: F401  (fixture)
from tests.unit.test_targets_backtest import T0, make_panel

pytestmark = pytest.mark.unit


def test_contributions_sum_to_the_raw_median(bundle: Bundle) -> None:  # noqa: F811
    panel = make_panel(days=20)
    end = (T0 + pd.Timedelta(days=19)).to_pydatetime()
    _, valid, _ = prepare_training(panel, end, 60, [], CAL, INFO, T0)
    model = bundle.models[60]
    contrib = model.contributions(valid)
    assert np.allclose(contrib.sum(axis=1), model.predict(valid)["p50"], atol=1e-6)
    grouped = grouped_contributions(contrib)
    assert set(grouped.columns) <= {*FEATURE_GROUPS, STATION_GROUP, OTHER_GROUP}
    expected = contrib.drop(columns="expected_value").sum(axis=1)
    assert np.allclose(grouped.sum(axis=1), expected)


def test_grouping_maps_unknown_features_to_other() -> None:
    contrib = pd.DataFrame(
        {"bikes_now": [1.0], "change_1": [0.5], "dow": [-0.2], "station_key": [0.3],
         "nbr_ratio_mean": [0.1], "expected_value": [9.0]}
    )  # fmt: skip
    grouped = grouped_contributions(contrib).iloc[0].to_dict()
    assert grouped == pytest.approx(
        {"lags": 1.5, "calendar": -0.2, STATION_GROUP: 0.3, OTHER_GROUP: 0.1}
    )
    rows = driver_rows(grouped_contributions(contrib), pd.Series([7]), pd.Timestamp(T0), 60)
    assert set(rows.columns) == {
        "station_key", "feature_group", "contribution", "issued_at", "horizon_min"
    }  # fmt: skip
    assert len(rows) == 4 and (rows["station_key"] == 7).all()


def test_forecast_cycle_returns_drivers_for_every_forecast_row(bundle: Bundle) -> None:  # noqa: F811
    panel = make_panel(days=24)
    stations = pd.DataFrame({"station_key": [1, 2], "source_id": ["A", "B"],
                             "lat": [53.34, 53.35], "lon": [-6.26, -6.27]})  # fmt: skip
    issued = T0 + pd.Timedelta(days=22)
    forecasts, drivers = predict_with_drivers(bundle, panel, stations, CAL, issued)
    keys = forecasts[["station_key", "horizon_min"]].drop_duplicates()
    explained = drivers[["station_key", "horizon_min"]].drop_duplicates()
    assert len(keys.merge(explained)) == len(keys)
    assert (drivers["issued_at"] == issued).all()
