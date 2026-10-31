"""Per-group LightGBM, Prophet per station and the E2 low-data split."""

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dockcast.experiments.e2 import cluster_groups, low_data_stations, low_data_summary
from dockcast.models.partitioned import PartitionedLgbm
from dockcast.models.prophet_model import ProphetStation

pytestmark = pytest.mark.unit
RNG = np.random.default_rng(5)


def group_rows(n: int = 400) -> pd.DataFrame:
    """Stations 1 and 2 follow opposite rules on the same feature."""
    f = RNG.uniform(0, 10, 2 * n)
    station = np.repeat([1, 2], n)
    y = np.where(station == 1, f, 10 - f)
    return pd.DataFrame({"station_key": station, "f": f, "y": y})


def test_each_group_learns_only_from_its_own_rows() -> None:
    rows = group_rows()
    model = PartitionedLgbm("lgbm_per_station", ["f"], {1: 1, 2: 2}, n_jobs=2)
    model.fit(rows, rows["y"])
    probe = pd.DataFrame({"station_key": [1, 2, 3], "f": [9.0, 9.0, 9.0]})
    pred = model.predict(probe)
    assert pred.loc[0, "p50"] > 7 > 3 > pred.loc[1, "p50"]
    assert pred.loc[2].isna().all()  # station without a group
    changed = rows.assign(y=np.where(rows.station_key == 2, 0.0, rows.y))
    again = PartitionedLgbm("lgbm_per_station", ["f"], {1: 1, 2: 2}).fit(changed, changed["y"])
    assert again.predict(probe).loc[0, "p50"] == pytest.approx(pred.loc[0, "p50"])


def test_cluster_model_pools_stations_of_one_group() -> None:
    rows = group_rows()
    model = PartitionedLgbm("lgbm_per_cluster", ["f"], {1: 0, 2: 0}, n_jobs=1)
    model.fit(rows, rows["y"], rows, rows["y"])
    assert list(model.models) == [0]
    assert model.models[0].stations == [1, 2]


def hourly_states(days: int = 21) -> pd.DataFrame:
    ts = pd.date_range("2026-03-01", periods=days * 24, freq="h", tz="UTC")
    local_hour = ts.tz_convert("Europe/Dublin").hour
    bikes = 10 + 5 * np.sin(2 * np.pi * local_hour / 24)
    return pd.DataFrame({"station_key": 7, "state_ts": ts, "bikes": bikes, "target_ok": True})


def test_prophet_predicts_daily_cycle_with_interval() -> None:
    states = hourly_states()
    cutoff = pd.Timestamp("2026-03-20", tz="UTC")
    model = ProphetStation([date(2026, 3, 17)]).fit_states(states, cutoff)
    targets = states[states.state_ts >= cutoff].head(24)
    probe = pd.DataFrame(
        {"station_key": [7] * 24 + [8], "target_ts": [*targets.state_ts, targets.state_ts.iloc[0]]}
    )
    pred = model.predict(probe)
    assert pred.iloc[-1].isna().all()  # unknown station
    known = pred.iloc[:-1]
    assert (known["p10"] <= known["p50"]).all() and (known["p50"] <= known["p90"]).all()
    assert np.abs(known["p50"].to_numpy() - targets["bikes"].to_numpy()).mean() < 1.0


def test_low_data_is_bottom_quarter_with_ties_by_key() -> None:
    counts = {1: 5, 2: 5, 3: 9, 4: 9, 5: 9, 6: 9, 7: 9, 8: 9}
    train = pd.DataFrame({"station_key": [s for s, n in counts.items() for _ in range(n)]})
    assert low_data_stations(train) == [1, 2]
    counts[3] = 5
    train = pd.DataFrame({"station_key": [s for s, n in counts.items() for _ in range(n)]})
    assert low_data_stations(train) == [1, 2]  # ceil(8 / 4) = 2, key breaks the tie
    summary = low_data_summary(train, [1, 2], fold=1, horizon=60)
    assert (summary.stations, summary.low, summary.low_max_rows, summary.rest_min_rows) == (
        8,
        2,
        5,
        5,
    )


def test_cluster_groups_uses_labels_of_that_fold() -> None:
    labels = pd.DataFrame(
        {"station_key": [1, 2, 1, 2], "cluster_id": [0, 1, 1, 1], "fold": [1, 1, 2, 2]}
    )
    assert cluster_groups(labels, 1) == {1: 0, 2: 1}
    assert cluster_groups(labels, 2) == {1: 1, 2: 1}


def test_prophet_daily_cycle_follows_local_hours_across_dst() -> None:
    ts = pd.date_range("2026-03-08", "2026-04-08", freq="h", tz="UTC")  # spans 29 March
    local_hour = ts.tz_convert("Europe/Dublin").hour
    states = pd.DataFrame(
        {
            "station_key": 7,
            "state_ts": ts,
            "bikes": 10 + 5 * np.sin(2 * np.pi * local_hour / 24),
            "target_ok": True,
        }
    )
    cutoff = pd.Timestamp("2026-04-05", tz="UTC")  # trained on both sides of the change
    model = ProphetStation([]).fit_states(states, cutoff)
    targets = states[states.state_ts >= cutoff]
    pred = model.predict(pd.DataFrame({"station_key": 7, "target_ts": targets.state_ts}))
    assert np.abs(pred["p50"].to_numpy() - targets["bikes"].to_numpy()).mean() < 1.0


def test_render_section_and_chart(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from dockcast.evaluation.backtest import add_slices
    from dockcast.evaluation.splits import Fold
    from dockcast.experiments.e2 import MODELS, LowData, plot_low_data, render_section
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
                "data_amount": ["low", "rest", "rest", "rest"],
            }
        )
        for k, name in enumerate(MODELS):
            rows[f"pred_{name}"] = rows["y"] + k * 0.5
            rows[f"p10_{name}"] = rows[f"pred_{name}"] - 1
            rows[f"p90_{name}"] = rows[f"pred_{name}"] + 1
        frames.append(add_slices(rows))
    results = score_all(pd.concat(frames), MODELS, extra=("cluster", "data_amount"))
    when = datetime(2026, 5, 6, tzinfo=UTC)
    low = [LowData(1, 60, 4, 1, 100, 200), LowData(2, 60, 4, 1, 120, 210)]
    text = render_section("run", "e1", "e3", [Fold(1, when, when, when)] * 2, results, low)
    assert "differ by 90-100 training rows (cut-offs 100-120 rows)" in text
    assert "| +60 | lgbm_per_station | 1.000 (0/2) | 1.000 (0/2) | 1.000 (0/2) |" in text
    assert "| +60 | data_amount | low | 0.500 | +0.500 | +1.000 | +1.500 |" in text
    plot_low_data(results, tmp_path / "e2.png")
    assert (tmp_path / "e2.png").stat().st_size > 0
