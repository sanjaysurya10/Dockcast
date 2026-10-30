"""Station behaviour clustering for E3: k-means and Ward on occupancy profiles (PRD 13, E3)."""

from collections.abc import Sequence
from itertools import combinations

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score


def order_labels(profiles: pd.DataFrame, labels: np.ndarray) -> pd.Series:
    """Renumber clusters 0..k-1 by ascending mean occupancy so ids are comparable across fits.

    Args:
        profiles: Profiles indexed by ``station_key``.
        labels: Raw cluster labels aligned with ``profiles`` rows.

    Returns:
        Labels indexed by ``station_key``.
    """
    raw = pd.Series(labels, index=profiles.index)
    level = profiles.mean(axis=1).groupby(raw).mean().sort_values()
    mapping = {int(old): new for new, old in enumerate(level.index)}
    return raw.map(mapping).astype(int).rename("cluster_id")


def fit_kmeans(profiles: pd.DataFrame, k: int, seed: int = 0) -> pd.Series:
    """K-means labels (``n_init=20``, fixed seed).

    Args:
        profiles: Profiles indexed by ``station_key``.
        k: Number of clusters.
        seed: Random state.

    Returns:
        Ordered labels indexed by ``station_key``.
    """
    model = KMeans(n_clusters=k, n_init=20, random_state=seed)
    return order_labels(profiles, model.fit_predict(profiles.to_numpy()))


def fit_ward(profiles: pd.DataFrame, k: int) -> pd.Series:
    """Hierarchical (Ward) labels.

    Args:
        profiles: Profiles indexed by ``station_key``.
        k: Number of clusters.

    Returns:
        Ordered labels indexed by ``station_key``.
    """
    model = AgglomerativeClustering(n_clusters=k, linkage="ward")
    return order_labels(profiles, model.fit_predict(profiles.to_numpy()))


def silhouette(profiles: pd.DataFrame, labels: pd.Series) -> float:
    """Mean silhouette (Euclidean) of ``labels`` on ``profiles``.

    Args:
        profiles: Profiles indexed by ``station_key``.
        labels: Labels indexed by ``station_key``.

    Returns:
        Silhouette score in [-1, 1].
    """
    return float(silhouette_score(profiles.to_numpy(), labels.loc[profiles.index].to_numpy()))


def ari(first: pd.Series, second: pd.Series) -> tuple[float, int]:
    """Adjusted Rand index on the stations both labelings share.

    Args:
        first: Labels indexed by ``station_key``.
        second: Labels indexed by ``station_key``.

    Returns:
        ARI and the number of shared stations.
    """
    shared = first.index.intersection(second.index)
    score = adjusted_rand_score(first.loc[shared].to_numpy(), second.loc[shared].to_numpy())
    return float(score), len(shared)


def pairwise_ari(labelings: Sequence[pd.Series]) -> list[float]:
    """ARI for every pair of labelings (e.g. one per fold).

    Args:
        labelings: Labels indexed by ``station_key``.

    Returns:
        One ARI per unordered pair.
    """
    return [ari(a, b)[0] for a, b in combinations(labelings, 2)]
