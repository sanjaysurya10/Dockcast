from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dockcast.evaluation import error_analysis as ea

pytestmark = pytest.mark.unit


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(5)
    n = 400
    y = rng.integers(0, 30, n).astype(float)
    return pd.DataFrame(
        {
            "station_key": rng.integers(1, 4, n),
            "target_ts": pd.date_range("2026-06-01", periods=n, freq="15min", tz="UTC"),
            "y": y,
            "pred_persistence": y + rng.normal(0, 3, n),
            "pred_lgbm_global": y + rng.normal(0, 2, n),
            "capacity": 30.0,
            "rebalance_flag": rng.random(n) < 0.1,
            "change_4": rng.integers(-10, 10, n).astype(float),
            "hour": (np.arange(n) % 24).astype(str),
            "weekend": np.where(np.arange(n) % 7 >= 5, "weekend", "weekday"),
            "fold": 1,
            "horizon_min": np.where(np.arange(n) % 2 == 0, 60, 120),
        }
    )


def test_report_answers_all_six_questions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ea, "FIGURES", tmp_path)
    names = pd.DataFrame({"station_key": [1, 2, 3], "name": ["A", "B", "C"]})
    text = ea.build_report(_frame(), "run123", names)
    for heading in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6."):
        assert heading in text
    assert "run123" in text and (tmp_path / "err_station_hour.png").exists()


def test_large_error_share_and_bias_sign() -> None:
    frame = ea.add_errors(_frame(), ["lgbm_global", "persistence"])
    large = ea.large_error_rebalance(frame, ["persistence"]).iloc[0]
    assert large["large_errors"] == int((frame["abs_persistence"] > 5).sum())
    shifted = frame.assign(pred_lgbm_global=frame["y"] - 1.0)
    bias = ea.error_vs_change(ea.add_errors(shifted, ["lgbm_global", "persistence"]), "lgbm_global")
    assert np.allclose(bias["bias_lgbm_global"], -1.0)  # prediction - actual
    growth = ea.horizon_growth(frame, ["persistence"])
    assert list(growth.horizon_min) == [60, 120]
