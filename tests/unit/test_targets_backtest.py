from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dockcast.evaluation.backtest import add_slices, run_fold, summarise
from dockcast.evaluation.reports import folds_json, replace_section
from dockcast.evaluation.splits import Fold
from dockcast.features.build import baseline_features
from dockcast.models.baselines import Persistence, SeasonalNaive7d
from dockcast.quality.gaps import Gap
from dockcast.targets.regression import issue_times, targets

pytestmark = pytest.mark.unit
T0 = pd.Timestamp("2025-10-20 00:00", tz="UTC")  # window spans the 2025-10-26 DST change


def make_panel(days: int = 15, stations: tuple[int, ...] = (1, 2)) -> pd.DataFrame:
    """States every 15 min; bikes = (minute-of-week index + station) % 25 (deterministic)."""
    times = pd.date_range(T0, periods=days * 96, freq="15min")
    frames = []
    for key in stations:
        idx = np.arange(len(times))
        frames.append(
            pd.DataFrame(
                {
                    "station_key": key,
                    "state_ts": times + pd.Timedelta(minutes=15),
                    "bikes": ((idx % (7 * 96)) + key) % 25,
                    "docks": 30 - (((idx % (7 * 96)) + key) % 25),
                    "target_ok": True,
                    "rebalance_flag": False,
                    "capacity": 30.0,
                }
            )
        )
    panel = pd.concat(frames, ignore_index=True)
    panel["bikes"] = panel["bikes"].astype(float)
    panel["docks"] = panel["docks"].astype(float)
    return panel


def test_issue_times_keep_targets_inside_window() -> None:
    start, end = T0, T0 + pd.Timedelta(hours=3)
    times = issue_times(start, end, 60)
    assert times[0] == start and times[-1] == end - pd.Timedelta(minutes=60)
    assert len(times) == 9


def test_targets_and_baseline_features_align() -> None:
    panel = make_panel()
    t = T0 + pd.Timedelta(days=8, hours=5)
    rows = baseline_features(panel, targets(panel, pd.DatetimeIndex([t]), 60), 60, [])
    row = rows[rows.station_key == 1].iloc[0]
    state = panel[panel.station_key == 1].set_index("state_ts")["bikes"]
    assert row["y"] == state[t + pd.Timedelta(minutes=60)]
    assert row["bikes_now"] == state[t]
    assert row["bikes_seasonal_7d"] == state[t + pd.Timedelta(minutes=60) - pd.Timedelta(days=7)]


def test_gap_masks_baseline_inputs_and_missing_targets() -> None:
    panel = make_panel()
    t = T0 + pd.Timedelta(days=8)
    gap = Gap(
        (t - timedelta(minutes=20)).to_pydatetime(),
        (t + timedelta(minutes=5)).to_pydatetime(),
        "hist_b",
        "hist_b",
    )
    dropped = panel[~((panel.station_key == 2) & (panel.state_ts == t + pd.Timedelta(minutes=60)))]
    rows = baseline_features(dropped, targets(dropped, pd.DatetimeIndex([t]), 60), 60, [gap])
    assert rows["bikes_now"].isna().all()  # bucket ending at t overlaps the gap
    s2 = rows[rows.station_key == 2].iloc[0]
    assert not s2["target_ok"] and np.isnan(s2["y"])


def test_slices_use_local_time_across_dst() -> None:
    rows = pd.DataFrame(
        {
            "target_ts": pd.to_datetime(["2025-10-25 07:30", "2025-10-27 07:30"], utc=True),
            "station_key": [1, 1],
            "capacity": [18.0, 40.0],
            "rebalance_flag": [False, True],
        }
    )
    out = add_slices(rows)
    # 07:30 UTC = 08:30 IST (Sat, before DST ends) and 07:30 GMT (Mon, after)
    assert list(out.hour) == ["8", "7"]
    assert list(out.weekend) == ["weekend", "weekday"]
    assert list(out.rush_hour) == ["rush", "rush"]
    assert list(out.capacity_band) == ["<20", "40+"]
    assert list(out.rebalance) == ["normal", "flagged"]


def test_run_fold_scores_common_rows_and_mase() -> None:
    panel = make_panel()
    start = (T0 + pd.Timedelta(days=8)).to_pydatetime()
    fold = Fold(1, start - timedelta(minutes=120), start, start + timedelta(days=1))
    outcome = run_fold(panel, fold, 60, [Persistence(), SeasonalNaive7d()], [])
    assert outcome.rows_common == outcome.rows_target_ok > 0
    overall = {m["model_name"]: m for m in outcome.metrics if m["slice_kind"] == "overall"}
    assert overall["persistence"]["mase"] == 1.0
    # the synthetic series repeats weekly, so seasonal naive is exact
    assert overall["seasonal_naive_7d"]["mae"] == 0.0
    summary = summarise(pd.DataFrame(outcome.metrics))
    assert set(summary.model_name) == {"persistence", "seasonal_naive_7d"}


def test_run_fold_requires_persistence() -> None:
    panel = make_panel()
    start = (T0 + pd.Timedelta(days=8)).to_pydatetime()
    fold = Fold(1, start - timedelta(minutes=120), start, start + timedelta(days=1))
    with pytest.raises(ValueError):
        run_fold(panel, fold, 60, [SeasonalNaive7d()], [])


def test_report_section_replace_and_folds_json(tmp_path: Path) -> None:
    path = tmp_path / "experiments.md"
    replace_section(path, "E1", "## E1 — old\n\nold body\n")
    replace_section(path, "E2", "## E2 — other\n\nkeep\n")
    replace_section(path, "E1", "## E1 — new\n\nnew body\n")
    text = path.read_text(encoding="utf-8")
    assert "new body" in text and "old body" not in text and "keep" in text
    fold = Fold(
        1,
        datetime(2026, 5, 6, tzinfo=UTC),
        datetime(2026, 5, 6, 2, tzinfo=UTC),
        datetime(2026, 5, 13, 2, tzinfo=UTC),
    )
    assert '"test_start": "2026-05-06T02:00:00+00:00"' in folds_json([fold])
