"""What drives a forecast (PRD 16.4): TreeSHAP contributions summed per feature group.

The P50 booster's ``pred_contrib`` splits each raw prediction into one value per feature plus
an expected value. Summing features by :data:`dockcast.features.registry.FEATURE_GROUPS` (and
the ``station_key`` category as ``station``) gives a few signed amounts, in bikes, that the
web app shows as plain-language chips. They explain the raw P50, before clipping to [0,
capacity].
"""

from collections.abc import Mapping, Sequence

import pandas as pd
from sqlalchemy import Engine, delete
from sqlalchemy.dialects.postgresql import insert

from dockcast.db.models import ForecastDriver
from dockcast.features.registry import FEATURE_GROUPS

STATION_GROUP = "station"
OTHER_GROUP = "other"


def group_of(groups: Mapping[str, Sequence[str]] = FEATURE_GROUPS) -> dict[str, str]:
    """``feature -> group``, with ``station_key`` as :data:`STATION_GROUP`."""
    mapping = {feature: name for name, features in groups.items() for feature in features}
    mapping["station_key"] = STATION_GROUP
    return mapping


def grouped_contributions(contributions: pd.DataFrame) -> pd.DataFrame:
    """Sum per-feature contributions into groups (features outside the registry go to "other").

    Args:
        contributions: Output of ``LgbmQuantile.contributions``.

    Returns:
        Same index, one column per group; ``expected_value`` is dropped.
    """
    features = contributions.drop(columns="expected_value")
    mapping = group_of()
    labels = [mapping.get(column, OTHER_GROUP) for column in features.columns]
    return features.T.groupby(labels).sum().T


def driver_rows(
    grouped: pd.DataFrame, station_keys: pd.Series, issued_at: pd.Timestamp, horizon_min: int
) -> pd.DataFrame:
    """Long rows for ``forecast_drivers``."""
    wide = grouped.assign(station_key=station_keys.to_numpy())
    long = wide.melt(id_vars="station_key", var_name="feature_group", value_name="contribution")
    return long.assign(issued_at=issued_at, horizon_min=horizon_min)


def store_drivers(engine: Engine, frame: pd.DataFrame) -> int:
    """Replace the stored drivers with this issue's rows (only the latest issue is kept)."""
    if frame.empty:
        return 0
    issued = frame["issued_at"].iloc[0].to_pydatetime()
    records = [
        {
            "station_key": int(key),
            "issued_at": issued,
            "horizon_min": int(horizon),
            "feature_group": str(group),
            "contribution": float(value),
        }
        for key, horizon, group, value in zip(
            frame["station_key"].to_numpy(dtype=int),
            frame["horizon_min"].to_numpy(dtype=int),
            frame["feature_group"].astype(str),
            frame["contribution"].to_numpy(dtype=float),
            strict=True,
        )
    ]
    stmt = insert(ForecastDriver).values(records)
    stmt = stmt.on_conflict_do_update(
        index_elements=["station_key", "issued_at", "horizon_min", "feature_group"],
        set_={"contribution": stmt.excluded.contribution},
    )
    with engine.begin() as conn:
        conn.execute(stmt)
        conn.execute(delete(ForecastDriver).where(ForecastDriver.issued_at < issued))
    return len(records)
