"""Rolling-origin backtest runner (PRD 13).

For each fold and horizon: build test rows (every station x every 15-min issue time in the test
window whose target falls inside it), add features with the cut-off rule, fit each model on
training rows (baselines ignore them), predict, keep **common rows** (valid target and a
prediction from every model) and score per slice. MASE divides by persistence MAE on the same
rows, so ``persistence`` must be one of the models.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pandas as pd

from dockcast.evaluation import metrics
from dockcast.evaluation.splits import Fold
from dockcast.features.build import FEATURE_COLUMNS, baseline_features
from dockcast.models.base import Forecaster
from dockcast.models.postprocess import postprocess
from dockcast.quality.gaps import Gap
from dockcast.targets.regression import issue_times, targets

if TYPE_CHECKING:
    from dockcast.evaluation.training import FoldData

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
    scored: pd.DataFrame,
    model_names: Sequence[str],
    fold: int,
    horizon_min: int,
    interval_models: Sequence[str] = (),
) -> list[dict[str, object]]:
    """Metrics for every model and slice on common rows.

    Args:
        scored: Common rows with ``y`` and ``pred_<model>`` columns plus slice columns;
            quantile models also have ``p10_<model>`` and ``p90_<model>``.
        model_names: Models; must include ``persistence``.
        fold: Fold number.
        horizon_min: Horizon.
        interval_models: Models scored on pinball loss, coverage and width.

    Returns:
        Rows shaped like ``backtest_results`` (without run id / experiment).
    """
    out: list[dict[str, object]] = []
    nan = float("nan")
    for kind in SLICE_KINDS:
        for value, part in scored.groupby(kind, observed=True):
            base_mae = metrics.mae(part["y"], part["pred_persistence"])
            for name in model_names:
                pred = part[f"pred_{name}"]
                model_mae = metrics.mae(part["y"], pred)
                row: dict[str, object] = {
                    "model_name": name,
                    "fold": fold,
                    "horizon_min": horizon_min,
                    "slice_kind": kind,
                    "slice_value": str(value),
                    "n": len(part),
                    "mae": model_mae,
                    "rmse": metrics.rmse(part["y"], pred),
                    "mase": metrics.mase(model_mae, base_mae),
                    "bias": metrics.bias(part["y"], pred),
                    "pinball_p10": nan,
                    "pinball_p50": nan,
                    "pinball_p90": nan,
                    "coverage_80": nan,
                    "interval_width": nan,
                }
                if name in interval_models:
                    lo, hi = part[f"p10_{name}"], part[f"p90_{name}"]
                    row |= {
                        "pinball_p10": metrics.pinball(part["y"], lo, 0.1),
                        "pinball_p50": metrics.pinball(part["y"], pred, 0.5),
                        "pinball_p90": metrics.pinball(part["y"], hi, 0.9),
                        "coverage_80": metrics.coverage(part["y"], lo, hi),
                        "interval_width": metrics.interval_width(lo, hi),
                    }
                out.append(row)
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


def score_fold(
    data: "FoldData",
    fold: Fold,
    horizon_min: int,
    models: Sequence[Forecaster],
    feature_cols: Sequence[str],
) -> FoldOutcome:
    """Fit every model on the fold's training rows, predict the test rows and score.

    Models with a ``fit(X, y, X_valid, y_valid)`` signature (LightGBM) get the validation week
    for early stopping. Predictions are post-processed (clip to capacity, sorted quantiles).

    Args:
        data: Output of :func:`dockcast.evaluation.training.prepare_fold`.
        fold: Fold.
        horizon_min: Horizon.
        models: Forecasters (``persistence`` required).
        feature_cols: Feature columns handed to the models.

    Returns:
        The fold outcome (common rows only in ``scored``).
    """
    names = [m.name for m in models]
    if "persistence" not in names:
        raise ValueError("persistence must be included (MASE denominator)")
    test = data.test
    interval: list[str] = []
    for model in models:
        if getattr(model, "uses_validation", False):
            model.fit(data.train, data.train["y"], data.valid, data.valid["y"])  # type: ignore[call-arg]
        else:
            model.fit(data.train, data.train["y"])
        pred = postprocess(model.predict(test), test["capacity"])
        test[f"pred_{model.name}"] = pred["p50"].to_numpy()
        if not model.is_point:
            interval.append(model.name)
            test[f"p10_{model.name}"] = pred["p10"].to_numpy()
            test[f"p90_{model.name}"] = pred["p90"].to_numpy()
    pred_cols = [f"pred_{n}" for n in names]
    common = test["target_ok"] & test[pred_cols].notna().all(axis=1)
    scored = test[common].reset_index(drop=True)
    return FoldOutcome(
        fold=fold.fold,
        horizon_min=horizon_min,
        rows_total=len(test),
        rows_target_ok=int(test["target_ok"].sum()),
        rows_common=len(scored),
        scored=scored,
        metrics=score_slices(scored, names, fold.fold, horizon_min, interval),
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
        coverage_80=("coverage_80", "mean"),
        interval_width=("interval_width", "mean"),
        pinball_p50=("pinball_p50", "mean"),
        n=("n", "sum"),
        folds=("fold", "nunique"),
    ).reset_index()
    return summary.sort_values(["horizon_min", "mae"]).reset_index(drop=True)
