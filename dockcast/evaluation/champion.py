"""Champion selection (PRD 12.5).

Per horizon: eligible models have mean ``coverage_80`` within ``[0.70, 0.90]`` (point models
have no interval and are not eligible); the champion is the eligible model with the lowest mean
MAE, except that a simpler model within 1 % of that MAE wins the tie.
"""

import math
from typing import Any

import pandas as pd

SIMPLICITY = ["persistence", "seasonal_naive_7d", "ridge", "lgbm_global"]  # simplest first
COVERAGE_RANGE = (0.70, 0.90)
TIE_TOLERANCE = 0.01


def select_champions(summary: pd.DataFrame) -> pd.DataFrame:
    """One row per horizon with the champion (or None) and why.

    Args:
        summary: Output of :func:`dockcast.evaluation.backtest.summarise`.

    Returns:
        Columns ``horizon_min, champion, mae, coverage_80, reason``.
    """
    rows: list[dict[str, Any]] = []
    lo, hi = COVERAGE_RANGE
    rank = {name: i for i, name in enumerate(SIMPLICITY)}
    for horizon in sorted(summary["horizon_min"].unique()):
        part: list[dict[str, Any]] = summary[summary["horizon_min"] == horizon].to_dict("records")
        eligible = [r for r in part if lo <= float(r["coverage_80"]) <= hi]
        if not eligible:
            covs = ", ".join(
                f"{r['model_name']} {float(r['coverage_80']):.3f}"
                for r in part
                if not math.isnan(float(r["coverage_80"]))
            )
            rows.append(
                {
                    "horizon_min": int(horizon),
                    "champion": None,
                    "mae": float("nan"),
                    "coverage_80": float("nan"),
                    "reason": f"no model with coverage in [{lo}, {hi}] ({covs or 'none'})",
                }
            )
            continue
        best = min(float(r["mae"]) for r in eligible)
        close = [r for r in eligible if float(r["mae"]) <= best * (1 + TIE_TOLERANCE)]
        pick = min(close, key=lambda r: rank.get(str(r["model_name"]), 99))
        reason = "lowest MAE with coverage in range"
        if len(close) > 1:
            reason += " (simpler model within 1 %)"
        rows.append(
            {
                "horizon_min": int(horizon),
                "champion": str(pick["model_name"]),
                "mae": float(pick["mae"]),
                "coverage_80": float(pick["coverage_80"]),
                "reason": reason,
            }
        )
    return pd.DataFrame(rows)
