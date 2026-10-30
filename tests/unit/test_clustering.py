"""E3 clustering helpers and profile reshaping."""

import numpy as np
import pandas as pd
import pytest

from dockcast.experiments.e3 import KScore, choose_k
from dockcast.features.station import profile_matrix
from dockcast.models.clustering import ari, fit_kmeans, fit_ward, order_labels, pairwise_ari

pytestmark = pytest.mark.unit
RNG = np.random.default_rng(3)


def three_groups(per_group: int = 10) -> pd.DataFrame:
    """Profiles from three well-separated occupancy levels."""
    centres = [0.1, 0.5, 0.9]
    rows = [c + RNG.normal(0, 0.02, 48) for c in centres for _ in range(per_group)]
    return pd.DataFrame(rows, index=pd.Index(range(1, 3 * per_group + 1), name="station_key"))


def test_order_labels_numbers_clusters_by_mean_occupancy() -> None:
    profiles = three_groups()
    raw = np.repeat([2, 0, 1], 10)
    labels = order_labels(profiles, raw)
    assert labels.tolist() == list(np.repeat([0, 1, 2], 10))


def test_kmeans_and_ward_recover_separated_groups() -> None:
    profiles = three_groups()
    expected = list(np.repeat([0, 1, 2], 10))
    assert fit_kmeans(profiles, 3).tolist() == expected
    assert fit_ward(profiles, 3).tolist() == expected


def test_ari_uses_shared_stations_and_ignores_label_names() -> None:
    first = pd.Series([0, 0, 1, 1, 2], index=[1, 2, 3, 4, 5])
    second = pd.Series([5, 5, 7, 7], index=[1, 2, 3, 4])
    score, shared = ari(first, second)
    assert score == pytest.approx(1.0)
    assert shared == 4
    assert pairwise_ari([first, second, first]) == [pytest.approx(1.0)] * 3


def test_profile_matrix_drops_stations_with_thin_cells() -> None:
    rows = [
        {"station_key": s, "day_type": d, "hour": h, "occupancy": 0.5, "n": n}
        for s, n in ((1, 30), (2, 30))
        for d in ("weekday", "weekend")
        for h in range(24)
    ]
    cells = pd.DataFrame(rows)
    cells.loc[(cells.station_key == 2) & (cells.hour == 3) & (cells.day_type == "weekend"), "n"] = 5
    wide = profile_matrix(cells, min_obs=20)
    assert wide.index.tolist() == [1]
    assert wide.columns[0] == "weekday_00" and wide.columns[-1] == "weekend_23"
    assert wide.shape == (1, 48)


def test_profile_matrix_drops_station_missing_a_cell() -> None:
    rows = [
        {"station_key": 1, "day_type": d, "hour": h, "occupancy": 0.5, "n": 30}
        for d in ("weekday", "weekend")
        for h in range(24)
        if not (d == "weekend" and h == 4)
    ]
    assert profile_matrix(pd.DataFrame(rows), min_obs=1).empty


def test_choose_k_by_silhouette_then_period_stability() -> None:
    scores = [
        KScore(3, 0.41, 1.0, 1.0, 0.6, 100, 0.9),
        KScore(4, 0.4104, 1.0, 1.0, 0.8, 100, 0.9),
        KScore(5, 0.30, 1.0, 1.0, 0.9, 100, 0.9),
    ]
    assert choose_k(scores) == 4
