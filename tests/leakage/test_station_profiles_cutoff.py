"""E3 profiles and cluster labels read nothing at or after the cutoff (PRD 10.1, 19.2)."""

from datetime import timedelta

import pandas as pd
import pytest
from sqlalchemy import Engine

from dockcast.features.station import load_profile_cells, profile_matrix
from dockcast.models.clustering import fit_kmeans
from tests.integration.test_station_profiles import START, grid_rows, insert_buckets, seed_stations

pytestmark = [pytest.mark.leakage, pytest.mark.integration]
CUTOFF = START + timedelta(days=9, hours=21, minutes=45)


def _profiles(engine: Engine) -> pd.DataFrame:
    return profile_matrix(load_profile_cells(engine, START, CUTOFF), min_obs=1)


def test_profiles_and_labels_identical_when_data_from_cutoff_changes(db_engine: Engine) -> None:
    keys = seed_stations(db_engine)
    insert_buckets(db_engine, grid_rows(keys, START, START + timedelta(days=14)))
    before = _profiles(db_engine)
    labels_before = fit_kmeans(before, 2)

    # The bucket whose state time equals the cutoff, and everything after it, changes.
    later = grid_rows(keys, CUTOFF - timedelta(minutes=15), START + timedelta(days=21))
    insert_buckets(db_engine, [{**r, "bikes": 20.0} for r in later])
    after = _profiles(db_engine)

    pd.testing.assert_frame_equal(before, after)
    pd.testing.assert_series_equal(labels_before, fit_kmeans(after, 2))


def test_last_state_before_cutoff_is_read(db_engine: Engine) -> None:
    keys = seed_stations(db_engine)
    insert_buckets(db_engine, grid_rows(keys, START, START + timedelta(days=14)))
    before = _profiles(db_engine)
    last = CUTOFF - timedelta(minutes=30)  # state at cutoff - 15 min
    insert_buckets(db_engine, [{"station_key": keys[0], "ts": last, "bikes": 20.0}])
    assert not before.equals(_profiles(db_engine))
