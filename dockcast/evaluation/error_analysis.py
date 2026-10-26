"""Error analysis (PRD 13.4) → ``reports/error_analysis.md`` + ``reports/figures/err_*.png``.

Reads the scored test rows saved by an E1 run (``data/processed/e1_predictions_<run>.parquet``)
and answers the six PRD 13.4 questions for the main model (default ``lgbm_global``) with
persistence alongside. Every number comes from that file, so the report cites its MLflow run.
"""

import argparse
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
from dockcast.evaluation.reports import REPORTS, git_commit
from dockcast.quality.eda import md_table

FIGURES = REPORTS / "figures"
LARGE_ERROR = 5.0
CHANGE_BINS = [-1000, -6, -2, 1, 5, 1000]
CHANGE_LABELS = ["<= -6", "-5..-2", "-1..+1", "+2..+5", ">= +6"]


def latest_predictions() -> tuple[Path, str]:
    """Newest E1 predictions file and its run id."""
    folder = get_env_settings().data_dir / "processed"
    files = sorted(folder.glob("e1_predictions_*.parquet"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"no e1_predictions_*.parquet in {folder}")
    path = files[-1]
    return path, path.stem.removeprefix("e1_predictions_")


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


def station_names(engine: Engine) -> pd.DataFrame:
    """``station_key, name``."""
    with engine.connect() as conn:
        return pd.read_sql(text("SELECT station_key, name FROM stations"), conn)


def build_report(
    frame: pd.DataFrame, run_id: str, names: pd.DataFrame, model: str = "lgbm_global"
) -> str:
    """Render the report (writes the heatmap figure).

    Args:
        frame: Scored rows from an E1 predictions file.
        run_id: MLflow run id of that E1 run.
        names: ``station_key, name``.
        model: Main model.

    Returns:
        Markdown.
    """
    models = [m for m in (model, "persistence", "ridge") if f"pred_{m}" in frame.columns]
    frame = add_errors(frame, models)
    heatmap = FIGURES / "err_station_hour.png"
    hour_station_heatmap(frame, model, heatmap)
    folds = sorted(frame["fold"].unique())
    return "\n".join(
        [
            "# Error analysis (v1)",
            "",
            f"MLflow run `{run_id}` (E1) · git `{git_commit()}` · {len(frame)} scored test rows, "
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
            md_table(horizon_growth(frame, models)),
            "",
            f"## 5. Large errors (|error| > {LARGE_ERROR:g} bikes) and rebalancing",
            "",
            md_table(large_error_rebalance(frame, models)),
            "",
            "## 6. Weekday vs weekend (MAE, bikes)",
            "",
            md_table(weekday_weekend(frame, models)),
            "",
        ]
    )


def main(argv: Sequence[str] | None = None) -> None:
    """``make error-analysis`` (latest E1 predictions unless ``--run`` is given)."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default=None, help="E1 MLflow run id")
    args = parser.parse_args(argv)
    if args.run:
        path = get_env_settings().data_dir / "processed" / f"e1_predictions_{args.run}.parquet"
        run_id = args.run
    else:
        path, run_id = latest_predictions()
    frame = pd.read_parquet(path)
    text_out = build_report(frame, run_id, station_names(make_engine()))
    (REPORTS / "error_analysis.md").write_text(text_out, encoding="utf-8")


if __name__ == "__main__":
    main()
