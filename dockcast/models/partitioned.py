"""LightGBM quantile models trained per group: one per station or per E3 cluster (PRD 12.2, E2).

Each group gets its own :class:`LgbmQuantile` with the same features, defaults and early
stopping as ``lgbm_global``, trained only on that group's rows. Rows whose station has no group
(or whose group had no training rows) get NaN and drop out of the common rows.
"""

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Self

import numpy as np
import pandas as pd

from dockcast.models.base import QUANTILE_COLUMNS
from dockcast.models.lgbm_quantile import LgbmQuantile


class PartitionedLgbm:
    """One quantile LightGBM per group, groups trained in parallel threads."""

    is_point = False
    uses_validation = True

    def __init__(
        self,
        name: str,
        features: Sequence[str],
        groups: Mapping[int, int],
        n_jobs: int = 1,
        threads_per_model: int = 1,
    ) -> None:
        """Create the model.

        Args:
            name: Model name, e.g. ``lgbm_per_station``.
            features: Numeric feature columns.
            groups: Station key -> group id.
            n_jobs: Groups trained at the same time.
            threads_per_model: LightGBM threads per group model.
        """
        self.name = name
        self.features = list(features)
        self.groups = {int(s): int(g) for s, g in groups.items()}
        self.n_jobs = n_jobs
        self.threads_per_model = threads_per_model
        self.models: dict[int, LgbmQuantile] = {}

    def _group_of(self, X: pd.DataFrame) -> pd.Series:  # noqa: N803
        return X["station_key"].astype(int).map(self.groups)

    def _fit_group(
        self, group: int, train: pd.DataFrame, valid: pd.DataFrame | None
    ) -> tuple[int, LgbmQuantile]:
        stations = sorted(s for s, g in self.groups.items() if g == group)
        model = LgbmQuantile(self.features, stations, num_threads=self.threads_per_model)
        if valid is None or valid.empty:
            model.fit(train, train["y"])
        else:
            model.fit(train, train["y"], valid, valid["y"])
        return group, model

    def fit(
        self,
        X: pd.DataFrame,  # noqa: N803
        y: pd.Series,
        X_valid: pd.DataFrame | None = None,  # noqa: N803
        y_valid: pd.Series | None = None,
    ) -> Self:
        """Train one model per group that has training rows.

        Args:
            X: Training features with ``station_key``.
            y: Training target.
            X_valid: Validation features (early stopping per group; none -> no early stop).
            y_valid: Validation target.

        Returns:
            Self.
        """
        train = X.assign(y=y.to_numpy())
        train_groups = self._group_of(train)
        valid = None if X_valid is None or y_valid is None else X_valid.assign(y=y_valid.to_numpy())
        valid_groups = None if valid is None else self._group_of(valid)
        jobs = []
        for group in sorted(int(g) for g in train_groups.dropna().unique()):
            part = train[train_groups == group]
            vpart = None if valid is None or valid_groups is None else valid[valid_groups == group]
            jobs.append((group, part, vpart))
        with ThreadPoolExecutor(max_workers=self.n_jobs) as pool:
            fitted = list(pool.map(lambda job: self._fit_group(*job), jobs))
        self.models = dict(fitted)
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        """Raw quantile predictions; NaN for stations without a fitted group model."""
        out = pd.DataFrame(np.nan, index=X.index, columns=QUANTILE_COLUMNS)
        groups = self._group_of(X)
        for group, model in self.models.items():
            mask = groups == group
            if mask.any():
                out.loc[mask, QUANTILE_COLUMNS] = model.predict(X[mask]).to_numpy()
        return out

    def best_iterations(self) -> dict[int, dict[float, int]]:
        """Best iteration per group and quantile."""
        return {g: dict(m.best_iterations) for g, m in self.models.items()}
