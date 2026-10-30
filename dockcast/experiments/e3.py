"""E3 — station behaviour groups (PRD 13, 14): k-means and Ward on occupancy profiles.

``make backtest E=E3``. Profiles use Format A + B (PRD 9.1a). Stability is reported two ways
(owner decision 2026-10-30): pairwise ARI of labels fitted on data before each E1 fold's training
end (the in-fold labels later experiments use), and ARI between disjoint periods (Format A only vs
Format B only). Writes MLflow (experiment ``E3``), the E3 section of ``reports/experiments.md``,
figures, per-fold labels (``data/processed/e3_fold_labels_<run>.parquet``) and
``stations.cluster_id`` from the final fit.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import numpy as np
import pandas as pd
import structlog
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from dockcast.config import ClusteringConfig, get_env_settings, load_project_config
from dockcast.db.engine import make_engine
from dockcast.evaluation.reports import REPORTS, generated_line, git_commit, replace_section
from dockcast.evaluation.splits import Fold
from dockcast.experiments.e1 import default_folds
from dockcast.features.station import DAY_TYPES, load_profile_cells, profile_matrix
from dockcast.models.clustering import (
    ari,
    fit_kmeans,
    fit_ward,
    pairwise_ari,
    silhouette,
)
from dockcast.quality.gaps import load_gaps
from dockcast.tracking import setup_mlflow

log = structlog.get_logger(job="e3")
EXPERIMENT = "E3"
FIGURES = REPORTS / "figures"
# Categorical slots in fixed order (dataviz reference palette, light surface).
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, MUTED, GRID, SURFACE = "#15201B", "#5A6560", "#DDE2DE", "#FFFFFF"


@dataclass(frozen=True)
class Periods:
    """Data windows used by E3 (UTC, end exclusive)."""

    a_start: datetime
    a_end: datetime
    b_start: datetime
    final_end: datetime


@dataclass(frozen=True)
class KScore:
    """Selection and stability scores for one k."""

    k: int
    silhouette: float
    fold_ari_mean: float
    fold_ari_min: float
    period_ari: float
    period_shared: int
    ward_ari: float


def source_span(engine: Engine, source: str) -> tuple[datetime, datetime]:
    """First and last raw observation of ``source`` (UTC)."""
    with engine.connect() as conn:
        lo, hi = conn.execute(
            text(
                "SELECT min(observed_at), max(observed_at) FROM station_status_raw "
                "WHERE source = :source"
            ),
            {"source": source},
        ).one()
    return lo.astimezone(UTC), hi.astimezone(UTC)


def periods(engine: Engine, folds: Sequence[Fold]) -> Periods:
    """Format A span, Format B start and the final fit end (last E1 test end)."""
    a_start, a_end = source_span(engine, "hist_a")
    b_start, _ = source_span(engine, "hist_b")
    return Periods(a_start, a_end, b_start, folds[-1].test_end)


def score_k(
    k: int,
    final: pd.DataFrame,
    fold_profiles: Sequence[pd.DataFrame],
    a_profiles: pd.DataFrame,
    b_profiles: pd.DataFrame,
    seed: int,
) -> KScore:
    """Silhouette on the final profiles, fold and period stability, k-means vs Ward agreement."""
    labels = fit_kmeans(final, k, seed)
    fold_scores = pairwise_ari([fit_kmeans(p, k, seed) for p in fold_profiles])
    period, shared = ari(fit_kmeans(a_profiles, k, seed), fit_kmeans(b_profiles, k, seed))
    ward, _ = ari(labels, fit_ward(final, k))
    return KScore(
        k,
        silhouette(final, labels),
        float(np.mean(fold_scores)),
        float(np.min(fold_scores)),
        period,
        shared,
        ward,
    )


def choose_k(scores: Sequence[KScore]) -> int:
    """Highest silhouette; ties go to the more stable (higher period ARI) k."""
    return max(scores, key=lambda s: (round(s.silhouette, 3), s.period_ari)).k


def representatives(
    profiles: pd.DataFrame, labels: pd.Series, names: pd.Series, n: int = 3
) -> dict[int, list[str]]:
    """The ``n`` stations closest to each cluster centroid."""
    out: dict[int, list[str]] = {}
    for cluster, members in profiles.groupby(labels):
        centre = members.mean(axis=0)
        dist = ((members - centre) ** 2).sum(axis=1).sort_values()
        out[int(cluster)] = [str(names.get(s, s)) for s in dist.index[:n]]
    return out


def plot_profiles(profiles: pd.DataFrame, labels: pd.Series, path: str) -> None:
    """Mean weekday and weekend occupancy by local hour, one line per cluster."""
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True, facecolor=SURFACE)
    hours = np.arange(24)
    for ax, day in zip(axes, DAY_TYPES, strict=True):
        cols = [f"{day}_{h:02d}" for h in hours]
        for cluster, members in profiles.groupby(labels):
            ax.plot(
                hours,
                members[cols].mean(axis=0).to_numpy(),
                color=SERIES[int(cluster)],
                lw=2,
                label=f"Cluster {int(cluster)} ({len(members)} stations)",
            )
        ax.set_title(day.capitalize(), color=INK, fontsize=12, loc="left")
        ax.set_xticks(range(0, 24, 3))
        ax.set_xticklabels([f"{h:02d}:00" for h in range(0, 24, 3)])
        ax.set_xlim(0, 23)
        ax.set_ylim(0, 1)
        ax.grid(axis="y", color=GRID, lw=0.8)
        ax.tick_params(colors=MUTED, length=0)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
    axes[0].set_ylabel("Mean occupancy (bikes / capacity)", color=MUTED)
    axes[1].legend(frameon=False, fontsize=9, labelcolor=INK, loc="upper right")
    fig.supxlabel("Local hour (Europe/Dublin)", color=MUTED, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=120, facecolor=SURFACE)
    plt.close(fig)


def plot_map(info: pd.DataFrame, labels: pd.Series, path: str) -> None:
    """Station locations coloured by cluster; unclustered stations in grey."""
    fig, ax = plt.subplots(figsize=(9, 6), facecolor=SURFACE)
    joined = info.set_index("station_key").join(labels, how="left")
    for cluster in sorted(int(c) for c in labels.unique()):
        part = joined[joined["cluster_id"] == cluster]
        ax.scatter(part.lon, part.lat, s=48, c=SERIES[cluster], edgecolors=SURFACE, lw=1,
                   label=f"Cluster {cluster} ({len(part)})")  # fmt: skip
    missing = joined[joined["cluster_id"].isna()]
    if len(missing):
        ax.scatter(missing.lon, missing.lat, s=70, marker="D", facecolors=SURFACE, edgecolors=INK,
                   lw=1.5, zorder=3, label=f"Not clustered ({len(missing)})")  # fmt: skip
    ax.set_aspect(1 / np.cos(np.radians(float(joined.lat.mean()))))
    ax.set_xlabel("Longitude", color=MUTED)
    ax.set_ylabel("Latitude", color=MUTED)
    ax.tick_params(colors=MUTED, length=0, labelsize=8)
    for side in ax.spines.values():
        side.set_color(GRID)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK, loc="upper left")
    ax.set_title(
        "Station clusters (no basemap). Data: Dublin City Council / Smart Dublin, CC BY 4.0",
        color=MUTED, fontsize=9, loc="left",
    )  # fmt: skip
    fig.savefig(path, dpi=120, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


def render_section(
    run_id: str,
    span: Periods,
    cfg: ClusteringConfig,
    scores: Sequence[KScore],
    k: int,
    final: pd.DataFrame,
    labels: pd.Series,
    reps: dict[int, list[str]],
    dropped: Sequence[str],
    n_folds: int,
) -> str:
    """The E3 section of ``reports/experiments.md``."""
    lines = [
        "## E3 — Station behaviour groups (k-means, Ward)",
        "",
        generated_line(run_id, span.a_start, span.final_end),
        "",
        "Profiles: mean occupancy (bikes / capacity in force) per local hour, weekdays (Mon-Fri) "
        "and weekends (Sat-Sun) separately, 48 values per station; observed, open, non-imputed, "
        "non-flat-lined 15-min states of Format A + B (PRD 9.1a). Stations with any cell under "
        f"{cfg.min_cell_obs} states are left out. K-means (n_init 20, seed {cfg.seed}) for "
        f"k = {cfg.k_min}-{cfg.k_max}; Ward at the same k. k is chosen by silhouette on the final "
        "profiles (data to the end of the last E1 test week).",
        "",
        f"Stability: **fold ARI** = pairwise adjusted Rand index of labels fitted on data before "
        f"each of the {n_folds} E1 fold training ends (folds differ by one week on top of years "
        f"of data, so this is expected to be high); **period ARI** = labels from Format A only "
        f"({span.a_start:%Y-%m} to {span.a_end:%Y-%m}) vs Format B only ({span.b_start:%Y-%m} to "
        f"{span.final_end:%Y-%m}), on stations in both: the stronger test.",
        "",
        "| k | silhouette | fold ARI mean | fold ARI min | period ARI (A vs B) "
        "| k-means vs Ward ARI |",
        "|---:|---:|---:|---:|---:|---:|",
    ]  # fmt: skip
    for s in scores:
        mark = " **(chosen)**" if s.k == k else ""
        lines.append(
            f"| {s.k}{mark} | {s.silhouette:.3f} | {s.fold_ari_mean:.3f} | {s.fold_ari_min:.3f} "
            f"| {s.period_ari:.3f} | {s.ward_ari:.3f} |"
        )
    chosen = next(s for s in scores if s.k == k)
    lines += [
        "",
        f"Stations clustered: {len(final)}; period ARI on {chosen.period_shared} stations in both "
        f"formats." + (f" Left out: {', '.join(dropped)}." if dropped else ""),
        "",
        f"At k = {k}: fold ARI {chosen.fold_ari_mean:.3f} (min {chosen.fold_ari_min:.3f}); period "
        f"ARI {chosen.period_ari:.3f}, so groups fitted on Format A only partly match those "
        f"fitted on Format B; k-means and Ward agree at ARI {chosen.ward_ari:.3f}.",
        "",
        f"Clusters at k = {k} (ids ordered by mean occupancy; mean over member stations):",
        "",
        "| cluster | stations | weekday mean | weekday 08:00 | weekday 18:00 | weekend mean "
        "| closest to centre |",
        "|---:|---:|---:|---:|---:|---:|---|",
    ]
    for cluster, members in final.groupby(labels):
        weekday = members[[c for c in members.columns if c.startswith("weekday")]]
        weekend = members[[c for c in members.columns if c.startswith("weekend")]]
        lines.append(
            f"| {int(cluster)} | {len(members)} | {float(weekday.to_numpy().mean()):.2f} | "
            f"{float(members['weekday_08'].mean()):.2f} | "
            f"{float(members['weekday_18'].mean()):.2f} | "
            f"{float(weekend.to_numpy().mean()):.2f} | {'; '.join(reps[int(cluster)])} |"
        )
    lines += [
        "",
        "![](figures/e3_profiles.png)",
        "",
        "![](figures/e3_cluster_map.png)",
        "",
        "Cluster labels describe historical occupancy only; they are not inferred trip purposes. "
        "Per-fold labels for later experiments are fitted in-fold (PRD 19.2).",
        "",
    ]
    return "\n".join(lines)


def store_cluster_ids(engine: Engine, labels: pd.Series) -> int:
    """Write final labels to ``stations.cluster_id`` (NULL for unclustered stations)."""
    with engine.begin() as conn:
        conn.execute(text("UPDATE stations SET cluster_id = NULL"))
        conn.execute(
            text("UPDATE stations SET cluster_id = :c WHERE station_key = :s"),
            [{"c": int(c), "s": int(s)} for s, c in zip(labels.index, labels, strict=True)],
        )
    return len(labels)


def main() -> None:
    """``make backtest E=E3``."""
    cfg = load_project_config().clustering
    engine = make_engine()
    with Session(engine) as session:
        gaps = load_gaps(session)
    folds = default_folds(engine, gaps)
    span = periods(engine, folds)
    setup_mlflow(EXPERIMENT)
    commit = git_commit()

    def profiles(start: datetime, cutoff: datetime) -> pd.DataFrame:
        return profile_matrix(load_profile_cells(engine, start, cutoff), cfg.min_cell_obs)

    final = profiles(span.a_start, span.final_end)
    fold_profiles = [profiles(span.a_start, f.train_end) for f in folds]
    a_profiles = profiles(span.a_start, span.a_end)
    b_profiles = profiles(span.b_start, span.final_end)
    log.info("profiles_loaded", final=len(final), a=len(a_profiles), b=len(b_profiles))

    scores = [
        score_k(k, final, fold_profiles, a_profiles, b_profiles, cfg.seed)
        for k in range(cfg.k_min, cfg.k_max + 1)
    ]
    k = choose_k(scores)
    labels = fit_kmeans(final, k, cfg.seed)
    with engine.connect() as conn:
        info = pd.read_sql(text("SELECT station_key, name, lat, lon FROM stations"), conn)
    names = info.set_index("station_key")["name"]
    seen = sorted(set(info.station_key) - set(final.index))
    dropped = [f"{names[s]} ({s})" for s in seen]
    reps = representatives(final, labels, names)

    with mlflow.start_run(run_name="e3") as active:
        run_id = active.info.run_id
        mlflow.log_params(
            {
                "k_range": f"{cfg.k_min}-{cfg.k_max}",
                "k_chosen": k,
                "min_cell_obs": cfg.min_cell_obs,
                "seed": cfg.seed,
                "data_start": span.a_start.isoformat(),
                "data_end": span.final_end.isoformat(),
                "n_folds": len(folds),
                "git_commit": commit,
                "data_source": "hist_a,hist_b",
            }
        )
        for s in scores:
            mlflow.log_metric(f"silhouette_k{s.k}", s.silhouette)
            mlflow.log_metric(f"fold_ari_mean_k{s.k}", s.fold_ari_mean)
            mlflow.log_metric(f"fold_ari_min_k{s.k}", s.fold_ari_min)
            mlflow.log_metric(f"period_ari_k{s.k}", s.period_ari)
            mlflow.log_metric(f"ward_ari_k{s.k}", s.ward_ari)
        fold_labels = pd.concat(
            [
                fit_kmeans(p, k, cfg.seed).to_frame().assign(fold=f.fold)
                for p, f in zip(fold_profiles, folds, strict=True)
            ]
        ).reset_index()
        path = get_env_settings().data_dir / "processed" / f"e3_fold_labels_{run_id}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        fold_labels.to_parquet(path, index=False)
        mlflow.log_param("fold_labels_file", str(path))
        mlflow.log_text(labels.reset_index().to_csv(index=False), "final_labels.csv")
        FIGURES.mkdir(parents=True, exist_ok=True)
        plot_profiles(final, labels, str(FIGURES / "e3_profiles.png"))
        plot_map(info, labels, str(FIGURES / "e3_cluster_map.png"))
        mlflow.log_artifact(str(FIGURES / "e3_profiles.png"))
        mlflow.log_artifact(str(FIGURES / "e3_cluster_map.png"))
        stored = store_cluster_ids(engine, labels)
    section = render_section(run_id, span, cfg, scores, k, final, labels, reps, dropped, len(folds))
    replace_section(REPORTS / "experiments.md", EXPERIMENT, section)
    log.info("e3_done", run_id=run_id, k=k, stations=stored, fold_labels=str(path))


if __name__ == "__main__":
    main()
