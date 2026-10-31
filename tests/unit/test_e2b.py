"""E2b: seeded short-history stations and history truncation."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dockcast.evaluation.splits import Fold
from dockcast.evaluation.training import LOOKBACK, prepare_fold
from dockcast.experiments.e2b import (
    drop_warmup,
    history_start,
    short_history_stations,
    short_summary,
    truncate_panel,
)
from tests.unit.test_models_m4 import CAL, INFO
from tests.unit.test_targets_backtest import T0, make_panel

pytestmark = pytest.mark.unit


def short_fold() -> Fold:
    test_start = (T0 + pd.Timedelta(days=21)).to_pydatetime()
    return Fold(1, test_start - timedelta(minutes=120), test_start, test_start + timedelta(days=2))


def test_short_stations_are_seeded_and_order_free() -> None:
    keys = list(range(1, 116))
    picked = short_history_stations(keys)
    assert len(picked) == 29 and picked == sorted(picked)
    assert short_history_stations(list(reversed(keys))) == picked
    assert short_history_stations(keys, seed=1) != picked


def test_truncation_keeps_only_the_short_window() -> None:
    fold = short_fold()
    panel = make_panel(days=24)
    start = history_start(fold, days=3)
    assert start == pd.Timestamp(fold.train_end) - timedelta(days=7 + 3) - LOOKBACK
    cut = truncate_panel(panel, [2], start)
    assert cut.loc[cut.station_key == 2, "state_ts"].min() >= start
    assert cut[cut.station_key == 1].equals(panel[panel.station_key == 1].reset_index(drop=True))
    data = prepare_fold(cut, fold, 60, [], CAL, INFO, T0.to_pydatetime())
    train = drop_warmup(data.train, [2], start)
    assert train.loc[train.station_key == 2, "issued_at"].min() >= start + LOOKBACK
    assert train.loc[train.station_key == 1, "issued_at"].min() < start + LOOKBACK
    info = short_summary(train, [2], 1, 60)
    assert info.short == 1 and info.short_max_rows < info.full_min_rows
    assert data.valid["station_key"].nunique() == 2  # validation week unchanged


def test_render_section_and_chart(tmp_path: Path) -> None:
    from dockcast.evaluation.backtest import add_slices
    from dockcast.experiments.e2 import MODELS, plot_low_data
    from dockcast.experiments.e2b import ShortInfo, render_section
    from dockcast.experiments.e4 import score_all

    t = pd.Timestamp("2026-05-06 08:00", tz="UTC")
    frames = []
    for fold in (1, 2):
        rows = pd.DataFrame(
            {
                "station_key": [1, 2, 3, 4],
                "target_ts": [t] * 4,
                "capacity": 30.0,
                "rebalance_flag": False,
                "y": [10.0, 5.0, 0.0, 3.0],
                "fold": fold,
                "horizon_min": 60,
                "cluster": ["0", "0", "1", "1"],
                "history": ["short", "full", "full", "full"],
            }
        )
        for k, name in enumerate(MODELS):
            rows[f"pred_{name}"] = rows["y"] + k * 0.5
            rows[f"p10_{name}"] = rows[f"pred_{name}"] - 1
            rows[f"p90_{name}"] = rows[f"pred_{name}"] + 1
        frames.append(add_slices(rows))
    results = score_all(pd.concat(frames), MODELS, extra=("cluster", "history"))
    when = datetime(2026, 5, 6, tzinfo=UTC)
    info = [ShortInfo(1, 60, 1, 600, 640, 16000), ShortInfo(2, 60, 1, 610, 650, 16100)]
    text = render_section("run", "e3", [Fold(1, when, when, when)] * 2, results, info, [1])
    assert (
        "Training rows per short station: 600-650; per full-history station at least 16000" in text
    )
    assert "| +60 | lgbm_per_station | 1.000 (0/2) | 1.000 (0/2) | 1.000 (0/2) |" in text
    assert "| +60 | history | short | 0.500 | +0.500 | +1.000 | +1.500 |" in text
    plot_low_data(results, tmp_path / "e2b.png", "history", "short", "Short")
    assert (tmp_path / "e2b.png").stat().st_size > 0
    assert np.isfinite(results["mae"]).all()
