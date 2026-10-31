"""E6 calibration metrics."""

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dockcast.evaluation.splits import Fold
from dockcast.experiments.e6 import (
    calibration,
    calibration_table,
    pinball,
    plot_coverage_by_hour,
    render_section,
    station_coverage,
)

pytestmark = pytest.mark.unit


def test_pinball_penalises_each_side_by_its_quantile() -> None:
    y = np.array([10.0, 10.0])
    assert pinball(y, np.array([8.0, 8.0]), 0.9) == pytest.approx(1.8)
    assert pinball(y, np.array([12.0, 12.0]), 0.9) == pytest.approx(0.2)


def test_calibration_counts_inside_and_below() -> None:
    rows = pd.DataFrame(
        {
            "y": [0.0, 5.0, 10.0, 20.0],
            "p10_lgbm_global": [1.0, 4.0, 8.0, 8.0],
            "pred_lgbm_global": [2.0, 5.0, 10.0, 10.0],
            "p90_lgbm_global": [3.0, 6.0, 12.0, 12.0],
        }
    )
    out = calibration(rows)
    assert out["coverage"] == 0.5  # 0 below P10, 20 above P90
    assert out["width"] == pytest.approx(3.0)
    assert (out["below_10"], out["above_90"]) == (0.25, 0.25)
    assert (out["below_50"], out["above_50"]) == (0.25, 0.25)  # two rows tie with P50


def sample_rows() -> pd.DataFrame:
    rng = np.random.default_rng(1)
    n = 2000
    y = rng.normal(10, 2, n)
    return pd.DataFrame(
        {
            "station_key": rng.integers(1, 5, n),
            "fold": rng.integers(1, 3, n),
            "horizon_min": rng.choice([30, 60], n),
            "hour": rng.integers(0, 24, n).astype(str),
            "cluster": rng.integers(0, 2, n).astype(str),
            "weekend": "weekday",
            "rush_hour": "other",
            "capacity_band": "20-29",
            "y": y,
            "p10_lgbm_global": 10 - 1.2816 * 2,
            "pred_lgbm_global": 10.0,
            "p90_lgbm_global": 10 + 1.2816 * 2,
        }
    )


def test_table_section_and_chart_on_calibrated_quantiles(tmp_path: Path) -> None:
    rows = sample_rows()
    table = calibration_table(rows)
    overall = table[table.slice_kind == "overall"]
    assert len(overall) == 4 and overall["coverage"].between(0.74, 0.86).all()
    stations = station_coverage(rows)
    assert len(stations) == 8
    when = datetime(2026, 5, 6, tzinfo=UTC)
    text = render_section("run", "e1", "e3", [Fold(1, when, when, when)], table, stations)
    assert "## E6" in text and "| +30 | hour 0 |" in text and "| +60 | cluster 1 |" in text
    plot_coverage_by_hour(table, tmp_path / "e6.png")
    assert (tmp_path / "e6.png").stat().st_size > 0
