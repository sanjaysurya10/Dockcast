"""E9 rebalancing simulation: replay, decision times, greedy moves, objective and report."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from dockcast.evaluation.splits import Fold
from dockcast.experiments.e9 import (
    WeekGrid,
    decision_times,
    objective,
    plan_moves,
    render_section,
    replay_changes,
    simulate,
    week_grid,
    week_results,
)

pytestmark = pytest.mark.unit


def make_grid(
    bikes: list[list[float]],
    capacity: list[float],
    start: str = "2026-05-06 05:00",
    forecast: list[list[float]] | None = None,
) -> WeekGrid:
    values = np.array(bikes, dtype=float)
    times = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=len(values), freq="15min")
    return WeekGrid(
        times=times,
        stations=np.arange(values.shape[1]),
        bikes=values,
        ok=~np.isnan(values),
        flagged=np.zeros(values.shape, dtype=bool),
        capacity=np.array(capacity, dtype=float),
        forecast_change=(
            np.full(values.shape, np.nan) if forecast is None else np.array(forecast, dtype=float)
        ),
    )


def test_replay_drops_flagged_and_missing_changes() -> None:
    grid = make_grid([[5, 5], [3, np.nan], [12, 6], [10, 4]], [20, 20])
    grid.flagged[2, 0] = True  # the +9 jump is the real operator's van
    change = replay_changes(grid)
    assert change[:, 0].tolist() == [0, -2, 0, -2]
    assert change[:, 1].tolist() == [0, 0, 0, -2]  # both ends needed


@pytest.mark.parametrize(
    ("day", "first_utc"),
    [("2026-03-29", "05:00"), ("2026-10-25", "06:00"), ("2026-03-28", "06:00")],
)
def test_decisions_follow_dublin_local_time_across_dst(day: str, first_utc: str) -> None:
    times = pd.date_range(pd.Timestamp(day, tz="UTC"), periods=96, freq="15min")
    decided = times[decision_times(times)]
    assert len(decided) == 16  # 06:00 to 21:00 local, hourly
    assert f"{decided[0]:%H:%M}" == first_utc


def test_greedy_move_takes_from_the_fullest_to_the_emptiest() -> None:
    state = np.array([1.0, 19.0, 10.0, 18.0])
    capacity = np.full(4, 20.0)
    moves = plan_moves(state, np.zeros(4), capacity, np.ones(4, dtype=bool), vans=2)
    assert moves[0] == (1, 0, 9)  # 19 -> 10 and 1 -> 10
    assert len(moves) == 1  # station 3 is at 18 = capacity - 2, but no free recipient below half


def test_greedy_respects_van_size_eligibility_and_no_risk() -> None:
    state = np.array([0.0, 40.0, 0.0])
    capacity = np.array([40.0, 40.0, 40.0])
    eligible = np.array([True, True, False])
    moves = plan_moves(state, np.zeros(3), capacity, eligible, vans=4, van_bikes=15)
    assert moves == [(1, 0, 15)]
    calm = plan_moves(np.full(3, 20.0), np.zeros(3), capacity, np.ones(3, dtype=bool), vans=2)
    assert calm == []


def test_forecast_change_lets_the_policy_act_before_the_stockout() -> None:
    state = np.array([6.0, 12.0])
    capacity = np.full(2, 20.0)
    eligible = np.ones(2, dtype=bool)
    assert plan_moves(state, np.zeros(2), capacity, eligible, vans=1) == []
    assert plan_moves(state, np.array([-5.0, 0.0]), capacity, eligible, vans=1) == [(1, 0, 2)]


def test_simulation_replays_and_counts_stockout_minutes() -> None:
    # Station 0 drains by 2 bikes every 15 min from 06:00 local (05:00 UTC); station 1 is full.
    drain = [[8 - 2 * i, 20] for i in range(6)]
    grid = make_grid(drain, [20, 20])
    idle = simulate(grid, "no_action", 0)
    assert (idle.empty_min, idle.full_min) == (2 * 15, 6 * 15)  # 0 at steps 4 and 5
    assert idle.clipped_bikes == 2.0  # step 5 wanted -2 from 0
    acted = simulate(grid, "persistence", 1)
    # 06:00 local: 2 bikes (8 -> half = 10); 07:00 local: station 0 is at 2 again, 8 bikes.
    assert (acted.moves, acted.bikes_moved) == (2, 10)
    assert acted.stockout_min == 15  # only the full bucket before the move
    forecast = [[-8, 0]] + [[np.nan, np.nan]] * 5
    lgbm = simulate(make_grid(drain, [20, 20], forecast=forecast), "lgbm_global", 1)
    # Foreseeing -8, one move fills station 0 to half at once (10 bikes); no row at 07:00.
    assert (lgbm.moves, lgbm.bikes_moved, lgbm.fallback_share) == (1, 10, 0.5)


def test_objective_and_section() -> None:
    drain = [[8 - 2 * i, 20] for i in range(6)]
    grid = make_grid(drain, [20, 20])
    results = pd.DataFrame(week_results(grid, 1) + week_results(grid, 2))
    table = objective(results, lambdas=(0, 10)).set_index(["policy", "vans"])
    assert table.loc[("persistence", 1), "avoided"] == 105  # 120 -> 15
    assert table.loc[("persistence", 1), "net_l10"] == 85  # 2 moves
    when = datetime(2026, 5, 6, 5, tzinfo=UTC)
    folds = [Fold(1, when, when, when + timedelta(hours=1)), Fold(2, when, when, when)]
    text = render_section("run", folds, results, 2)
    assert "## E9 — Rebalancing simulation (SIMULATION" in text
    assert "| observed (real operator, not simulated) | 0 |" in text
    assert "| 1 | 0/2 | 0 | +0 |" in text


def test_week_grid_pivots_states_and_forecast_change() -> None:
    start = pd.Timestamp("2026-05-06 05:00", tz="UTC")
    ts = pd.date_range(start, periods=3, freq="15min")
    panel = pd.DataFrame(
        {
            "station_key": [7] * 3 + [9] * 3,
            "state_ts": list(ts) * 2,
            "bikes": [4.0, 3.0, 2.0, 10.0, 11.0, 12.0],
            "docks": [16.0, 17.0, 18.0, 10.0, 9.0, 8.0],
            "target_ok": [True, True, False, True, True, True],
            "rebalance_flag": [False, False, False, False, True, False],
            "capacity": [20.0] * 3 + [np.nan] * 3,
        }
    )
    preds = pd.DataFrame(
        {
            "station_key": [7],
            "issued_at": [start],
            "pred_persistence": [4.0],
            "pred_lgbm_global": [1.5],
        }
    )
    grid = week_grid(panel, preds, Fold(1, start, start, ts[-1].to_pydatetime()))
    assert grid.stations.tolist() == [7, 9]
    assert grid.capacity.tolist() == [20.0, 20.0]  # station 9 from bikes + docks
    assert grid.ok[:, 0].tolist() == [True, True, False]
    assert grid.flagged[:, 1].tolist() == [False, True, False]
    assert grid.forecast_change[0, 0] == -2.5
    assert np.isnan(grid.forecast_change[0, 1])
