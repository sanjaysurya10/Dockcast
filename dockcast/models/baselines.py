"""Naive baselines (PRD 12.2): persistence and seasonal naive (7 days)."""

from typing import Self

import pandas as pd

from dockcast.models.base import point_frame


class Persistence:
    """ŷ = bikes at the issue time (``bikes_now``)."""

    name = "persistence"
    is_point = True

    def fit(self, X: pd.DataFrame, y: pd.Series) -> Self:  # noqa: N803
        """No parameters to learn."""
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        """Copy ``bikes_now``."""
        return point_frame(X["bikes_now"])


class SeasonalNaive7d:
    """ŷ = bikes at the target time minus 7 days (``bikes_seasonal_7d``)."""

    name = "seasonal_naive_7d"
    is_point = True

    def fit(self, X: pd.DataFrame, y: pd.Series) -> Self:  # noqa: N803
        """No parameters to learn."""
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        """Copy ``bikes_seasonal_7d``."""
        return point_frame(X["bikes_seasonal_7d"])
