"""Feature groups for ablation (PRD 10.8). v1 groups only; spatial/cluster/weather come later."""

LAG_COLUMNS = [
    "bikes_now",
    "docks_now",
    "ratio_now",
    *[f"bikes_lag{k}" for k in (1, 2, 3, 4, 8)],
    *[f"ratio_lag{k}" for k in (1, 2, 3, 4, 8)],
    "change_1",
    "change_4",
    "acceleration",
]

FEATURE_GROUPS: dict[str, list[str]] = {
    "lags": LAG_COLUMNS,
    "rolling": [
        "bikes_roll4_mean",
        "bikes_roll4_std",
        "bikes_roll12_mean",
        "bikes_roll12_std",
        "zero_bikes_24h",
        "zero_docks_24h",
    ],
    "seasonal": ["bikes_seasonal_1d", "bikes_seasonal_7d"],
    "calendar": [
        "hour_local",
        "minute_sin",
        "minute_cos",
        "dow",
        "dow_sin",
        "dow_cos",
        "is_weekend",
        "is_public_holiday",
        "is_school_term",
        "is_uni_term",
        "days_to_next_holiday",
        "month_sin",
        "month_cos",
    ],
    "station_static": ["capacity", "lat", "lon", "te_station_hour"],
}
