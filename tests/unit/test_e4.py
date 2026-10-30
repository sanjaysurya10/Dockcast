"""E4 joins model A from E1 and scores every model on the shared rows."""

import pandas as pd
import pytest

from dockcast.evaluation.backtest import add_slices
from dockcast.experiments.e4 import attach_baseline, delta_table, score_all

pytestmark = pytest.mark.unit
T = pd.Timestamp("2026-05-06 08:00", tz="UTC")


def e4_rows() -> pd.DataFrame:
    rows = pd.DataFrame(
        {
            "station_key": [1, 2, 3],
            "issued_at": [T, T, T],
            "target_ts": [T + pd.Timedelta(hours=1)] * 3,
            "horizon_min": 60,
            "fold": 1,
            "y": [10.0, 5.0, 0.0],
            "capacity": [30.0, 30.0, 30.0],
            "rebalance_flag": [False, False, False],
            "pred_persistence": [12.0, 5.0, 2.0],
            "pred_lgbm_spatial_600": [10.0, 6.0, 0.0],
            "p10_lgbm_spatial_600": [8.0, 4.0, 0.0],
            "p90_lgbm_spatial_600": [12.0, 8.0, 1.0],
        }
    )
    return add_slices(rows)


E1 = pd.DataFrame(
    {
        "station_key": [1, 2, 4],
        "issued_at": [T, T, T],
        "horizon_min": 60,
        "fold": 1,
        "y": [10.0, 5.0, 7.0],
        "pred_lgbm_global": [11.0, 7.0, 7.0],
        "p10_lgbm_global": [9.0, 5.0, 6.0],
        "p90_lgbm_global": [13.0, 9.0, 8.0],
    }
)
LABELS = pd.DataFrame({"station_key": [1], "cluster_id": [2], "fold": [1]})


def test_attach_keeps_shared_rows_and_adds_in_fold_cluster() -> None:
    merged = attach_baseline(e4_rows(), E1, LABELS)
    assert merged["station_key"].tolist() == [1, 2]
    assert merged["cluster"].tolist() == ["2", "none"]
    assert merged["pred_lgbm_global"].tolist() == [11.0, 7.0]


def test_attach_refuses_different_targets() -> None:
    bad = E1.assign(y=[10.0, 6.0, 7.0])
    with pytest.raises(ValueError, match="targets differ"):
        attach_baseline(e4_rows(), bad, LABELS)


def test_score_all_and_delta_by_slice() -> None:
    merged = attach_baseline(e4_rows(), E1, LABELS)
    names = ["persistence", "lgbm_global", "lgbm_spatial_600"]
    results = score_all(merged, names)
    overall = results[(results.slice_kind == "overall")].set_index("model_name")["mae"]
    assert overall["lgbm_global"] == pytest.approx(1.5)  # |11-10|, |7-5|
    assert overall["lgbm_spatial_600"] == pytest.approx(0.5)  # 0, |6-5|
    cluster = results[(results.slice_kind == "cluster") & (results.slice_value == "2")]
    assert set(cluster.model_name) == set(names)
    lines = delta_table(results, names[2:], 60)
    assert lines[0] == "| overall | all | 2 | 1.500 | -1.000 |"


def test_render_handles_different_radii_per_horizon() -> None:
    from datetime import UTC, datetime

    from dockcast.evaluation.splits import Fold
    from dockcast.experiments.e4 import render_section

    h60 = attach_baseline(e4_rows(), E1, LABELS).assign(
        pred_lgbm_spatial_400=[10.5, 5.5],
        p10_lgbm_spatial_400=[9.0, 4.0],
        p90_lgbm_spatial_400=[12.0, 7.0],
    )
    h30 = h60.drop(columns=[c for c in h60 if c.endswith("_400")]).assign(horizon_min=30)
    merged = pd.concat([h60, h30], ignore_index=True)
    names = ["persistence", "lgbm_global", "lgbm_spatial_400", "lgbm_spatial_600"]
    results = score_all(merged, names)
    assert set(results[results.horizon_min == 30].model_name) == {
        "persistence",
        "lgbm_global",
        "lgbm_spatial_600",
    }
    when = datetime(2026, 5, 6, tzinfo=UTC)
    text = render_section(
        "run", "e1", "e3", [Fold(1, when, when, when)], {60: [400, 600], 30: [600]}, 5, results
    )
    assert "+60: 400 m / 600 m; +30: 600 m" in text
    assert "| slice | value | rows | MAE A | Δ 400 m | Δ 600 m |" in text
    assert "| slice | value | rows | MAE A | Δ 600 m |" in text
