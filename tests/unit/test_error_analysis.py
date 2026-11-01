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


def _v2_frame() -> pd.DataFrame:
    frame = _frame()
    frame["issued_at"] = frame["target_ts"] - pd.Timedelta(minutes=60)
    frame["rush_hour"] = "other"
    frame["capacity_band"] = "30-39"
    frame["p10_lgbm_global"] = frame["pred_lgbm_global"] - 2.0
    frame["p90_lgbm_global"] = frame["pred_lgbm_global"] + 2.0
    return frame


def _e2(frame: pd.DataFrame) -> pd.DataFrame:
    e2 = frame[["station_key", "issued_at", "horizon_min", "fold", "pred_lgbm_global"]].copy()
    e2["cluster"] = np.where(frame["station_key"] == 1, 0, 1)
    e2["pred_lgbm_per_cluster"] = frame["y"]
    e2["p10_lgbm_per_cluster"] = frame["y"] - 1.0
    e2["p90_lgbm_per_cluster"] = frame["y"] + 1.0
    return e2


def test_add_e2_joins_rows_and_rejects_other_runs() -> None:
    frame = _v2_frame()
    joined = ea.add_e2(frame, _e2(frame))
    assert len(joined) == len(frame)
    assert set(joined["cluster"]) == {"0", "1"}
    other = _e2(frame).assign(pred_lgbm_global=lambda f: f["pred_lgbm_global"] + 1.0)
    with pytest.raises(ValueError, match="different upstream"):
        ea.add_e2(frame, other)
    with pytest.raises(ValueError, match="cover"):
        ea.add_e2(frame, _e2(frame).iloc[1:])


def test_slice_metrics_and_champion_rule() -> None:
    frame = ea.add_e2(_v2_frame(), _e2(_v2_frame()))
    table = ea.slice_metrics(frame, ["lgbm_global", "lgbm_per_cluster"])
    assert list(table.loc[table["slice"] == "horizon", "value"]) == ["+60", "+120"]
    assert set(table["slice"]) >= {"hour", "weekend", "cluster", "rebalance"}
    h60 = table[(table["slice"] == "horizon") & (table["value"] == "+60")].iloc[0]
    assert h60["mae_per_cluster"] == 0.0 and h60["cov_per_cluster"] == 1.0
    assert h60["rows"] == int((frame["horizon_min"] == 60).sum())
    # per-cluster is exact but always covers (1.0 > 0.90), so it is not eligible
    picks = ea.champions(frame, ["lgbm_global", "lgbm_per_cluster", "persistence"])
    assert set(picks["champion"].dropna()) <= {"lgbm_global"}


def test_v2_report_has_slices_and_champion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ea, "FIGURES", tmp_path)
    names = pd.DataFrame({"station_key": [1, 2, 3], "name": ["A", "B", "C"]})
    frame = ea.add_e2(_v2_frame(), _e2(_v2_frame()))
    text = ea.build_report(frame, "run123", names, e2_run="e2run")
    assert "# Error analysis (v2)" in text and "e2run" in text
    assert "## 7. Metrics by slice" in text and "## 8. Champion" in text
