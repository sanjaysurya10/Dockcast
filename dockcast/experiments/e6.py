"""E6 — uncertainty quality of the champion's P10-P90 intervals (PRD 14 E6, RQ6, M11).

``make backtest E=E6``. No retraining: reads the E1 ``lgbm_global`` predictions (deterministic,
M6) and the in-fold E3 cluster labels, then reports per horizon and slice (local hour of the
target, cluster, weekday/weekend, rush hour, capacity band):

- coverage of P10-P90 (target 0.80) and mean width;
- calibration of each quantile: share of targets strictly below P10 and strictly above P90
  (targets 0.10 each), strictly below / above P50 (at most 0.50 each; the target is a whole
  number of bikes, so exact ties are common), and each quantile's pinball loss;
- per-station coverage spread (how many stations fall inside 0.70-0.90, the champion band).

Writes MLflow (experiment ``E6``), the E6 section of ``reports/experiments.md`` and
``reports/figures/e6_coverage_by_hour.png``.
"""

import argparse
from collections.abc import Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import mlflow
import numpy as np
import pandas as pd
import structlog
from sqlalchemy.orm import Session

from dockcast.db.engine import make_engine
from dockcast.evaluation.reports import REPORTS, generated_line, git_commit, replace_section
from dockcast.evaluation.splits import Fold
from dockcast.experiments.e1 import default_folds
from dockcast.experiments.e3 import GRID, INK, MUTED, SERIES, SURFACE
from dockcast.experiments.e4 import latest_run
from dockcast.quality.gaps import load_gaps
from dockcast.tracking import setup_mlflow

log = structlog.get_logger(job="e6")
EXPERIMENT = "E6"
FIGURES = REPORTS / "figures"
MODEL = "lgbm_global"
QUANTILE_COLUMNS = {0.1: f"p10_{MODEL}", 0.5: f"pred_{MODEL}", 0.9: f"p90_{MODEL}"}
SLICES = ("hour", "cluster", "weekend", "rush_hour", "capacity_band")
BAND = (0.70, 0.90)


def pinball(y: np.ndarray, pred: np.ndarray, q: float) -> float:
    """Mean pinball (quantile) loss of ``pred`` at quantile ``q``."""
    diff = y - pred
    return float(np.mean(np.maximum(q * diff, (q - 1) * diff)))


def calibration(rows: pd.DataFrame) -> dict[str, float]:
    """Interval and per-quantile calibration metrics for one group of rows.

    Args:
        rows: Rows with ``y`` and the :data:`QUANTILE_COLUMNS`.

    Returns:
        ``n, coverage, width, below_10, below_50, above_50, above_90`` and ``pinball_q``.
    """
    y = rows["y"].to_numpy(dtype=float)
    p10 = rows[QUANTILE_COLUMNS[0.1]].to_numpy(dtype=float)
    p90 = rows[QUANTILE_COLUMNS[0.9]].to_numpy(dtype=float)
    out = {
        "n": float(len(rows)),
        "coverage": float(np.mean((y >= p10) & (y <= p90))),
        "width": float(np.mean(p90 - p10)),
    }
    p50 = rows[QUANTILE_COLUMNS[0.5]].to_numpy(dtype=float)
    out["below_10"] = float(np.mean(y < p10))
    out["below_50"] = float(np.mean(y < p50))
    out["above_50"] = float(np.mean(y > p50))
    out["above_90"] = float(np.mean(y > p90))
    for q, col in QUANTILE_COLUMNS.items():
        out[f"pinball_{int(q * 100)}"] = pinball(y, rows[col].to_numpy(dtype=float), q)
    return out


def calibration_table(rows: pd.DataFrame) -> pd.DataFrame:
    """Calibration per fold, horizon and slice (``overall`` plus :data:`SLICES`).

    Args:
        rows: E1 predictions with ``fold, horizon_min``, ``cluster`` and the slice columns.

    Returns:
        One row per ``fold, horizon_min, slice_kind, slice_value``.
    """
    records = []
    for kind in ("overall", *SLICES):
        keys = ["fold", "horizon_min"] if kind == "overall" else ["fold", "horizon_min", kind]
        for key, part in rows.groupby(keys, observed=True):
            fold, horizon = int(str(key[0])), int(str(key[1]))
            value = "all" if kind == "overall" else str(key[2])
            records.append(
                {
                    "fold": fold,
                    "horizon_min": horizon,
                    "slice_kind": kind,
                    "slice_value": value,
                    **calibration(part),
                }
            )
    return pd.DataFrame(records)


def station_coverage(rows: pd.DataFrame) -> pd.DataFrame:
    """P10-P90 coverage per station and horizon over all folds."""
    inside = (rows["y"] >= rows[QUANTILE_COLUMNS[0.1]]) & (rows["y"] <= rows[QUANTILE_COLUMNS[0.9]])
    return (
        rows.assign(inside=inside)
        .groupby(["horizon_min", "station_key"])["inside"]
        .mean()
        .rename("coverage")
        .reset_index()
    )


def mean_over_folds(table: pd.DataFrame) -> pd.DataFrame:
    """Mean of every metric over folds, per horizon and slice."""
    metrics = [c for c in table.columns if c not in ("fold", "horizon_min", "slice_kind")]
    metrics.remove("slice_value")
    return table.groupby(["horizon_min", "slice_kind", "slice_value"])[metrics].mean().reset_index()


def plot_coverage_by_hour(table: pd.DataFrame, path: Path) -> None:
    """Coverage and width by local target hour, one line per horizon."""
    part = mean_over_folds(table)
    part = part[part["slice_kind"] == "hour"].assign(hour=lambda d: d["slice_value"].astype(int))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), facecolor=SURFACE)
    for color, (h, rows) in zip(SERIES, part.groupby("horizon_min"), strict=False):
        rows = rows.sort_values("hour")
        axes[0].plot(rows["hour"], rows["coverage"], color=color, lw=2, label=f"+{h} min")
        axes[1].plot(rows["hour"], rows["width"], color=color, lw=2, label=f"+{h} min")
    axes[0].axhspan(*BAND, color=GRID, alpha=0.5, lw=0, label="champion band 0.70-0.90")
    axes[0].axhline(0.8, color=MUTED, lw=1, ls="--")
    axes[0].set_ylabel("P10-P90 coverage", color=MUTED)
    axes[1].set_ylabel("Mean P10-P90 width (bikes)", color=MUTED)
    for ax, title in zip(axes, ("Coverage", "Width"), strict=True):
        ax.set_title(title, color=INK, fontsize=12, loc="left")
        ax.set_xlabel("Local hour of target", color=MUTED)
        ax.set_xticks(range(0, 24, 3))
        ax.grid(axis="y", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(colors=MUTED, length=0)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
    axes[0].legend(frameon=False, fontsize=9, labelcolor=INK, loc="lower left")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


def _row(h: int, label: str, rec: pd.Series) -> str:
    return (
        f"| +{h} | {label} | {rec['coverage']:.3f} | {rec['width']:.2f} | "
        f"{rec['below_10']:.3f} | {rec['above_90']:.3f} | {rec['below_50']:.3f} | "
        f"{rec['above_50']:.3f} | "
        f"{rec['pinball_10']:.3f} | {rec['pinball_50']:.3f} | {rec['pinball_90']:.3f} |"
    )


def render_section(
    run_id: str,
    e1_run: str,
    e3_run: str,
    folds: Sequence[Fold],
    table: pd.DataFrame,
    stations: pd.DataFrame,
) -> str:
    """The E6 section of ``reports/experiments.md``."""
    means = mean_over_folds(table)
    header = [
        "| horizon | slice | coverage P10-P90 | width | < P10 | > P90 | < P50 | > P50 | "
        "pinball P10 | pinball P50 | pinball P90 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    overall = means[means["slice_kind"] == "overall"].set_index("horizon_min")
    fold_cov = table[table["slice_kind"] == "overall"].groupby("horizon_min")["coverage"]
    lines = [
        "## E6 — Uncertainty quality (P10-P90 of the champion)",
        "",
        generated_line(run_id, folds[0].test_start, folds[-1].test_end),
        "",
        f"`{MODEL}` P10 / P50 / P90 from E1 run `{e1_run}` (no retraining), all 8 folds, every "
        f"15-min issue time on the test weeks; clusters from E3 run `{e3_run}`, fitted before "
        "each fold. Targets: coverage 0.80; share strictly below P10 and strictly above P90 "
        "0.10 each; strictly below / above P50 at most 0.50 each (targets are whole bikes, so "
        "exact ties with a quantile are common). Means over folds. **No weather.**",
        "",
        *header,
    ]
    for h, rec in overall.iterrows():
        lines.append(_row(int(str(h)), "all", rec))
    lines += [
        "",
        "Coverage range over folds: "
        + "; ".join(f"+{h}: {float(v.min()):.3f}-{float(v.max()):.3f}" for h, v in fold_cov)
        + ".",
        "",
        "Per-station coverage (all folds pooled):",
        "",
        "| horizon | stations | min | median | max | inside 0.70-0.90 | below 0.70 | above 0.90 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for h, part in stations.groupby("horizon_min"):
        cov = part["coverage"]
        lines.append(
            f"| +{int(str(h))} | {len(cov)} | {cov.min():.3f} | {cov.median():.3f} | "
            f"{cov.max():.3f} | "
            f"{int(cov.between(*BAND).sum())} | {int((cov < BAND[0]).sum())} | "
            f"{int((cov > BAND[1]).sum())} |"
        )
    lines += [
        "",
        "![Coverage and width by local hour](figures/e6_coverage_by_hour.png)",
        "",
        "Calibration by slice, mean over folds:",
        "",
        *header,
    ]
    for kind in SLICES:
        part = means[means["slice_kind"] == kind]
        order = (
            part.assign(key=pd.to_numeric(part["slice_value"], errors="coerce"))
            if kind in ("hour", "cluster")
            else part.assign(key=part["slice_value"])
        ).sort_values(["horizon_min", "key"])
        for record in order.to_dict("records"):
            lines.append(
                _row(
                    int(record["horizon_min"]),
                    f"{kind} {record['slice_value']}",
                    pd.Series(record),
                )
            )
    lines.append("")
    return "\n".join(lines)


def load_rows(e1_file: str, labels: pd.DataFrame) -> pd.DataFrame:
    """E1 predictions with the in-fold cluster of each station (``none`` if unlabelled)."""
    rows = pd.read_parquet(e1_file)
    rows = rows.merge(labels, on=["station_key", "fold"], how="left")
    rows["cluster"] = rows["cluster_id"].map(lambda c: "none" if pd.isna(c) else str(int(c)))
    return rows.drop(columns="cluster_id")


def main(argv: Sequence[str] | None = None) -> None:
    """``make backtest E=E6``."""
    argparse.ArgumentParser().parse_args(argv)
    engine = make_engine()
    with Session(engine) as session:
        gaps = load_gaps(session)
    folds = default_folds(engine, gaps)
    setup_mlflow("E1")
    e1_run, e1_file = latest_run("E1", "predictions_file")
    setup_mlflow("E3")
    e3_run, e3_file = latest_run("E3", "fold_labels_file")
    rows = load_rows(e1_file, pd.read_parquet(e3_file))
    table = calibration_table(rows)
    stations = station_coverage(rows)
    setup_mlflow(EXPERIMENT)
    with mlflow.start_run(run_name="e6") as active:
        run_id = active.info.run_id
        mlflow.log_params(
            {
                "model": MODEL,
                "source_e1_run": e1_run,
                "cluster_e3_run": e3_run,
                "n_folds": int(rows["fold"].nunique()),
                "git_commit": git_commit(),
                "data_source": "hist_b",
            }
        )
        overall = mean_over_folds(table)
        for rec in overall[overall["slice_kind"] == "overall"].to_dict("records"):
            h = int(rec["horizon_min"])
            mlflow.log_metric(f"coverage80_h{h}", float(rec["coverage"]))
            mlflow.log_metric(f"width_h{h}", float(rec["width"]))
        mlflow.log_metric("rows", len(rows))
        mlflow.log_text(table.to_csv(index=False), "calibration.csv")
        mlflow.log_text(stations.to_csv(index=False), "station_coverage.csv")
    plot_coverage_by_hour(table, FIGURES / "e6_coverage_by_hour.png")
    section = render_section(run_id, e1_run, e3_run, folds, table, stations)
    replace_section(REPORTS / "experiments.md", EXPERIMENT, section)
    log.info("e6_done", run_id=run_id, rows=len(rows))


if __name__ == "__main__":
    main()
