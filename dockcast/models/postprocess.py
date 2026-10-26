"""Prediction post-processing (PRD 12.4): clip to ``[0, capacity]`` and order quantiles."""

import numpy as np
import pandas as pd

from dockcast.models.base import QUANTILE_COLUMNS


def postprocess(pred: pd.DataFrame, capacity: pd.Series) -> pd.DataFrame:
    """Sort ``p10 <= p50 <= p90`` per row, then clip each to ``[0, capacity]``.

    Args:
        pred: Columns ``p10, p50, p90``.
        capacity: Capacity per row (NaN = no upper clip).

    Returns:
        A new frame with the same index.
    """
    values = np.sort(pred[QUANTILE_COLUMNS].to_numpy(dtype=float), axis=1)
    upper = capacity.to_numpy(dtype=float)[:, None]
    values = np.clip(values, 0.0, np.where(np.isnan(upper), np.inf, upper))
    return pd.DataFrame(values, columns=QUANTILE_COLUMNS, index=pred.index)
