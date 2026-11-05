"""E8 retraining schemes, drift summary and the report."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from dockcast.evaluation.splits import Fold
from dockcast.experiments.e8 import (
    SchemeModel,
    drift_summary,
    plot_drift,
    quarter_mae,
    render_section,
    weekly_mae,
    window_encoding,
)

pytestmark = pytest.mark.unit


class Recorder:
    """Stand-in for ``LgbmQuantile`` that records what it was trained and asked on."""

    def __init__(self) -> None:
        self.fitted: pd.DataFrame | None = None
        self.valid: pd.DataFrame | None = None

    def fit(
        self,
        X: pd.DataFrame,  # noqa: N803
        y: pd.Series,
        X_valid: pd.DataFrame | None = None,  # noqa: N803
        y_valid: pd.Series | None = None,
    ) -> "Recorder":
        self.fitted, self.valid = X, X_valid
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        return pd.DataFrame({q: X["te_station_hour"] for q in ("p10", "p50", "p90")})


def rows(issued: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "station_key": [1] * len(issued),
            "hour_local": [8] * len(issued),
            "issued_at": pd.to_datetime(issued, utc=True),
            "te_station_hour": 0.99,
        }
    )


def test_scheme_model_uses_its_own_encoding_and_window() -> None:
    encoding = pd.Series([0.25], index=pd.MultiIndex.from_tuples([(1, 8)]))
    inner = Recorder()
    model = SchemeModel(
        "lgbm_rolling12",
        inner,  # type: ignore[arg-type]
        encoding,
        train_from=pd.Timestamp("2026-03-01", tz="UTC"),
    )
    train = rows(["2026-01-01 08:00", "2026-03-02 08:00"])
    model.fit(train, pd.Series([1.0, 2.0]), rows(["2026-03-20 08:00"]), pd.Series([3.0]))
    assert inner.fitted is not None and len(inner.fitted) == 1  # older row dropped
    assert inner.fitted["te_station_hour"].tolist() == [0.25]
    assert inner.valid is not None and inner.valid["te_station_hour"].tolist() == [0.25]
    assert model.predict(rows(["2026-04-01 08:00"]))["p50"].tolist() == [0.25]


def test_frozen_scheme_does_not_retrain() -> None:
    inner = Recorder()
    model = SchemeModel("lgbm_fixed", inner, pd.Series(dtype=float), frozen=True)  # type: ignore[arg-type]
    model.fit(rows(["2026-01-01 08:00"]), pd.Series([1.0]))
    assert inner.fitted is None


def test_window_encoding_reads_only_the_last_weeks_before_train_end() -> None:
    ts = pd.to_datetime(
        ["2026-01-05 08:00", "2026-03-20 08:00", "2026-03-27 08:00", "2026-04-02 08:00"], utc=True
    )
    panel = pd.DataFrame(
        {"station_key": 1, "state_ts": ts, "bikes": [30.0, 10.0, 20.0, 0.0], "capacity": 40.0}
    )
    encoding = window_encoding(panel, pd.Timestamp("2026-04-01", tz="UTC"), weeks=4)
    assert encoding.to_dict() == {(1, 8): pytest.approx(0.375)}  # (10 + 20) / 2 / 40


def test_weeks_sliced_from_one_build_match_prepare_fold() -> None:
    from dockcast.evaluation.backtest import add_slices
    from dockcast.evaluation.training import prepare_fold
    from dockcast.experiments.e8 import HORIZON, prepare_weeks, week_data
    from tests.unit.test_models_m4 import CAL, INFO
    from tests.unit.test_targets_backtest import T0, make_panel

    panel = make_panel(days=30)
    start = (T0 + pd.Timedelta(days=16)).to_pydatetime()
    gap = timedelta(minutes=120)
    folds = [
        Fold(i + 1, s - gap, s, s + timedelta(days=4))
        for i, s in enumerate((start, start + timedelta(days=5), start + timedelta(days=10)))
    ]
    shared = prepare_weeks(panel, folds, [], CAL, INFO, T0.to_pydatetime())
    for fold in folds:
        sliced = week_data(shared, fold)
        expected = prepare_fold(
            panel[panel["state_ts"] <= pd.Timestamp(fold.test_end)],
            fold,
            HORIZON,
            [],
            CAL,
            INFO,
            T0.to_pydatetime(),
        )
        for part in ("train", "valid", "test"):
            ours = getattr(sliced, part).drop(columns="te_station_hour")
            if part != "test":  # slice columns are only needed for scoring; models read floats
                ours = add_slices(ours)
            theirs = getattr(expected, part).drop(columns="te_station_hour")[ours.columns]
            pd.testing.assert_frame_equal(ours, theirs, check_dtype=False)


def weekly_frame() -> tuple[pd.DataFrame, list[Fold]]:
    start = datetime(2025, 7, 2, tzinfo=UTC)
    folds = [
        Fold(i + 1, start + timedelta(weeks=i), start + timedelta(weeks=i), start)
        for i in range(26)
    ]
    records = []
    for fold in folds:
        week = fold.fold - 1
        for name, mae in (
            ("persistence", 1.5),
            ("lgbm_fixed", 1.0 + 0.01 * week),
            ("lgbm_weekly", 1.0),
            ("lgbm_rolling12", 1.05),
        ):
            records.append(
                {
                    "model_name": name,
                    "fold": fold.fold,
                    "slice_kind": "overall",
                    "slice_value": "all",
                    "mae": mae,
                }
            )
    return weekly_mae(pd.DataFrame(records), folds), folds


def test_drift_summary_measures_the_gap_and_its_trend() -> None:
    weekly, _ = weekly_frame()
    assert list(weekly.columns) == ["persistence", "lgbm_fixed", "lgbm_weekly", "lgbm_rolling12"]
    drift = drift_summary(weekly).set_index("model_name")
    assert drift.loc["lgbm_fixed", "trend_per_month"] == pytest.approx(0.04)
    assert drift.loc["lgbm_fixed", "gap_vs_weekly"] == pytest.approx(0.125)
    assert drift.loc["lgbm_rolling12", "weeks_better"] == 0
    assert drift.loc["lgbm_rolling12", "trend_per_month"] == pytest.approx(0.0)
    quarters = quarter_mae(weekly)
    assert list(quarters.index) == ["2025Q3", "2025Q4"]


def test_section_and_chart(tmp_path: Path) -> None:
    from dockcast.evaluation.backtest import add_slices
    from dockcast.experiments.e4 import score_all

    names = ["persistence", "lgbm_fixed", "lgbm_weekly", "lgbm_rolling12"]
    t = pd.Timestamp("2025-07-02 08:00", tz="UTC")
    frames = []
    for fold in (1, 2):
        part = pd.DataFrame(
            {
                "station_key": [1, 2],
                "target_ts": [t, t],
                "capacity": 30.0,
                "rebalance_flag": False,
                "y": [10.0, 5.0],
                "fold": fold,
                "horizon_min": 60,
            }
        )
        for name, err in zip(names, (2.0, 0.5 * fold, 0.5, 0.6), strict=True):
            part[f"pred_{name}"] = part["y"] + err
            part[f"p10_{name}"] = part[f"pred_{name}"] - 1
            part[f"p90_{name}"] = part[f"pred_{name}"] + 1
        frames.append(add_slices(part))
    results = score_all(pd.concat(frames), names, extra=())
    when = datetime(2025, 7, 2, tzinfo=UTC)
    folds = [Fold(1, when, when, when + timedelta(weeks=1)), Fold(2, when, when, when)]
    folds[1] = Fold(2, when, when + timedelta(weeks=1), when + timedelta(weeks=2))
    weekly = weekly_mae(results, folds)
    text = render_section("run", folds, results, weekly, drift_summary(weekly), quarter_mae(weekly))
    assert "## E8 — Drift and retraining" in text
    assert "| lgbm_fixed | 0.750 | 0.354 |" in text
    assert "| 2025Q3 | 2.000 | 0.750 | 0.500 | 0.600 |" in text
    plot_drift(weekly, tmp_path / "e8.png")
    assert (tmp_path / "e8.png").stat().st_size > 0
