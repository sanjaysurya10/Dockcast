"""Error analysis (PRD 13.3, 13.4) → ``reports/error_analysis.md`` + ``reports/figures/err_*.png``.

Reads the scored test rows saved by an E1 run (``data/processed/e1_predictions_<run>.parquet``)
and, for v2, the E2 rows (``e2_predictions_<run>.parquet``) that add ``lgbm_per_cluster`` and
the in-fold cluster on the same rows. It answers the six PRD 13.4 questions for the main model
(default ``lgbm_global``) with the other models alongside, reports the PRD 13.3 metrics by slice
and applies the PRD 12.5 champion rule. Every number comes from those files, so the report cites
their MLflow runs.
"""

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sqlalchemy import Engine, text

from dockcast.config import get_env_settings
from dockcast.db.engine import make_engine
from dockcast.evaluation import metrics
from dockcast.evaluation.champion import select_champions
from dockcast.evaluation.reports import REPORTS, git_commit
from dockcast.quality.eda import md_table

FIGURES = REPORTS / "figures"
LARGE_ERROR = 5.0
CHANGE_BINS = [-1000, -6, -2, 1, 5, 1000]
CHANGE_LABELS = ["<= -6", "-5..-2", "-1..+1", "+2..+5", ">= +6"]
V2_MODEL = "lgbm_per_cluster"
E2_KEYS = ["station_key", "issued_at", "horizon_min", "fold"]
SLICE_COLUMNS = ("hour", "weekend", "rush_hour", "capacity_band", "cluster", "rebalance")
SLICE_HORIZON = 60


def latest_predictions(experiment: str = "e1") -> tuple[Path, str]:
    """Newest predictions file of an experiment and its run id."""
    folder = get_env_settings().data_dir / "processed"
    prefix = f"{experiment}_predictions_"
    files = sorted(folder.glob(f"{prefix}*.parquet"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"no {prefix}*.parquet in {folder}")
    path = files[-1]
    return path, path.stem.removeprefix(prefix)


def add_e2(frame: pd.DataFrame, e2: pd.DataFrame) -> pd.DataFrame:
    """Join ``cluster`` and the ``lgbm_per_cluster`` columns of an E2 run onto E1 rows.

    Args:
        frame: E1 scored rows.
        e2: E2 scored rows on the same folds.

    Returns:
        ``frame`` plus ``cluster, pred_/p10_/p90_lgbm_per_cluster``.

    Raises:
        ValueError: If E2 does not cover every E1 row, or its ``lgbm_global`` differs from E1's
            (so the two files come from different upstream runs).
    """
    v2_cols = [f"{kind}_{V2_MODEL}" for kind in ("pred", "p10", "p90")]
    right = e2[[*E2_KEYS, "cluster", "pred_lgbm_global", *v2_cols]].rename(
        columns={"pred_lgbm_global": "e2_lgbm_global"}
    )
    out = frame.merge(right, on=E2_KEYS, how="left", validate="one_to_one")
    if out[f"pred_{V2_MODEL}"].isna().any():
        raise ValueError("E2 predictions do not cover every E1 row")
    if not np.allclose(out["e2_lgbm_global"], out["pred_lgbm_global"]):
        raise ValueError("E2 lgbm_global differs from E1: different upstream runs")
    out["cluster"] = out["cluster"].astype(str)
    return out.drop(columns="e2_lgbm_global")


def add_errors(frame: pd.DataFrame, models: Sequence[str]) -> pd.DataFrame:
    """``abs_<m>`` and ``err_<m>`` (prediction - actual) columns."""
    out = frame.copy()
    for m in models:
        out[f"err_{m}"] = out[f"pred_{m}"] - out["y"]
        out[f"abs_{m}"] = out[f"err_{m}"].abs()
    return out


def top_stations(frame: pd.DataFrame, model: str, names: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Stations with the highest MAE at +60 and their characteristics (question 1)."""
    h60 = frame[frame["horizon_min"] == 60]
    grouped = h60.groupby("station_key")
    table = pd.DataFrame(
        {
            "mae": grouped[f"abs_{model}"].mean(),
            "mae_persistence": grouped["abs_persistence"].mean(),
            "capacity": grouped["capacity"].median(),
            "mean_bikes": grouped["y"].mean(),
            "share_empty": grouped["y"].apply(lambda s: float((s == 0).mean())),
            "share_rebalance": grouped["rebalance_flag"].mean(),
            "abs_change_4": grouped["change_4"].apply(lambda s: float(s.abs().mean())),
        }
    ).sort_values("mae", ascending=False)
    table = table.head(n).reset_index().merge(names, on="station_key", how="left")
    cols = ["station_key", "name", "mae", "mae_persistence", "capacity", "mean_bikes",
            "share_empty", "share_rebalance", "abs_change_4"]  # fmt: skip
    return table[cols]


def hour_station_heatmap(frame: pd.DataFrame, model: str, path: Path) -> None:
    """Station x local hour MAE at +60 (question 2)."""
    h60 = frame[frame["horizon_min"] == 60]
    pivot = h60.pivot_table(
        index="station_key", columns="hour", values=f"abs_{model}", aggfunc="mean"
    )
    pivot = pivot.reindex(columns=[str(h) for h in range(24)])
    pivot = pivot.loc[pivot.mean(axis=1).sort_values(ascending=False).index]
    fig, ax = plt.subplots(figsize=(10, 12))
    image = ax.imshow(pivot.to_numpy(), aspect="auto", cmap="magma")
    ax.set_xticks(range(0, 24, 2), [str(h) for h in range(0, 24, 2)])
    ax.set_yticks([])
    ax.set_xlabel("local hour of target")
    ax.set_ylabel(f"{len(pivot)} stations, sorted by MAE (top = worst)")
    ax.set_title(f"{model} MAE at +60 by station and hour")
    fig.colorbar(image, ax=ax, label="MAE (bikes)")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=100)
    plt.close(fig)


def error_vs_change(frame: pd.DataFrame, model: str) -> pd.DataFrame:
    """Bias and MAE by recent change ``bikes(t) - bikes(t-60)`` at +60 (question 3)."""
    h60 = frame[frame["horizon_min"] == 60].copy()
    h60["recent_change"] = pd.cut(h60["change_4"], CHANGE_BINS, labels=CHANGE_LABELS)
    grouped = h60.groupby("recent_change", observed=True)
    return pd.DataFrame(
        {
            "rows": grouped.size(),
            f"bias_{model}": grouped[f"err_{model}"].mean(),
            f"mae_{model}": grouped[f"abs_{model}"].mean(),
            "bias_persistence": grouped["err_persistence"].mean(),
            "mae_persistence": grouped["abs_persistence"].mean(),
        }
    ).reset_index()


def horizon_growth(frame: pd.DataFrame, models: Sequence[str]) -> pd.DataFrame:
    """MAE per horizon (question 4)."""
    grouped = frame.groupby("horizon_min")
    return pd.DataFrame({m: grouped[f"abs_{m}"].mean() for m in models}).reset_index()


def large_error_rebalance(frame: pd.DataFrame, models: Sequence[str]) -> pd.DataFrame:
    """Share of |error| > 5 bikes whose target bucket is rebalance-flagged (question 5)."""
    rows = []
    base = float(frame["rebalance_flag"].mean())
    for m in models:
        large = frame[frame[f"abs_{m}"] > LARGE_ERROR]
        rows.append(
            {
                "model": m,
                "large_errors": len(large),
                "share_of_rows": len(large) / len(frame),
                "share_rebalance_flagged": float(large["rebalance_flag"].mean())
                if len(large)
                else np.nan,
                "flagged_share_all_rows": base,
            }
        )
    return pd.DataFrame(rows)


def weekday_weekend(frame: pd.DataFrame, models: Sequence[str]) -> pd.DataFrame:
    """MAE weekday vs weekend per horizon (question 6)."""
    grouped = frame.groupby(["horizon_min", "weekend"])
    return pd.DataFrame({m: grouped[f"abs_{m}"].mean() for m in models}).reset_index()


def metric_row(part: pd.DataFrame, models: Sequence[str]) -> dict[str, float]:
    """Rows, then MAE, RMSE, MASE, bias and P10-P90 coverage per model (PRD 13.2)."""
    persistence_mae = metrics.mae(part["y"], part["pred_persistence"])
    row: dict[str, float] = {"rows": float(len(part))}
    for m in models:
        short = m.removeprefix("lgbm_")
        model_mae = metrics.mae(part["y"], part[f"pred_{m}"])
        row[f"mae_{short}"] = model_mae
        row[f"rmse_{short}"] = metrics.rmse(part["y"], part[f"pred_{m}"])
        row[f"mase_{short}"] = metrics.mase(model_mae, persistence_mae)
        row[f"bias_{short}"] = metrics.bias(part["y"], part[f"pred_{m}"])
        row[f"cov_{short}"] = (
            metrics.coverage(part["y"], part[f"p10_{m}"], part[f"p90_{m}"])
            if f"p10_{m}" in part.columns
            else np.nan
        )
    return row


def slice_order(value: object) -> tuple[int, float, str]:
    """Sort key: ``<20`` first, then numbers by value (``20-29`` < ``40+``), then text."""
    label = str(value)
    if label.startswith("<"):
        return (0, -1.0, label)
    number = re.match(r"\d+", label)
    return (0, float(number.group()), label) if number else (1, 0.0, label)


def slice_metrics(frame: pd.DataFrame, models: Sequence[str]) -> pd.DataFrame:
    """PRD 13.3 slices: overall per horizon, then each slice at +60.

    Args:
        frame: Scored rows with ``pred_<m>`` (and ``p10_/p90_<m>`` for interval models).
        models: Models to report.

    Returns:
        Columns ``slice, value, rows`` then the :func:`metric_row` metrics.
    """
    records: list[dict[str, object]] = []
    for horizon, part in frame.groupby("horizon_min"):
        records.append({"slice": "horizon", "value": f"+{horizon}", **metric_row(part, models)})
    rows = frame[frame["horizon_min"] == SLICE_HORIZON].assign(
        rebalance=lambda f: np.where(f["rebalance_flag"], "flagged", "normal")
    )
    for column in SLICE_COLUMNS:
        if column not in rows.columns:
            continue
        values = sorted(rows[column].unique(), key=slice_order)
        for value in values:
            part = rows[rows[column] == value]
            records.append({"slice": column, "value": str(value), **metric_row(part, models)})
    table = pd.DataFrame(records)
    table["rows"] = table["rows"].astype(int)
    return table


def champions(frame: pd.DataFrame, models: Sequence[str]) -> pd.DataFrame:
    """PRD 12.5 champion per horizon from the fold-mean MAE and coverage of ``models``."""
    records: list[dict[str, object]] = []
    for (horizon, fold), part in frame.groupby(["horizon_min", "fold"]):
        for m in models:
            records.append(
                {
                    "horizon_min": horizon,
                    "fold": fold,
                    "model_name": m,
                    "mae": metrics.mae(part["y"], part[f"pred_{m}"]),
                    "coverage_80": metrics.coverage(part["y"], part[f"p10_{m}"], part[f"p90_{m}"])
                    if f"p10_{m}" in part.columns
                    else np.nan,
                }
            )
    summary = (
        pd.DataFrame(records)
        .groupby(["horizon_min", "model_name"], as_index=False)[["mae", "coverage_80"]]
        .mean()
    )
    return select_champions(summary)


def analysis_json(
    frame: pd.DataFrame,
    run_id: str,
    e2_run: str | None,
    names: pd.DataFrame,
    folds: list[dict[str, object]],
    model: str = "lgbm_global",
) -> dict[str, object]:
    """The slices ``GET /v1/model/error-analysis`` serves (PRD 16.5).

    Args:
        frame: Scored rows (as for :func:`build_report`).
        run_id: E1 MLflow run id.
        e2_run: E2 MLflow run id joined onto ``frame``, if any.
        names: ``station_key, name``.
        folds: ``reports/folds.json`` entries.
        model: Main model for the heatmap.

    Returns:
        JSON-ready dict matching ``dockcast.api.schemas.ErrorAnalysis``.
    """
    present = [m for m in (model, V2_MODEL, "persistence", "ridge") if f"pred_{m}" in frame.columns]
    scored = add_errors(frame, present)
    growth = horizon_growth(scored, present).melt(
        id_vars="horizon_min", var_name="model_name", value_name="mae"
    )
    h60 = scored[scored["horizon_min"] == 60]
    pivot = h60.pivot_table(index="station_key", columns="hour", values=f"abs_{model}")
    hours = list(range(24))
    pivot = pivot.reindex(columns=[str(h) for h in hours])
    pivot = pivot.loc[pivot.mean(axis=1).sort_values(ascending=False).index]
    name_of = names.set_index("station_key")["name"]
    heatmap = [
        {
            "station_key": int(key),
            "name": str(name_of.get(key, key)),
            "mae": [None if pd.isna(v) else round(float(v), 4) for v in values],
        }
        for key, values in zip(pivot.index, pivot.to_numpy(), strict=True)
    ]
    return {
        "run_id": run_id,
        "e2_run_id": e2_run,
        "git_commit": git_commit(),
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "folds": folds,
        "horizon_growth": [
            {"horizon_min": int(horizon), "model_name": str(name), "mae": float(mae)}
            for horizon, name, mae in zip(
                growth["horizon_min"].to_numpy(dtype=int),
                growth["model_name"].astype(str),
                growth["mae"].to_numpy(dtype=float),
                strict=True,
            )
        ],
        "heatmap_hours": hours,
        "heatmap": heatmap,
    }


def station_names(engine: Engine) -> pd.DataFrame:
    """``station_key, name``."""
    with engine.connect() as conn:
        return pd.read_sql(text("SELECT station_key, name FROM stations"), conn)


def build_report(
    frame: pd.DataFrame,
    run_id: str,
    names: pd.DataFrame,
    model: str = "lgbm_global",
    e2_run: str | None = None,
) -> str:
    """Render the report (writes the heatmap figure).

    Args:
        frame: Scored rows from an E1 predictions file, joined with :func:`add_e2` when
            ``e2_run`` is given.
        run_id: MLflow run id of that E1 run.
        names: ``station_key, name``.
        model: Main model.
        e2_run: MLflow run id of the E2 run joined onto ``frame``, if any.

    Returns:
        Markdown.
    """
    present = [m for m in (model, V2_MODEL, "persistence", "ridge") if f"pred_{m}" in frame.columns]
    interval_models = [m for m in (model, V2_MODEL) if m in present]
    frame = add_errors(frame, present)
    heatmap = FIGURES / "err_station_hour.png"
    hour_station_heatmap(frame, model, heatmap)
    folds = sorted(frame["fold"].unique())
    runs = f"MLflow run `{run_id}` (E1)"
    if e2_run:
        runs += f" and `{e2_run}` (E2: `{V2_MODEL}` and the in-fold E3 cluster on the same rows)"
    return "\n".join(
        [
            "# Error analysis (v2)",
            "",
            f"{runs} · git `{git_commit()}` · {len(frame)} scored test rows, "
            f"folds {folds[0]}-{folds[-1]}, horizons "
            f"{', '.join(f'+{h}' for h in sorted(frame['horizon_min'].unique()))} · target "
            f"{frame['target_ts'].min():%Y-%m-%d} → {frame['target_ts'].max():%Y-%m-%d} UTC. "
            f"Main model `{model}`; errors are prediction - actual (bikes). No weather features.",
            "",
            "## 1. Top 10 stations by MAE (+60)",
            "",
            md_table(top_stations(frame, model, names)),
            "",
            "## 2. Error by station and hour (+60)",
            "",
            f"![](figures/{heatmap.name})",
            "",
            "## 3. Do we under-predict sharp changes? Error vs change over the last hour (+60)",
            "",
            "Recent change = bikes(t) - bikes(t - 60 min). Negative bias = under-prediction.",
            "",
            md_table(error_vs_change(frame, model)),
            "",
            "## 4. Error growth with horizon (MAE, bikes)",
            "",
            md_table(horizon_growth(frame, present)),
            "",
            f"## 5. Large errors (|error| > {LARGE_ERROR:g} bikes) and rebalancing",
            "",
            md_table(large_error_rebalance(frame, present)),
            "",
            "## 6. Weekday vs weekend (MAE, bikes)",
            "",
            md_table(weekday_weekend(frame, present)),
            "",
            "## 7. Metrics by slice (PRD 13.3)",
            "",
            f"Horizon rows use every test row; the other slices are at +{SLICE_HORIZON}. MASE is "
            "against persistence on the same rows; `cov` is P10-P90 coverage (target 0.80). "
            "Hours are local; rush hour is 07-10 and 16-19 local; `rebalance` is whether the "
            "target bucket is rebalance-flagged. Per-station errors are in sections 1-2.",
            "",
            md_table(slice_metrics(frame, interval_models)),
            "",
            "## 8. Champion per horizon (PRD 12.5)",
            "",
            "Lowest fold-mean MAE among models with fold-mean coverage in [0.70, 0.90]; a simpler "
            f"model within 1 % wins the tie (`{V2_MODEL}` counts as less simple than "
            "`lgbm_global`). The API keeps serving `lgbm_global` until the owner decides to "
            "switch.",
            "",
            md_table(champions(frame, present)),
            "",
        ]
    )


def main(argv: Sequence[str] | None = None) -> None:
    """``make error-analysis`` (latest E1 and E2 predictions unless ``--run``/``--e2-run``)."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default=None, help="E1 MLflow run id")
    parser.add_argument("--e2-run", default=None, help="E2 MLflow run id")
    args = parser.parse_args(argv)
    folder = get_env_settings().data_dir / "processed"
    if args.run:
        path, run_id = folder / f"e1_predictions_{args.run}.parquet", args.run
    else:
        path, run_id = latest_predictions("e1")
    if args.e2_run:
        e2_path, e2_run = folder / f"e2_predictions_{args.e2_run}.parquet", args.e2_run
    else:
        e2_path, e2_run = latest_predictions("e2")
    frame = add_e2(pd.read_parquet(path), pd.read_parquet(e2_path))
    names = station_names(make_engine())
    text_out = build_report(frame, run_id, names, e2_run=e2_run)
    (REPORTS / "error_analysis.md").write_text(text_out, encoding="utf-8")
    folds = json.loads((REPORTS / "folds.json").read_text(encoding="utf-8"))
    payload = analysis_json(frame, run_id, e2_run, names, folds)
    (REPORTS / "error_analysis.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
