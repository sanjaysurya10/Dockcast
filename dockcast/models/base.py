"""Common forecaster interface (PRD 12.1)."""

from typing import Protocol, Self

import pandas as pd

QUANTILE_COLUMNS = ["p10", "p50", "p90"]


class Forecaster(Protocol):
    """Anything that fits on a feature frame and predicts quantiles."""

    name: str
    is_point: bool  # True: p10 = p50 = p90, excluded from interval metrics

    def fit(self, X: pd.DataFrame, y: pd.Series) -> Self:  # noqa: N803 (sklearn convention)
        """Train on features ``X`` and target ``y``."""
        ...

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        """Return a frame with columns ``p10, p50, p90`` aligned with ``X``."""
        ...


def point_frame(values: pd.Series) -> pd.DataFrame:
    """Quantile frame for a point forecast (all quantiles equal).

    Args:
        values: Point predictions.

    Returns:
        Columns ``p10, p50, p90``.
    """
    return pd.DataFrame(
        {q: values.astype(float).to_numpy() for q in QUANTILE_COLUMNS}, index=values.index
    )
