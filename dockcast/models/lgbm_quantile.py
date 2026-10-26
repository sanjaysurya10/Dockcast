"""Global LightGBM quantile models, one booster per quantile (PRD 12.2, 12.3)."""

from collections.abc import Callable, Sequence
from typing import Any, Self

import lightgbm as lgb
import pandas as pd

from dockcast.models.base import QUANTILE_COLUMNS

QUANTILES = (0.1, 0.5, 0.9)
DEFAULT_PARAMS: dict[str, Any] = {  # PRD 12.3 starting point
    "num_leaves": 63,
    "learning_rate": 0.05,
    "min_data_in_leaf": 100,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "seed": 42,
    "verbose": -1,
}


class LgbmQuantile:
    """Station as a categorical feature; early stopping on a validation set when given."""

    name = "lgbm_global"
    is_point = False
    uses_validation = True

    def __init__(
        self,
        features: Sequence[str],
        stations: Sequence[int],
        n_estimators: int = 2000,
        early_stopping: int = 100,
        num_threads: int = 0,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Create the model.

        Args:
            features: Numeric feature columns (``station_key`` is added as categorical).
            stations: Every station key, so train and test share categories.
            n_estimators: Maximum boosting rounds.
            early_stopping: Patience on the validation set.
            num_threads: LightGBM threads (0 = default).
            params: Overrides of :data:`DEFAULT_PARAMS`.
        """
        self.features = list(features)
        self.stations = sorted(int(s) for s in stations)
        self.n_estimators = n_estimators
        self.early_stopping = early_stopping
        self.params = {**DEFAULT_PARAMS, **(params or {}), "num_threads": num_threads}
        self.boosters: dict[float, lgb.Booster] = {}
        self.best_iterations: dict[float, int] = {}

    def _frame(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        frame = X[self.features].astype(float)
        frame["station_key"] = pd.Categorical(
            X["station_key"].astype(int), categories=self.stations
        )
        return frame

    def fit(
        self,
        X: pd.DataFrame,  # noqa: N803
        y: pd.Series,
        X_valid: pd.DataFrame | None = None,  # noqa: N803
        y_valid: pd.Series | None = None,
    ) -> Self:
        """Train one booster per quantile.

        Args:
            X: Training features (with ``station_key``).
            y: Training target.
            X_valid: Optional validation features for early stopping.
            y_valid: Validation target.

        Returns:
            Self.
        """
        train = lgb.Dataset(
            self._frame(X),
            label=y.to_numpy(),
            categorical_feature=["station_key"],
            free_raw_data=False,
        )
        valid = None
        if X_valid is not None and y_valid is not None:
            valid = lgb.Dataset(self._frame(X_valid), label=y_valid.to_numpy(), reference=train)
        for q in QUANTILES:
            params = {**self.params, "objective": "quantile", "alpha": q, "metric": "quantile"}
            callbacks: list[Callable[..., Any]] = (
                [lgb.early_stopping(self.early_stopping, verbose=False)] if valid else []
            )
            booster = lgb.train(
                params,
                train,
                num_boost_round=self.n_estimators,
                valid_sets=[valid] if valid else None,
                callbacks=callbacks,
            )
            self.boosters[q] = booster
            self.best_iterations[q] = int(booster.best_iteration or booster.current_iteration())
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        """Raw quantile predictions (post-process before scoring)."""
        if not self.boosters:
            raise RuntimeError("fit before predict")
        frame = self._frame(X)
        out = {
            col: self.boosters[q].predict(frame, num_iteration=self.best_iterations[q])
            for col, q in zip(QUANTILE_COLUMNS, QUANTILES, strict=True)
        }
        return pd.DataFrame(out, index=X.index)

    def feature_importance(self) -> pd.Series:
        """Gain importance of the median booster."""
        booster = self.boosters[0.5]
        return pd.Series(
            booster.feature_importance("gain"), index=booster.feature_name()
        ).sort_values(ascending=False)
