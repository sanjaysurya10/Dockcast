"""Neighbour sets and PRD 10.5 spatial features against hand-computed values."""

import numpy as np
import pandas as pd
import pytest

from dockcast.features.matrix import build_grid, feature_matrix, fit_station_hour_encoding
from dockcast.features.spatial import (
    haversine_m,
    neighbour_sets,
    spatial_columns,
    spatial_matrices,
)
from tests.unit.test_feature_matrix import CALENDAR
from tests.unit.test_targets_backtest import T0, make_panel

pytestmark = pytest.mark.unit

# Station 1 at the origin; 2 is ~111 m north, 3 ~222 m north, 4 ~1.1 km north.
INFO = pd.DataFrame(
    {
        "station_key": [1, 2, 3, 4],
        "lat": [53.340, 53.341, 53.342, 53.350],
        "lon": [-6.26, -6.26, -6.26, -6.26],
    }
)
STATIONS = np.array([1, 2, 3, 4])


def test_haversine_one_millidegree_of_latitude() -> None:
    dist = haversine_m(np.array([53.340, 53.341]), np.array([-6.26, -6.26]))
    assert dist[0, 1] == pytest.approx(111.2, abs=0.5)
    assert dist[0, 0] == 0.0


def test_neighbours_respect_radius_and_k() -> None:
    nb = neighbour_sets(STATIONS, INFO, k=1, radius_m=300)
    assert [list(i) for i in nb.index] == [[1], [0], [1], []]
    assert [sorted(w) for w in nb.within] == [[1, 2], [0, 2], [0, 1], []]
    assert spatial_columns(300) == [
        "nb300_ratio_mean",
        "nb300_change_4_mean",
        "nb300_zero_count",
        "nb300_bikes_total",
        "nb300_ratio_idw",
    ]


def test_spatial_values_by_hand() -> None:
    nb = neighbour_sets(STATIONS, INFO, k=5, radius_m=300)
    bikes = np.array(
        [
            [1.0, 2.0, 3.0, 9.0],
            [1.0, 2.0, 3.0, 9.0],
            [1.0, 2.0, 3.0, 9.0],
            [1.0, 2.0, 3.0, 9.0],
            [5.0, 0.0, np.nan, 9.0],
        ]
    )
    capacity = np.full_like(bikes, 10.0)
    m = spatial_matrices(bikes, capacity, nb)
    # Station 1 at the last row: neighbours 2 (0 bikes) and 3 (missing).
    assert m["ratio_mean"][4, 0] == pytest.approx(0.0)
    assert m["change_4_mean"][4, 0] == pytest.approx(-2.0)
    assert m["zero_count"][4, 0] == 1.0
    assert m["bikes_total"][4, 0] == 0.0
    # Station 2: neighbours 1 (111 m, ratio 0.5) and 3 (111 m, missing) -> 0.5.
    assert m["ratio_idw"][4, 1] == pytest.approx(0.5)
    # Station 1 in row 0: 2 at 111 m (0.2), 3 at 222 m (0.3); weights 1/d.
    d12, d13 = nb.distance_m[0]
    expected = (0.2 / d12 + 0.3 / d13) / (1 / d12 + 1 / d13)
    assert m["ratio_idw"][0, 0] == pytest.approx(expected)
    assert np.isnan(m["change_4_mean"][3, 0])  # no state an hour earlier
    assert np.isnan(m["ratio_mean"][:, 3]).all()  # isolated station


def test_feature_matrix_adds_spatial_columns_for_each_radius() -> None:
    panel = make_panel(stations=(1, 2, 3, 4))
    t = T0 + pd.Timedelta(days=8, hours=6)
    grid = build_grid(panel, [], t)
    nbs = [neighbour_sets(grid.stations, INFO, 5, r) for r in (150, 300)]
    rows = pd.DataFrame({"station_key": [1], "issued_at": [t]})
    enc = fit_station_hour_encoding(panel, t)
    f = feature_matrix(grid, rows, 60, CALENDAR, INFO, enc, nbs).iloc[0]
    state = panel.set_index(["station_key", "state_ts"])["bikes"]
    assert f["nb150_bikes_total"] == state[(2, t)]
    assert f["nb300_bikes_total"] == state[(2, t)] + state[(3, t)]
    assert f["nb300_ratio_mean"] == pytest.approx((state[(2, t)] + state[(3, t)]) / 60)
