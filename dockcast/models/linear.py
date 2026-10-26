"""Ridge regression baseline-plus (PRD 12.2): same features, standardised, one-hot hour/dow."""

from collections.abc import Sequence
from typing import Self

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from dockcast.models.base import point_frame

ONE_HOT = ("hour_local", "dow")


class RidgeForecaster:
    """Point forecaster; scaling and imputation are fitted on the training rows only."""

    name = "ridge"
    is_point = True

    def __init__(self, features: Sequence[str], alpha: float = 1.0) -> None:
        """Create the model.

        Args:
            features: Feature columns to use.
            alpha: L2 strength.
        """
        self.features = list(features)
        self.alpha = alpha
        self._pipe: Pipeline | None = None

    def fit(self, X: pd.DataFrame, y: pd.Series) -> Self:  # noqa: N803
        """Fit imputer, scaler, one-hot encoder and ridge on ``X``."""
        numeric = [c for c in self.features if c not in ONE_HOT]
        prep = ColumnTransformer(
            [
                (
                    "num",
                    make_pipeline(
                        SimpleImputer(strategy="median", add_indicator=True), StandardScaler()
                    ),
                    numeric,
                ),
                ("cat", OneHotEncoder(handle_unknown="ignore"), list(ONE_HOT)),
            ]
        )
        self._pipe = make_pipeline(prep, Ridge(alpha=self.alpha))
        self._pipe.fit(X[self.features], y)
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        """Point predictions as equal quantiles."""
        if self._pipe is None:
            raise RuntimeError("fit before predict")
        return point_frame(pd.Series(self._pipe.predict(X[self.features]), index=X.index))
