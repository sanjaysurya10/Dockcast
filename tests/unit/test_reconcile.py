import pytest

from dockcast.ingest.historical.reconcile import (
    KnownStation,
    haversine_m,
    normalise_name,
    reconcile,
)

pytestmark = pytest.mark.unit

# Coordinates from the live feed / format A for Clarendon Row and Blessington Street.
KNOWN = [
    KnownStation(10, "1", "CLARENDON ROW", 53.340927, -6.262501),
    KnownStation(11, "2", "BLESSINGTON STREET", 53.3568, -6.26814),
]


def test_haversine_one_millidegree_latitude() -> None:
    assert haversine_m(53.0, -6.0, 53.001, -6.0) == pytest.approx(111.2, abs=0.5)


def test_normalise_name() -> None:
    assert normalise_name("Sir Patrick's  Dun") == "SIR PATRICK S DUN"


def test_exact_id_match() -> None:
    match = reconcile("1", "CLARENDON ROW", 53.340927, -6.262501, KNOWN)
    assert (match.station_key, match.method, match.warning) == (10, "exact", None)


def test_exact_id_far_away_warns() -> None:
    match = reconcile("1", "CLARENDON ROW", 53.35, -6.262501, KNOWN)
    assert match.method == "exact" and match.warning is not None


def test_name_and_coords_match_within_30m() -> None:
    match = reconcile("99", "Blessington Street", 53.35681, -6.26814, KNOWN)
    assert (match.station_key, match.method) == (11, "name+coords")


def test_same_name_too_far_is_new() -> None:
    match = reconcile("99", "BLESSINGTON STREET", 53.3578, -6.26814, KNOWN)
    assert match.station_key is None and match.method == "new" and match.warning
