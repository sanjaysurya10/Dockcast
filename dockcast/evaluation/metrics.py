"""Regression and interval metrics (PRD 13.2). Event metrics arrive with M10."""

import numpy as np
import pandas as pd


def mae(y: pd.Series, pred: pd.Series) -> float:
    """Mean absolute error."""
    return float(np.mean(np.abs(y.to_numpy() - pred.to_numpy())))


def rmse(y: pd.Series, pred: pd.Series) -> float:
    """Root mean squared error."""
    return float(np.sqrt(np.mean((y.to_numpy() - pred.to_numpy()) ** 2)))


def bias(y: pd.Series, pred: pd.Series) -> float:
    """Mean error ``pred - y`` (positive = over-prediction)."""
    return float(np.mean(pred.to_numpy() - y.to_numpy()))


def mase(model_mae: float, persistence_mae: float) -> float:
    """MAE scaled by persistence MAE on the same rows (< 1 beats persistence)."""
    return float("nan") if persistence_mae == 0 else model_mae / persistence_mae


def pinball(y: pd.Series, quantile_pred: pd.Series, q: float) -> float:
    """Mean pinball (quantile) loss for quantile level ``q``."""
    diff = y.to_numpy() - quantile_pred.to_numpy()
    return float(np.mean(np.maximum(q * diff, (q - 1) * diff)))


def coverage(y: pd.Series, lower: pd.Series, upper: pd.Series) -> float:
    """Share of ``y`` inside ``[lower, upper]``."""
    inside = (y.to_numpy() >= lower.to_numpy()) & (y.to_numpy() <= upper.to_numpy())
    return float(np.mean(inside))


def interval_width(lower: pd.Series, upper: pd.Series) -> float:
    """Mean ``upper - lower``."""
    return float(np.mean(upper.to_numpy() - lower.to_numpy()))
