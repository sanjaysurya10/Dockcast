"""E7 ablation variants, cluster one-hot, oracle weather and the report."""

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dockcast.evaluation.splits import Fold
from dockcast.experiments.e7 import (
    ablation_groups,
    ablation_table,
    add_cluster_onehot,
    plot_ablation,
    render_section,
    variants,
)
from dockcast.features.weather import oracle_weather

pytestmark = pytest.mark.unit


def test_variants_drop_exactly_one_group() -> None:
    groups = ablation_groups(4)
    assert list(groups)[-3:] == ["spatial", "cluster", "weather"]
    columns = variants(groups)
    assert len(columns) == len(groups) + 1
    full = set(columns["full"])
    for name, cols in groups.items():
        assert full - set(columns[f"no_{name}"]) == set(cols)


def test_cluster_onehot_uses_fold_assignment() -> None:
    rows = pd.DataFrame({"station_key": [1, 2, 3]})
    out = add_cluster_onehot(rows, {1: 0, 2: 2}, 3)
    assert out[["cluster_0", "cluster_1", "cluster_2"]].to_numpy().tolist() == [
        [1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0],
        [0.0, 0.0, 0.0],  # unlabelled station
    ]


def test_oracle_weather_uses_the_hour_closing_the_target_bucket() -> None:
    weather = pd.DataFrame(
        {
            "ts": pd.to_datetime(["2026-05-06 08:00", "2026-05-06 09:00"], utc=True),
            "temp_c": [10.0, 12.0],
            "precip_mm": [0.0, 1.5],
            "wind_speed_ms": [3.0, 4.0],
        }
    )
    targets = pd.to_datetime(
        ["2026-05-06 08:00", "2026-05-06 08:15", "2026-05-06 09:00", "2026-05-06 10:00"], utc=True
    )
    out = oracle_weather(pd.DataFrame({"target_ts": targets}), weather)
    assert out["temp_c"].tolist()[:3] == [10.0, 12.0, 12.0]
    assert out["is_raining"].tolist()[:3] == [0.0, 1.0, 1.0]
    assert out.loc[3, ["temp_c", "is_raining"]].isna().all()  # hour missing


def test_table_section_and_chart(tmp_path: Path) -> None:
    from dockcast.evaluation.backtest import add_slices
    from dockcast.experiments.e4 import score_all

    names = ["persistence", "lgbm_full", "lgbm_no_lags", "lgbm_no_weather"]
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
            }
        )
        for name, err in zip(names, (2.0, 0.5, 1.5, 0.5 + 0.1 * fold), strict=True):
            rows[f"pred_{name}"] = rows["y"] + err
            rows[f"p10_{name}"] = rows[f"pred_{name}"] - 1
            rows[f"p90_{name}"] = rows[f"pred_{name}"] + 1
        frames.append(add_slices(rows))
    results = score_all(pd.concat(frames), names)
    table = ablation_table(results, names)
    assert table["group"].tolist() == ["lags", "weather"]
    assert table.loc[0, "delta_mae"] == pytest.approx(1.0) and table.loc[0, "hurts"] == 2
    assert table.loc[1, "delta_mae"] == pytest.approx(0.15)
    when = datetime(2026, 5, 6, tzinfo=UTC)
    groups = {"lags": ["a"], "weather": ["b"]}
    text = render_section("run", "e3", [Fold(1, when, when, when)] * 2, results, table, groups)
    assert "| weather (oracle) | +0.150 | +0.100 to +0.200 | 2/2 |" in text
    assert "| cluster | 0 | 0.500 | +1.000 | +0.150 |" in text
    plot_ablation(table, tmp_path / "e7.png")
    assert (tmp_path / "e7.png").stat().st_size > 0
    assert np.isfinite(table["delta_mae"]).all()
