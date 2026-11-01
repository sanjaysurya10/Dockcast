import pytest

from dockcast.api import risk

pytestmark = pytest.mark.unit


def test_empty_levels_follow_p50_then_p10() -> None:
    assert risk.empty_level(p10=0.0, p50=0.4) == "likely"
    assert risk.empty_level(p10=0.5, p50=3.0) == "possible"
    assert risk.empty_level(p10=0.6, p50=3.0) == "low"


def test_full_levels_use_free_docks() -> None:
    assert risk.full_level(p50=29.6, p90=30.0, capacity=30) == "likely"
    assert risk.full_level(p50=25.0, p90=29.5, capacity=30) == "possible"
    assert risk.full_level(p50=25.0, p90=29.0, capacity=30) == "low"


def test_eta_is_the_first_horizon_at_empty_or_full() -> None:
    rows = [
        {"horizon_min": 120, "bikes_p50": 0.0},
        {"horizon_min": 30, "bikes_p50": 4.0},
        {"horizon_min": 60, "bikes_p50": 0.5},
    ]
    assert risk.eta_min(rows, "empty", 20) == 60
    assert risk.eta_min(rows, "full", 20) is None
    assert risk.eta_min([{"horizon_min": 30, "bikes_p50": 19.8}], "full", 20) == 30


def test_rank_key_orders_by_level_then_margin() -> None:
    keys = sorted(
        [
            risk.rank_key("low", 0.9, 20, "empty"),
            risk.rank_key("likely", 0.3, 20, "empty"),
            risk.rank_key("possible", 2.0, 20, "empty"),
            risk.rank_key("likely", 0.1, 20, "empty"),
        ]
    )
    assert keys == [(0, 0.1), (0, 0.3), (1, 2.0), (2, 0.9)]
    assert risk.rank_key("likely", 19.9, 20, "full") == (0, pytest.approx(0.1))
