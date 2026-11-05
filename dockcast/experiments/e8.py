"""E8 — drift and retraining over a year of weekly test windows (PRD 14 E8, RQ8, M18).

``make backtest E=E8``. 52 consecutive gap-free test weeks ending at the last complete month of
Format B (owner decision 2026-11-04: Format B only; Format A's 30-min grid and the 62-day hole
before Format B rule it out). At +60, three ways of keeping ``lgbm_global`` up to date:

- ``lgbm_fixed``: trained once before the first test week and never updated.
- ``lgbm_weekly``: retrained before every test week on all history (expanding window).
- ``lgbm_rolling12``: retrained before every test week on the last 12 weeks only.

Each scheme's station x hour encoding comes from the same data its model was trained on (frozen
for ``lgbm_fixed``, the 12-week window for ``lgbm_rolling12``). Features are the v1 set, LightGBM
defaults and early stopping on the last training week, as in E1. Persistence is the MASE
denominator.

Writes MLflow (experiment ``E8``), ``backtest_results``, the E8 section of
``reports/experiments.md`` and ``reports/figures/e8_drift.png``.
"""

import argparse
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Self

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import mlflow
import numpy as np
import pandas as pd
import structlog
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from dockcast.config import load_project_config
from dockcast.db.engine import make_engine
from dockcast.evaluation.backtest import FoldOutcome, add_slices, score_fold, summarise
from dockcast.evaluation.reports import (
    REPORTS,
    folds_json,
    generated_line,
    git_commit,
    replace_section,
    store_results,
)
from dockcast.evaluation.splits import Fold, last_complete_month_end, rolling_origin_folds
from dockcast.evaluation.training import (
    LOOKBACK,
    VALID_WINDOW,
    FoldData,
    hourly_issue_times,
)
from dockcast.experiments.e1 import b_span, reference_tables
from dockcast.experiments.e3 import GRID, INK, MUTED, SERIES, SURFACE
from dockcast.experiments.e4 import score_all
from dockcast.features.matrix import (
    StateGrid,
    build_grid,
    feature_columns,
    feature_matrix,
    fit_station_hour_encoding,
)
from dockcast.models.base import Forecaster
from dockcast.models.baselines import Persistence
from dockcast.models.lgbm_quantile import LgbmQuantile
from dockcast.quality.gaps import Gap, load_gaps
from dockcast.targets.regression import issue_times, load_panel, targets
from dockcast.tracking import setup_mlflow

log = structlog.get_logger(job="e8")
EXPERIMENT = "E8"
FIGURES = REPORTS / "figures"
HORIZON = 60
N_WEEKS = 52
ROLLING_WEEKS = 12
SCHEMES = ("lgbm_fixed", "lgbm_weekly", "lgbm_rolling12")
NAMES = ("persistence", *SCHEMES)


class SchemeModel:
    """``LgbmQuantile`` with its own station x hour encoding and optional training window.

    Args:
        name: Model name in the results.
        model: The wrapped forecaster.
        encoding: Station x hour encoding that replaces ``te_station_hour`` in every frame.
        train_from: Training rows with ``issued_at`` before this are dropped (rolling window).
        frozen: ``fit`` does nothing (the model was trained earlier).
    """

    is_point = False
    uses_validation = True

    def __init__(
        self,
        name: str,
        model: LgbmQuantile,
        encoding: pd.Series,
        train_from: pd.Timestamp | None = None,
        frozen: bool = False,
    ) -> None:
        """Wrap ``model`` with this scheme's encoding and window."""
        self.name = name
        self.model = model
        self.encoding = encoding
        self.train_from = train_from
        self.frozen = frozen

    def encode(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        """``X`` with ``te_station_hour`` looked up in this scheme's encoding."""
        keys = pd.MultiIndex.from_arrays([X["station_key"], X["hour_local"]])
        out = X.copy()
        out["te_station_hour"] = self.encoding.reindex(keys).to_numpy(dtype=float)
        return out

    def fit(
        self,
        X: pd.DataFrame,  # noqa: N803
        y: pd.Series,
        X_valid: pd.DataFrame | None = None,  # noqa: N803
        y_valid: pd.Series | None = None,
    ) -> Self:
        """Train on rows inside the window (no-op when frozen)."""
        if self.frozen:
            return self
        if self.train_from is not None:
            keep = X["issued_at"] >= self.train_from
            X, y = X[keep], y[keep]  # noqa: N806
        valid = None if X_valid is None else self.encode(X_valid)
        self.model.fit(self.encode(X), y, valid, y_valid)
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        """Quantiles from the wrapped model on re-encoded features."""
        return self.model.predict(self.encode(X))


def drift_folds(engine: Engine, gaps: Sequence[Gap], n_weeks: int = N_WEEKS) -> list[Fold]:
    """``n_weeks`` gap-free test weeks ending at the last complete month of Format B."""
    cfg = load_project_config().backtest
    lo, hi = b_span(engine)
    end = last_complete_month_end(hi, timedelta(minutes=30))
    return rolling_origin_folds(lo, end, gaps, n_weeks, cfg.test_window_days, cfg.gap_min)


def window_encoding(panel: pd.DataFrame, train_end: pd.Timestamp, weeks: int) -> pd.Series:
    """Station x hour encoding from states in the ``weeks`` weeks before ``train_end``."""
    start = train_end - timedelta(weeks=weeks)
    return fit_station_hour_encoding(panel[panel["state_ts"] >= start], train_end)


@dataclass
class WeekFeatures:
    """What every week shares: one state grid and the hourly training rows of all weeks."""

    panel: pd.DataFrame
    grid: StateGrid
    hourly: pd.DataFrame
    calendar: pd.DataFrame
    station_info: pd.DataFrame
    encoding: pd.Series

    def rows(self, times: pd.DatetimeIndex) -> pd.DataFrame:
        """Featurised rows for every station at ``times``."""
        rows = targets(self.panel, times, HORIZON)
        return feature_matrix(
            self.grid, rows, HORIZON, self.calendar, self.station_info, self.encoding
        )


def prepare_weeks(
    panel: pd.DataFrame,
    folds: Sequence[Fold],
    gaps: Sequence[Gap],
    calendar: pd.DataFrame,
    station_info: pd.DataFrame,
    data_start: datetime,
) -> WeekFeatures:
    """Build the grid and the hourly training rows once, for :func:`week_data` to slice.

    Every feature reads only states at or before its row's issue time (``tests/leakage``), so a
    row's features do not depend on the fold's cut-off and one grid serves all weeks. The
    station x hour encoding is a placeholder: each :class:`SchemeModel` replaces it. Hourly
    features are stored as float32 to fit in memory.
    """
    step = timedelta(minutes=15)
    grid = build_grid(panel, gaps, pd.Timestamp(max(f.test_end for f in folds)))
    encoding = fit_station_hour_encoding(panel, pd.Timestamp(folds[0].train_end))
    first = pd.Timestamp(data_start).tz_convert("UTC").ceil("h") + LOOKBACK
    shared = WeekFeatures(panel, grid, pd.DataFrame(), calendar, station_info, encoding)
    times = hourly_issue_times(first, folds[-1].train_end - VALID_WINDOW - step, HORIZON)
    hourly = shared.rows(times)
    hourly = hourly[hourly["target_ok"]].reset_index(drop=True)
    floats = [c for c in feature_columns() if hourly[c].dtype == "float64"]
    shared.hourly = hourly.astype(dict.fromkeys(floats, "float32"))
    return shared


def week_data(shared: WeekFeatures, fold: Fold) -> FoldData:
    """One week's train / valid / test rows, as :func:`prepare_fold` would build them."""
    step, horizon = timedelta(minutes=15), timedelta(minutes=HORIZON)
    train_end = pd.Timestamp(fold.train_end)
    valid_start = train_end - VALID_WINDOW
    hourly = shared.hourly
    train = hourly[hourly["issued_at"] <= valid_start - step - horizon]
    valid = shared.rows(issue_times(valid_start, fold.train_end - step, HORIZON))
    test = shared.rows(issue_times(fold.test_start, fold.test_end, HORIZON))
    return FoldData(
        train.reset_index(drop=True),
        valid[valid["target_ok"]].reset_index(drop=True),
        add_slices(test),
    )


def run(engine: Engine, folds: Sequence[Fold], gaps: Sequence[Gap]) -> list[FoldOutcome]:
    """Score the three schemes and persistence on every test week at :data:`HORIZON`."""
    data_start, _ = b_span(engine)
    calendar, info = reference_tables(engine)
    panel = load_panel(engine, data_start, max(f.test_end for f in folds))
    stations = sorted(int(s) for s in panel["station_key"].unique())
    started = time.monotonic()
    shared = prepare_weeks(panel, folds, gaps, calendar, info, data_start)
    log.info("features_built", hourly=len(shared.hourly), seconds=round(time.monotonic() - started))
    columns = feature_columns()
    fixed: SchemeModel | None = None
    outcomes: list[FoldOutcome] = []
    for fold in folds:
        started = time.monotonic()
        data = week_data(shared, fold)
        train_end = pd.Timestamp(fold.train_end)
        if fixed is None:
            fixed = SchemeModel(
                "lgbm_fixed",
                LgbmQuantile(columns, stations, num_threads=10),
                fit_station_hour_encoding(panel, train_end),
            )
        else:
            fixed.frozen = True
        models: list[Forecaster] = [
            Persistence(),
            fixed,
            SchemeModel(
                "lgbm_weekly",
                LgbmQuantile(columns, stations, num_threads=10),
                fit_station_hour_encoding(panel, train_end),
            ),
            SchemeModel(
                "lgbm_rolling12",
                LgbmQuantile(columns, stations, num_threads=10),
                window_encoding(panel, train_end, ROLLING_WEEKS),
                train_from=train_end - timedelta(weeks=ROLLING_WEEKS),
            ),
        ]
        outcome = score_fold(data, fold, HORIZON, models, [])
        outcome.scored["fold"], outcome.scored["horizon_min"] = fold.fold, HORIZON
        outcome.scored = outcome.scored[
            ["fold", "horizon_min", "y", "station", "overall", "hour", "dow", "weekend"]
            + ["rush_hour", "capacity_band", "rebalance"]
            + [
                c
                for c in map(str, outcome.scored.columns)
                if c.startswith(("pred_", "p10_", "p90_"))
            ]
        ]
        outcomes.append(outcome)
        log.info(
            "week_scored",
            fold=fold.fold,
            test_start=f"{fold.test_start:%Y-%m-%d}",
            common=outcome.rows_common,
            seconds=round(time.monotonic() - started),
        )
        del data
    return outcomes


def weekly_mae(results: pd.DataFrame, folds: Sequence[Fold]) -> pd.DataFrame:
    """Overall MAE per test week (rows) and model (columns), indexed by the week's start."""
    part = results[(results.slice_kind == "overall") & (results.slice_value == "all")]
    table = part.pivot_table(index="fold", columns="model_name", values="mae")
    starts = {f.fold: pd.Timestamp(f.test_start) for f in folds}
    table.index = pd.DatetimeIndex([starts[int(i)] for i in table.index], name="week_start")
    return table[[n for n in NAMES if n in table]]


def drift_summary(weekly: pd.DataFrame) -> pd.DataFrame:
    """Per scheme: mean MAE, weeks beating weekly retraining and the trend against it.

    ``trend_per_month`` is the least-squares slope of (scheme MAE - ``lgbm_weekly`` MAE) against
    weeks since the first test week, scaled to 4 weeks; positive means the scheme falls further
    behind weekly retraining as time passes.
    """
    weeks = np.arange(len(weekly), dtype=float)
    rows = []
    for name in weekly.columns:
        gap = weekly[name] - weekly["lgbm_weekly"]
        slope = float(np.polyfit(weeks, gap.to_numpy(dtype=float), 1)[0]) if len(weeks) > 1 else 0.0
        rows.append(
            {
                "model_name": name,
                "mae": float(weekly[name].mean()),
                "mae_first_13": float(weekly[name].iloc[:13].mean()),
                "mae_last_13": float(weekly[name].iloc[-13:].mean()),
                "gap_vs_weekly": float(gap.mean()),
                "weeks_better": int((gap < 0).sum()),
                "trend_per_month": slope * 4,
            }
        )
    return pd.DataFrame(rows)


def quarter_mae(weekly: pd.DataFrame) -> pd.DataFrame:
    """Mean weekly MAE per calendar quarter of the week start (rows) and model (columns)."""
    quarter = pd.DatetimeIndex(weekly.index).tz_convert(None).to_period("Q").astype(str)
    return weekly.groupby(quarter).mean()


def plot_drift(weekly: pd.DataFrame, path: Path) -> None:
    """MAE per test week for each scheme (top) and the gap to weekly retraining (bottom)."""
    fig, (top, bottom) = plt.subplots(
        2, 1, figsize=(10, 6.4), sharex=True, height_ratios=(3, 2), facecolor=SURFACE
    )
    x = pd.DatetimeIndex(weekly.index).tz_convert(None)
    colours = dict(zip(NAMES, [MUTED, SERIES[1], SERIES[0], SERIES[2]], strict=True))
    for name in weekly.columns:
        style = "--" if name == "persistence" else "-"
        top.plot(x, weekly[name], style, color=colours[name], lw=2, label=name)
    top.set_ylabel("MAE at +60 (bikes)", color=MUTED)
    top.legend(frameon=False, fontsize=8, ncol=4, loc="upper left", labelcolor=INK)
    for name in ("lgbm_fixed", "lgbm_rolling12"):
        bottom.plot(x, weekly[name] - weekly["lgbm_weekly"], color=colours[name], lw=2, label=name)
    bottom.axhline(0, color=SERIES[0], lw=1)
    bottom.set_ylabel("MAE - weekly retrain", color=MUTED)
    bottom.legend(frameon=False, fontsize=8, ncol=2, loc="upper left", labelcolor=INK)
    for ax in (top, bottom):
        ax.grid(axis="y", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(colors=MUTED, length=0)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(GRID)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


def render_section(
    run_id: str,
    folds: Sequence[Fold],
    results: pd.DataFrame,
    weekly: pd.DataFrame,
    drift: pd.DataFrame,
    quarters: pd.DataFrame,
) -> str:
    """The E8 section of ``reports/experiments.md``."""
    summary = summarise(results).set_index("model_name")
    n = len(folds)
    lines = [
        "## E8 — Drift and retraining (+60, 52 weeks)",
        "",
        generated_line(run_id, folds[0].test_start, folds[-1].test_end),
        "",
        f"{n} gap-free test weeks, {folds[0].test_start:%Y-%m-%d} → "
        f"{folds[-1].test_end:%Y-%m-%d}, Format B only (owner decision 2026-11-04: Format A's "
        "30-min grid and the 62-day hole before Format B rule it out). `lgbm_global` with the v1 "
        "features, LightGBM defaults and early stopping on the last training week, kept up to "
        "date three ways: `lgbm_fixed` is trained once before the first test week "
        f"(training end {folds[0].train_end:%Y-%m-%d %H:%M} UTC) and never updated; "
        "`lgbm_weekly` is retrained before every week on all earlier data; `lgbm_rolling12` is "
        f"retrained before every week on the last {ROLLING_WEEKS} weeks only. Each scheme's "
        "station x hour encoding comes from the data its model was trained on. Persistence is "
        "the MASE denominator. **No weather.** Every model is scored on the same rows.",
        "",
        "| model | MAE | ± (weeks) | MASE | coverage P10-P90 | width | rows |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in NAMES:
        rec = summary.loc[name]
        cov: str = "—" if pd.isna(rec["coverage_80"]) else f"{float(rec['coverage_80']):.3f}"
        width: str = (
            "—" if pd.isna(rec["interval_width"]) else f"{float(rec['interval_width']):.2f}"
        )
        lines.append(
            f"| {name} | {float(rec['mae']):.3f} | {float(rec['mae_std']):.3f} | "
            f"{float(rec['mase']):.3f} | {cov} | {width} | {int(rec['n'])} |"
        )
    lines += [
        "",
        "Against weekly retraining (gap = scheme MAE - `lgbm_weekly` MAE; trend = slope of the "
        "gap per 4 weeks since the first test week, positive = falling further behind):",
        "",
        "| model | MAE first 13 weeks | MAE last 13 weeks | mean gap | weeks better than weekly "
        "| trend per 4 weeks |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for record in drift[drift.model_name != "lgbm_weekly"].to_dict("records"):
        lines.append(
            f"| {record['model_name']} | {record['mae_first_13']:.3f} | "
            f"{record['mae_last_13']:.3f} | "
            f"{record['gap_vs_weekly']:+.3f} | {record['weeks_better']}/{n} | "
            f"{record['trend_per_month']:+.4f} |"
        )
    lines += [
        "",
        "![MAE per test week and the gap to weekly retraining](figures/e8_drift.png)",
        "",
        "Mean weekly MAE by quarter of the test week:",
        "",
        "| quarter | " + " | ".join(quarters.columns) + " |",
        "|---|" + "---:|" * len(quarters.columns),
    ]
    for quarter, values in quarters.iterrows():
        lines.append(f"| {quarter} | " + " | ".join(f"{v:.3f}" for v in values) + " |")
    worst = weekly["lgbm_weekly"].idxmax()
    lines += [
        "",
        f"Hardest week for `lgbm_weekly`: {worst:%Y-%m-%d} (MAE "
        f"{float(weekly['lgbm_weekly'].max()):.3f}); easiest: "
        f"{weekly['lgbm_weekly'].idxmin():%Y-%m-%d} "
        f"(MAE {float(weekly['lgbm_weekly'].min()):.3f}). "
        "Fold dates are in the run's `folds.json` artifact.",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    """``make backtest E=E8`` (``--weeks N`` for timing runs: the last N weeks, no report)."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--weeks", type=int, default=None)
    args = parser.parse_args(argv)
    engine = make_engine()
    with Session(engine) as session:
        gaps = load_gaps(session)
    folds = drift_folds(engine, gaps)
    if args.weeks:
        folds = folds[-args.weeks :]
    setup_mlflow(EXPERIMENT)
    with mlflow.start_run(run_name="e8") as active:
        run_id = active.info.run_id
        mlflow.log_params(
            {
                "models": ",".join(NAMES),
                "horizons": str(HORIZON),
                "n_folds": len(folds),
                "rolling_weeks": ROLLING_WEEKS,
                "fixed_train_end": f"{folds[0].train_end:%Y-%m-%d %H:%M}",
                "weather": "none",
                "git_commit": git_commit(),
                "data_source": "hist_b",
            }
        )
        mlflow.log_text(folds_json(folds), "folds.json")
        outcomes = run(engine, folds, gaps)
        scored = pd.concat([o.scored for o in outcomes], ignore_index=True)
        results = score_all(scored, list(NAMES), extra=())
        weekly = weekly_mae(results, folds)
        drift = drift_summary(weekly)
        for rec in summarise(results).to_dict("records"):
            mlflow.log_metric(f"mae_{rec['model_name']}_h{HORIZON}", float(rec["mae"]))
        for rec in drift.to_dict("records"):
            mlflow.log_metric(f"gap_vs_weekly_{rec['model_name']}", rec["gap_vs_weekly"])
            mlflow.log_metric(f"trend_per_month_{rec['model_name']}", rec["trend_per_month"])
        mlflow.log_metric("rows_scored", len(scored))
        mlflow.log_text(results.to_csv(index=False), "results.csv")
        mlflow.log_text(weekly.to_csv(), "weekly_mae.csv")
        stored = store_results(engine, run_id, EXPERIMENT, results)
    if args.weeks is None:
        plot_drift(weekly, FIGURES / "e8_drift.png")
        section = render_section(run_id, folds, results, weekly, drift, quarter_mae(weekly))
        replace_section(REPORTS / "experiments.md", EXPERIMENT, section)
    log.info("e8_done", run_id=run_id, rows=len(scored), results_rows=stored)


if __name__ == "__main__":
    main()
