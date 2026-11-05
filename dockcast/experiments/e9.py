"""E9 — rebalancing **simulation** (PRD 14 E9, RQ9, M19). Not an operational tool (NG2).

``make backtest E=E9``. Owner decisions 2026-11-05 (PRD 23):

- Demand is a replay: each station's observed 15-min net change in bikes, with the changes in
  rebalance-flagged buckets removed (no real operator), plus the simulated van moves, clipped at
  0 and capacity. A bucket at 0 bikes or at capacity is 15 stockout-minutes. Riders are assumed
  not to react to the moves, and net change understates real demand (no trip data).
- Fleet: vans of 20 bikes, one pickup -> dropoff move per van per hour, 06:00-22:00
  Europe/Dublin; travel is ignored. 2 vans by default, 1 and 4 as a sensitivity check.
- Forecasts: E1's 8 test weeks at +60, read from E1 run ``e4819616``'s saved predictions (the
  per-fold models E1 trained), so nothing is retrained. The ``persistence`` policy plans on the
  current simulated state; ``lgbm_global`` adds the P50's forecast change over the next hour.
- Objective: stockout-minutes avoided against no action, minus lambda x moves.

Writes MLflow (experiment ``E9``) and the E9 section of ``reports/experiments.md``.
"""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import structlog
from sqlalchemy.orm import Session

from dockcast.config import get_env_settings
from dockcast.db.engine import make_engine
from dockcast.evaluation.reports import (
    REPORTS,
    folds_json,
    generated_line,
    git_commit,
    replace_section,
)
from dockcast.evaluation.splits import Fold
from dockcast.experiments.e1 import default_folds
from dockcast.quality.gaps import load_gaps
from dockcast.targets.regression import BUCKET, load_panel
from dockcast.tracking import setup_mlflow

log = structlog.get_logger(job="e9")
EXPERIMENT = "E9"
E1_RUN = "e4819616d7034b90abcb3adc882313da"
HORIZON = 60
POLICIES = ("no_action", "persistence", "lgbm_global")
FLEETS = (1, 2, 4)
DEFAULT_VANS = 2
VAN_BIKES = 20
LOW = 2
FIRST_HOUR, LAST_HOUR = 6, 21
LAMBDAS = (0, 5, 10, 20)
LOCAL_TZ = "Europe/Dublin"
BUCKET_MIN = 15


@dataclass
class WeekGrid:
    """One test week on the 15-min grid: rows are state times, columns stations."""

    times: pd.DatetimeIndex
    stations: np.ndarray
    bikes: np.ndarray
    ok: np.ndarray
    flagged: np.ndarray
    capacity: np.ndarray
    forecast_change: np.ndarray


@dataclass(frozen=True)
class SimResult:
    """Totals for one policy over one week."""

    empty_min: int
    full_min: int
    moves: int
    bikes_moved: int
    clipped_bikes: float
    fallback_share: float

    @property
    def stockout_min(self) -> int:
        """Empty plus full minutes."""
        return self.empty_min + self.full_min


def week_grid(panel: pd.DataFrame, predictions: pd.DataFrame, fold: Fold) -> WeekGrid:
    """Pivot one test week's states and +60 forecasts to time x station arrays.

    Args:
        panel: ``load_panel`` rows covering the week.
        predictions: E1 +60 rows for this fold (``pred_persistence`` is the state at issue).
        fold: The test week.

    Returns:
        The week's grid; ``forecast_change`` is P50 minus the state at issue, NaN where E1 has
        no scored row.
    """
    times = pd.date_range(pd.Timestamp(fold.test_start), pd.Timestamp(fold.test_end), freq=BUCKET)
    week = panel[panel["state_ts"].between(times[0], times[-1])]
    stations = np.array(sorted(int(s) for s in week["station_key"].unique()))

    def grid(frame: pd.DataFrame, column: str, index: str = "state_ts") -> pd.DataFrame:
        return frame.pivot(index=index, columns="station_key", values=column).reindex(
            index=times, columns=stations
        )

    bikes = grid(week, "bikes")
    ok = grid(week.assign(ok=week["target_ok"].astype(float)), "ok").fillna(0.0).astype(bool)
    flagged = grid(week.assign(f=week["rebalance_flag"].astype(float)), "f").fillna(0.0)
    capacity = (
        week.groupby("station_key")["capacity"].median().reindex(stations)
        .fillna((week["bikes"] + week["docks"]).groupby(week["station_key"]).max())
    )  # fmt: skip
    capacity = capacity[capacity > 0]
    stations = capacity.index.to_numpy()
    change = predictions.assign(
        change=predictions["pred_lgbm_global"] - predictions["pred_persistence"]
    )
    return WeekGrid(
        times=times,
        stations=stations,
        bikes=bikes.to_numpy(dtype=float),
        ok=ok.to_numpy(),
        flagged=flagged.to_numpy().astype(bool),
        capacity=capacity.to_numpy(dtype=float),
        forecast_change=grid(change, "change", "issued_at").to_numpy(dtype=float),
    )


def replay_changes(grid: WeekGrid) -> np.ndarray:
    """Observed 15-min net change per station; 0 when an end is missing or the bucket is flagged.

    Row 0 is 0 (the week starts from the observed state).
    """
    change = np.zeros_like(grid.bikes)
    change[1:] = np.diff(grid.bikes, axis=0)
    change[np.isnan(change) | grid.flagged] = 0.0
    change[0] = 0.0
    return change


def decision_times(times: pd.DatetimeIndex) -> np.ndarray:
    """True on the hour from 06:00 to 21:00 Europe/Dublin (the last move ends by 22:00)."""
    local = times.tz_convert(LOCAL_TZ)
    hour = np.asarray(local.hour)
    return np.asarray(local.minute == 0) & (hour >= FIRST_HOUR) & (hour <= LAST_HOUR)


def initial_state(grid: WeekGrid) -> np.ndarray:
    """First observed bikes per station (0 for stations never observed this week)."""
    first = pd.DataFrame(grid.bikes).bfill().iloc[0].to_numpy(dtype=float)
    state: np.ndarray = np.nan_to_num(np.minimum(first, grid.capacity))
    return state


def _pick(mask: np.ndarray, score: np.ndarray, lowest: bool) -> int | None:
    if not mask.any():
        return None
    values = np.where(mask, score, np.inf if lowest else -np.inf)
    return int(np.argmin(values) if lowest else np.argmax(values))


def plan_moves(
    state: np.ndarray,
    expected_change: np.ndarray,
    capacity: np.ndarray,
    eligible: np.ndarray,
    vans: int,
    van_bikes: int = VAN_BIKES,
    low: int = LOW,
) -> list[tuple[int, int, int]]:
    """Greedy moves for one decision time: ``(donor, recipient, bikes)`` per van.

    A station is at risk when its expected bikes in an hour are ``<= low`` (empty) or
    ``>= capacity - low`` (full). Each van serves the most at-risk recipient and donor; when only
    one side is at risk, the other end is the station furthest past half full in the other
    direction. Each move brings both ends towards half full, and a station is visited at most
    once per decision time.

    Args:
        state: Simulated bikes now.
        expected_change: Forecast change over the next hour (0 for persistence).
        capacity: Docks per station.
        eligible: Stations open and observed now.
        vans: Number of vans.
        van_bikes: Bikes a van carries.
        low: Risk threshold in bikes.

    Returns:
        Planned moves, possibly fewer than ``vans``.
    """
    expected = np.clip(state + expected_change, 0.0, capacity)
    half = np.round(capacity / 2)
    free = eligible.copy()
    moves: list[tuple[int, int, int]] = []
    for _ in range(vans):
        empty_risk = free & (expected <= low)
        full_risk = free & (expected >= capacity - low)
        if not (empty_risk.any() or full_risk.any()):
            break
        recipient = _pick(empty_risk, expected, lowest=True)
        if recipient is None:
            recipient = _pick(free & (expected < half), expected / capacity, lowest=True)
        donor = _pick(full_risk, expected - capacity, lowest=False)
        if donor is None:
            donor = _pick(free & (expected > half), expected - half, lowest=False)
        if recipient is None or donor is None or recipient == donor:
            break
        bikes = int(
            np.floor(
                min(
                    van_bikes,
                    expected[donor] - half[donor],
                    half[recipient] - expected[recipient],
                    state[donor],
                    capacity[recipient] - state[recipient],
                )
            )
        )
        free[donor] = free[recipient] = False
        if bikes >= 1:
            moves.append((donor, recipient, bikes))
    return moves


def simulate(grid: WeekGrid, policy: str, vans: int) -> SimResult:
    """Replay one week under a policy.

    Each step adds the replayed change and clips to ``[0, capacity]``, then counts open stations
    at 0 or capacity, then (at decision times) applies the policy's moves.
    """
    change = replay_changes(grid)
    decide = decision_times(grid.times)
    state = initial_state(grid)
    capacity = grid.capacity
    empty = full = moves = moved = 0
    clipped = 0.0
    decisions = fallbacks = 0
    for t in range(len(grid.times)):
        if t > 0:
            raw = state + change[t]
            state = np.clip(raw, 0.0, capacity)
            clipped += float(np.abs(raw - state)[grid.ok[t]].sum())
        empty += int((grid.ok[t] & (state <= 0)).sum())
        full += int((grid.ok[t] & (state >= capacity)).sum())
        if policy == "no_action" or not decide[t]:
            continue
        expected = np.zeros_like(state)
        if policy == "lgbm_global":
            forecast = grid.forecast_change[t]
            missing = np.isnan(forecast) & grid.ok[t]
            decisions += int(grid.ok[t].sum())
            fallbacks += int(missing.sum())
            expected = np.nan_to_num(forecast)
        for donor, recipient, bikes in plan_moves(state, expected, capacity, grid.ok[t], vans):
            state[donor] -= bikes
            state[recipient] += bikes
            moves += 1
            moved += bikes
    return SimResult(
        empty_min=empty * BUCKET_MIN,
        full_min=full * BUCKET_MIN,
        moves=moves,
        bikes_moved=moved,
        clipped_bikes=clipped,
        fallback_share=fallbacks / decisions if decisions else 0.0,
    )


def observed_stockouts(grid: WeekGrid) -> tuple[int, int]:
    """Empty and full minutes in the real data (with the real operator), for reference."""
    bikes = np.nan_to_num(grid.bikes, nan=-1.0)
    empty = int((grid.ok & (bikes == 0)).sum()) * BUCKET_MIN
    full = int((grid.ok & (bikes >= grid.capacity)).sum()) * BUCKET_MIN
    return empty, full


def week_results(grid: WeekGrid, fold: int) -> list[dict[str, object]]:
    """Every policy and fleet size for one week, plus the observed reference row."""
    empty, full = observed_stockouts(grid)
    records: list[dict[str, object]] = [
        {"fold": fold, "policy": "observed", "vans": 0, "empty_min": empty, "full_min": full,
         "stockout_min": empty + full, "moves": 0, "bikes_moved": 0, "clipped_bikes": 0.0,
         "fallback_share": 0.0},
    ]  # fmt: skip
    for policy in POLICIES:
        for vans in (0,) if policy == "no_action" else FLEETS:
            result = simulate(grid, policy, vans)
            records.append(
                {
                    "fold": fold,
                    "policy": policy,
                    "vans": vans,
                    "empty_min": result.empty_min,
                    "full_min": result.full_min,
                    "stockout_min": result.stockout_min,
                    "moves": result.moves,
                    "bikes_moved": result.bikes_moved,
                    "clipped_bikes": result.clipped_bikes,
                    "fallback_share": result.fallback_share,
                }
            )
    return records


def objective(results: pd.DataFrame, lambdas: Sequence[int] = LAMBDAS) -> pd.DataFrame:
    """Per policy and fleet: mean weekly stockout-minutes avoided and ``avoided - lambda x moves``.

    Args:
        results: ``week_results`` rows for every fold.
        lambdas: Cost of one move in stockout-minutes.

    Returns:
        One row per simulated policy and fleet, with mean and std over weeks.
    """
    base = results[results["policy"] == "no_action"].set_index("fold")["stockout_min"]
    acted = results[~results["policy"].isin(["no_action", "observed"])].copy()
    acted["avoided"] = base.reindex(acted["fold"]).to_numpy() - acted["stockout_min"]
    for lam in lambdas:
        acted[f"net_l{lam}"] = acted["avoided"] - lam * acted["moves"]
    nets = [f"net_l{lam}" for lam in lambdas]
    columns = ["stockout_min", "avoided", "moves", "bikes_moved", *nets]
    grouped = acted.groupby(["policy", "vans"])
    out = grouped[columns].mean()
    out["avoided_std"] = grouped["avoided"].std()
    return out.reset_index()


def head_to_head(results: pd.DataFrame) -> pd.DataFrame:
    """Per fleet: weeks where the LightGBM policy has fewer stockout-minutes than persistence."""
    pivot = results[results["policy"].isin(["persistence", "lgbm_global"])].pivot_table(
        index=["vans", "fold"], columns="policy", values="stockout_min"
    )
    diff = pivot["persistence"] - pivot["lgbm_global"]
    return pd.DataFrame(
        {
            "weeks_better": (diff > 0).groupby(level="vans").sum(),
            "weeks_worse": (diff < 0).groupby(level="vans").sum(),
            "mean_gain_min": diff.groupby(level="vans").mean(),
        }
    )


def render_section(
    run_id: str, folds: Sequence[Fold], results: pd.DataFrame, n_stations: int
) -> str:
    """The E9 section of ``reports/experiments.md``."""
    means = results.groupby(["policy", "vans"])[
        ["empty_min", "full_min", "stockout_min", "moves", "bikes_moved", "clipped_bikes"]
    ].mean()
    table = objective(results)
    duel = head_to_head(results)
    fallback = results.loc[results["policy"] == "lgbm_global", "fallback_share"].mean()
    lines = [
        "## E9 — Rebalancing simulation (SIMULATION, +60, 8 weeks)",
        "",
        generated_line(run_id, folds[0].test_start, folds[-1].test_end),
        "",
        "**This is a simulation, not a measurement and not operator advice (PRD NG2).** "
        "Owner decisions 2026-11-05 (PRD 23). Demand is a replay: each station's observed "
        "15-min net change in bikes, with changes in rebalance-flagged buckets removed (no real "
        "operator), plus the simulated van moves, clipped at 0 and capacity. A bucket at 0 bikes "
        "or at capacity on an open station counts as 15 stockout-minutes. Riders are assumed not "
        "to react to the moves, and net change understates real demand (no trip data). "
        f"Vans carry {VAN_BIKES} bikes and make one pickup -> dropoff move per hour, "
        f"{FIRST_HOUR:02d}:00-{LAST_HOUR + 1:02d}:00 Europe/Dublin; travel is ignored. Greedy "
        f"policy: serve the station with the lowest expected bikes in an hour (<= {LOW}) and the "
        f"fullest (>= capacity - {LOW}), bringing both towards half full. `persistence` plans on "
        "the current simulated state; `lgbm_global` adds its P50 forecast change over the next "
        f"hour, from E1 run `{E1_RUN}` (same folds; nothing retrained). "
        f"{n_stations} stations; LightGBM fell back to persistence for "
        f"{fallback:.1%} of open-station decisions (no scored E1 row).",
        "",
        "Mean per test week (8 weeks):",
        "",
        "| policy | vans | empty min | full min | stockout min | moves | bikes moved "
        "| clipped bikes |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    order = [("observed", 0), ("no_action", 0)] + [
        (p, v) for p in ("persistence", "lgbm_global") for v in FLEETS
    ]
    for policy, vans in order:
        row = means.loc[[(policy, vans)]].iloc[0]
        label = "observed (real operator, not simulated)" if policy == "observed" else policy
        clipped = "—" if policy == "observed" else f"{row['clipped_bikes']:.0f}"
        lines.append(
            f"| {label} | {vans} | {row['empty_min']:.0f} | {row['full_min']:.0f} | "
            f"{row['stockout_min']:.0f} | {row['moves']:.0f} | {row['bikes_moved']:.0f} | "
            f"{clipped} |"
        )
    lam_cols = " | ".join(f"λ = {lam}" for lam in LAMBDAS)
    lines += [
        "",
        "Objective: stockout-minutes avoided against no action, minus λ x moves (λ in "
        "stockout-minutes per move). Mean per week; ± is the std of avoided minutes over weeks.",
        "",
        f"| policy | vans | avoided | ± | avoided per move | {lam_cols} |",
        "|---|---:|---:|---:|---:|" + "---:|" * len(LAMBDAS),
    ]
    for rec in table.sort_values(["vans", "policy"], ascending=[True, False]).to_dict("records"):
        nets = " | ".join(f"{float(rec[f'net_l{lam}']):.0f}" for lam in LAMBDAS)
        per_move = float(rec["avoided"]) / float(rec["moves"])
        lines.append(
            f"| {rec['policy']} | {rec['vans']} | {float(rec['avoided']):.0f} | "
            f"{float(rec['avoided_std']):.0f} | {per_move:.0f} | "
            f"{nets} |"
        )
    cost_share = (max(LAMBDAS) * table["moves"] / table["avoided"]).max()
    lines += [
        "",
        f"At λ = {max(LAMBDAS)} the move cost is at most {cost_share:.1%} of the minutes "
        "avoided, so the ranking does not depend on λ in this range. The minutes avoided per "
        "move are "
        "large because in a replay a delivered bike stays until the observed net change "
        "drains it; riders do not take the extra bikes. Read them as an upper bound on what "
        "a move achieves, and compare policies rather than trusting the absolute values.",
    ]
    lines += [
        "",
        "LightGBM-planned vs persistence-planned, same fleet (stockout-minutes per week):",
        "",
        "| vans | weeks LightGBM better | weeks worse | mean minutes saved |",
        "|---:|---:|---:|---:|",
    ]
    for fleet, counts in duel.iterrows():
        lines.append(
            f"| {fleet} | {int(counts['weeks_better'])}/{len(folds)} | "
            f"{int(counts['weeks_worse'])} | {float(counts['mean_gain_min']):+.0f} |"
        )
    lines.append("")
    return "\n".join(lines)


def load_predictions(path: Path) -> pd.DataFrame:
    """E1's +60 rows: station, issue time, fold, persistence and LightGBM P50."""
    frame = pd.read_parquet(
        path,
        columns=["station_key", "issued_at", "fold", "horizon_min", "pred_persistence",
                 "pred_lgbm_global"],
    )  # fmt: skip
    return frame[frame["horizon_min"] == HORIZON].drop(columns="horizon_min")


def run(predictions: pd.DataFrame, folds: Sequence[Fold]) -> tuple[pd.DataFrame, int]:
    """Simulate every week. Returns per-week results and the number of stations seen."""
    engine = make_engine()
    start = folds[0].test_start - BUCKET
    panel = load_panel(engine, start, folds[-1].test_end)
    records: list[dict[str, object]] = []
    stations: set[int] = set()
    for fold in folds:
        preds = predictions[predictions["fold"] == fold.fold]
        first = preds["issued_at"].min()
        if first != pd.Timestamp(fold.test_start):
            raise ValueError(f"fold {fold.fold}: E1 rows start {first}, fold {fold.test_start}")
        grid = week_grid(panel, preds, fold)
        stations.update(int(s) for s in grid.stations)
        records += week_results(grid, fold.fold)
        log.info("week_simulated", fold=fold.fold, stations=len(grid.stations))
    return pd.DataFrame(records), len(stations)


def main(argv: Sequence[str] | None = None) -> None:
    """``make backtest E=E9``."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, default=None)
    args = parser.parse_args(argv)
    path = args.predictions or (
        get_env_settings().data_dir / "processed" / f"e1_predictions_{E1_RUN}.parquet"
    )
    engine = make_engine()
    with Session(engine) as session:
        gaps = load_gaps(session)
    folds = default_folds(engine, gaps)
    setup_mlflow(EXPERIMENT)
    with mlflow.start_run(run_name="e9") as active:
        run_id = active.info.run_id
        mlflow.log_params(
            {
                "kind": "simulation",
                "policies": ",".join(POLICIES),
                "fleets": ",".join(map(str, FLEETS)),
                "van_bikes": VAN_BIKES,
                "risk_low": LOW,
                "hours_local": f"{FIRST_HOUR:02d}-{LAST_HOUR + 1:02d}",
                "lambdas": ",".join(map(str, LAMBDAS)),
                "horizon": HORIZON,
                "forecasts_from": E1_RUN,
                "n_folds": len(folds),
                "git_commit": git_commit(),
            }
        )
        mlflow.log_text(folds_json(folds), "folds.json")
        results, n_stations = run(load_predictions(path), folds)
        table = objective(results)
        for rec in table.to_dict("records"):
            key = f"{rec['policy']}_v{rec['vans']}"
            mlflow.log_metric(f"avoided_min_{key}", float(rec["avoided"]))
            mlflow.log_metric(f"moves_{key}", float(rec["moves"]))
        mlflow.log_text(results.to_csv(index=False), "results.csv")
    section = render_section(run_id, folds, results, n_stations)
    replace_section(REPORTS / "experiments.md", EXPERIMENT, section)
    log.info("e9_done", run_id=run_id, weeks=len(folds))


if __name__ == "__main__":
    main()
