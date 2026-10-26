"""Rolling-origin backtest runner (PRD 13).

For each fold and horizon: build test rows (every station x every 15-min issue time in the test
window whose target falls inside it), add features with the cut-off rule, fit each model on
training rows (baselines ignore them), predict, keep **common rows** (valid target and a
prediction from every model) and score per slice. MASE divides by persistence MAE on the same
rows, so ``persistence`` must be one of the models.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

import pandas as pd

from dockcast.evaluation import metrics
from dockcast.evaluation.splits import Fold
from dockcast.features.build import FEATURE_COLUMNS, baseline_features
from dockcast.models.base import Forecaster
from dockcast.quality.gaps import Gap
from dockcast.targets.regression import issue_times, targets

TZ = "Europe/Dublin"
CAPACITY_BANDS = [0, 20, 30, 40, 1000]
CAPACITY_LABELS = ["<20", "20-29", "30-39", "40+"]
SLICE_KINDS = (
    "overall",
    "hour",
    "dow",
    "weekend",
    "rush_hour",
    "capacity_band",
    "rebalance",
    "station",
)


@dataclass
class FoldOutcome:
    """Scored rows and per-slice metrics for one fold and horizon."""

    fold: int
    horizon_min: int
    rows_total: int
    rows_target_ok: int
    rows_common: int
    scored: pd.DataFrame
    metrics: list[dict[str, object]] = field(default_factory=list)


def add_slices(rows: pd.DataFrame) -> pd.DataFrame:
    """Slice columns from the target time in local time (PRD 13.3).

    Args:
        rows: Columns ``target_ts, station_key, capacity, rebalance_flag``.

    Returns:
        ``rows`` with ``hour, dow, weekend, rush_hour, capacity_band, rebalance, station``.
    """
    local = rows["target_ts"].dt.tz_convert(TZ)
    out = rows.copy()
    out["hour"] = local.dt.hour.astype(str)
    out["dow"] = local.dt.dayofweek.astype(str)
    out["weekend"] = (local.dt.dayofweek >= 5).map({True: "weekend", False: "weekday"})
    hour = local.dt.hour
    rush = ((hour >= 7) & (hour < 10)) | ((hour >= 16) & (hour < 19))
    out["rush_hour"] = rush.map({True: "rush", False: "other"})
    out["capacity_band"] = pd.cut(
        out["capacity"], CAPACITY_BANDS, labels=CAPACITY_LABELS, right=False
    ).astype(str)
    out["rebalance"] = out["rebalance_flag"].map({True: "flagged", False: "normal"})
    out["station"] = out["station_key"].astype(str)
    out["overall"] = "all"
    return out


def fold_rows(
    panel: pd.DataFrame, fold: Fold, horizon_min: int, gaps: Sequence[Gap]
) -> pd.DataFrame:
    """Test rows for one fold: targets, baseline features and slice columns.

    Args:
        panel: States covering the test window and 7 days before it.
        fold: Fold.
        horizon_min: Horizon in minutes.
        gaps: Data gaps.

    Returns:
        One row per station and issue time.
    """
    times = issue_times(fold.test_start, fold.test_end, horizon_min)
    rows = targets(panel, times, horizon_min)
    return add_slices(baseline_features(panel, rows, horizon_min, gaps))


def score_slices(
    scored: pd.DataFrame, model_names: Sequence[str], fold: int, horizon_min: int
) -> list[dict[str, object]]:
    """Metrics for every model and slice on common rows.

    Args:
        scored: Common rows with ``y`` and ``pred_<model>`` columns plus slice columns.
        model_names: Models; must include ``persistence``.
        fold: Fold number.
        horizon_min: Horizon.

    Returns:
        Rows shaped like ``backtest_results`` (without run id / experiment).
    """
    out: list[dict[str, object]] = []
    for kind in SLICE_KINDS:
        for value, part in scored.groupby(kind, observed=True):
            base_mae = metrics.mae(part["y"], part["pred_persistence"])
            for name in model_names:
                model_mae = metrics.mae(part["y"], part[f"pred_{name}"])
                out.append(
                    {
                        "model_name": name,
                        "fold": fold,
                        "horizon_min": horizon_min,
                        "slice_kind": kind,
                        "slice_value": str(value),
                        "n": len(part),
                        "mae": model_mae,
                        "rmse": metrics.rmse(part["y"], part[f"pred_{name}"]),
                        "mase": metrics.mase(model_mae, base_mae),
                        "bias": metrics.bias(part["y"], part[f"pred_{name}"]),
                    }
                )
    return out


def run_fold(
    panel: pd.DataFrame,
    fold: Fold,
    horizon_min: int,
    models: Sequence[Forecaster],
    gaps: Sequence[Gap],
) -> FoldOutcome:
    """Predict and score one fold and horizon.

    Args:
        panel: States covering the test window and 7 days before it.
        fold: Fold.
        horizon_min: Horizon.
        models: Forecasters (``persistence`` required for MASE).
        gaps: Data gaps.

    Returns:
        The fold outcome.
    """
    names = [m.name for m in models]
    if "persistence" not in names:
        raise ValueError("persistence must be included (MASE denominator)")
    rows = fold_rows(panel, fold, horizon_min, gaps)
    features = rows[FEATURE_COLUMNS]
    for model in models:
        model.fit(features.iloc[0:0], rows["y"].iloc[0:0])  # baselines: nothing to learn
        rows[f"pred_{model.name}"] = model.predict(features)["p50"].to_numpy()
    pred_cols = [f"pred_{n}" for n in names]
    common = rows["target_ok"] & rows[pred_cols].notna().all(axis=1)
    scored = rows[common].reset_index(drop=True)
    return FoldOutcome(
        fold=fold.fold,
        horizon_min=horizon_min,
        rows_total=len(rows),
        rows_target_ok=int(rows["target_ok"].sum()),
        rows_common=len(scored),
        scored=scored,
        metrics=score_slices(scored, names, fold.fold, horizon_min),
    )


def summarise(results: pd.DataFrame) -> pd.DataFrame:
    """Overall metrics averaged over folds (mean and std of fold values).

    Args:
        results: Rows from :func:`score_slices` for all folds.

    Returns:
        One row per model and horizon.
    """
    overall = results[results["slice_kind"] == "overall"]
    grouped = overall.groupby(["model_name", "horizon_min"])
    summary = grouped.agg(
        mae=("mae", "mean"),
        mae_std=("mae", "std"),
        rmse=("rmse", "mean"),
        mase=("mase", "mean"),
        bias=("bias", "mean"),
        n=("n", "sum"),
        folds=("fold", "nunique"),
    ).reset_index()
    return summary.sort_values(["horizon_min", "mae"]).reset_index(drop=True)
