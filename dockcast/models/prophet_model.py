"""Prophet per station (PRD 12.2 ``prophet_station``): daily + weekly seasonality, holidays.

Prophet models the series itself and does not read the state at the issue time, so one fit per
station and fold serves every horizon: it is fitted on hourly observed states before the fold's
``train_end`` (local wall-clock time, so daily seasonality follows Dublin hours) and predicts the
state at each target time. P10 / P90 are Prophet's 80% interval. Public holidays come from
``calendar_days``.
"""

import logging
from collections.abc import Sequence
from datetime import date
from typing import Self

import numpy as np
import pandas as pd
from prophet import Prophet

from dockcast.models.base import QUANTILE_COLUMNS

TZ = "Europe/Dublin"
SEED = 0

logging.getLogger("cmdstanpy").setLevel(logging.WARNING)


def _local_naive(ts: pd.Series) -> pd.Series:
    local: pd.Series = ts.dt.tz_convert(TZ).dt.tz_localize(None)
    return local


class ProphetStation:
    """One Prophet model per station, fitted once per fold with :meth:`fit_states`."""

    name = "prophet_station"
    is_point = False

    def __init__(self, holidays: Sequence[date]) -> None:
        """Create the model.

        Args:
            holidays: Public holiday dates.
        """
        self.holidays = pd.DataFrame(
            {"holiday": "public_holiday", "ds": pd.to_datetime(sorted(holidays))}
        )
        self.models: dict[int, Prophet] = {}

    def fit_states(self, states: pd.DataFrame, cutoff: pd.Timestamp) -> Self:
        """Fit every station on its hourly valid states with ``state_ts < cutoff``.

        Args:
            states: Panel rows ``station_key, state_ts, bikes, target_ok``.
            cutoff: Exclusive end of the history (the fold's ``train_end``).

        Returns:
            Self.
        """
        known = states[
            (states["state_ts"] < cutoff)
            & states["target_ok"]
            & (states["state_ts"].dt.minute == 0)
            & states["bikes"].notna()
        ]
        self.models = {}
        for key, part in known.groupby("station_key"):
            if len(part) < 2:
                continue
            model = Prophet(
                daily_seasonality=True,
                weekly_seasonality=True,
                yearly_seasonality=False,
                holidays=self.holidays,
                interval_width=0.8,
            )
            model.fit(pd.DataFrame({"ds": _local_naive(part["state_ts"]), "y": part["bikes"]}))
            self.models[int(str(key))] = model
        return self

    def fit(self, X: pd.DataFrame, y: pd.Series) -> Self:  # noqa: N803
        """No-op: the model is fitted on states by :meth:`fit_states` (horizon-independent)."""
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        """Quantiles at each row's ``target_ts``; NaN for stations without a model."""
        out = pd.DataFrame(np.nan, index=X.index, columns=QUANTILE_COLUMNS)
        for key, part in X.groupby("station_key"):
            model = self.models.get(int(str(key)))
            if model is None:
                continue
            times = pd.Series(part["target_ts"].unique())
            np.random.seed(SEED)  # Prophet samples its interval with the global numpy RNG
            pred = model.predict(pd.DataFrame({"ds": _local_naive(times)}))
            lookup = pd.DataFrame(
                {
                    "p10": pred["yhat_lower"].to_numpy(),
                    "p50": pred["yhat"].to_numpy(),
                    "p90": pred["yhat_upper"].to_numpy(),
                },
                index=times,
            )
            out.loc[part.index, QUANTILE_COLUMNS] = lookup.loc[part["target_ts"]].to_numpy()
        return out
