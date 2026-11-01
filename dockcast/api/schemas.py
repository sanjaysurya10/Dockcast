"""Response models of the read-only API (PRD 15)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class Health(BaseModel):
    """``GET /health``."""

    status: str  # "ok" | "degraded"
    db: str  # "ok" | "error"
    last_collector_run: datetime | None
    last_forecast_issued_at: datetime | None


class City(BaseModel):
    """One city."""

    city_code: str
    name: str
    timezone: str
    centre_lat: float
    centre_lon: float
    default_zoom: float


class Status(BaseModel):
    """Latest observed status of a station."""

    bikes: int
    docks: int
    observed_at: datetime
    is_renting: bool | None


class Risk(BaseModel):
    """P(empty) / P(full) in the next window (event models arrive in v2, M10)."""

    window_min: int
    p_empty: float
    p_full: float


class Station(BaseModel):
    """A station with its latest status."""

    station_key: int
    name: str
    lat: float
    lon: float
    capacity: int
    is_active: bool
    now: Status | None
    risk: Risk | None


class HorizonForecast(BaseModel):
    """Quantile forecast for one horizon."""

    horizon_min: int
    target_ts: datetime
    bikes_p10: float
    bikes_p50: float
    bikes_p90: float


class Freshness(BaseModel):
    """Ages of the data behind a response."""

    status_age_s: int | None
    forecast_age_s: int | None
    stale: bool


class StationForecast(BaseModel):
    """``GET /v1/stations/{station_key}/forecast`` (PRD 15.2)."""

    station_key: int
    name: str
    capacity: int
    issued_at: datetime
    model_version: str
    now: Status | None
    forecasts: list[HorizonForecast]
    risk: Risk | None
    data_freshness: Freshness


class RiskStation(BaseModel):
    """One station in ``GET /v1/cities/{city}/risk``: interim levels from the forecast range."""

    station_key: int
    name: str
    lat: float
    lon: float
    capacity: int
    now: Status | None
    horizon_min: int
    bikes_p10: float
    bikes_p50: float
    bikes_p90: float
    empty_level: Literal["likely", "possible", "low"]
    full_level: Literal["likely", "possible", "low"]
    eta_empty_min: int | None
    eta_full_min: int | None


class CityRisk(BaseModel):
    """``GET /v1/cities/{city}/risk``: stations ranked by empty or full risk at one window.

    ``basis`` is ``forecast_range``: levels come from the regression P10/P50/P90, not from
    calibrated event probabilities (those arrive with M10).
    """

    city: str
    window_min: int
    kind: Literal["empty", "full"]
    basis: Literal["forecast_range"]
    issued_at: datetime
    model_version: str
    total: int
    stations: list[RiskStation]


class HistoryPoint(BaseModel):
    """One 15-min state (``bikes``/``docks`` are the last observation in the bucket)."""

    ts: datetime
    bikes: float | None
    docks: float | None
    is_imputed: bool


class StationHistory(BaseModel):
    """``GET /v1/stations/{station_key}/history``."""

    station_key: int
    hours: int
    points: list[HistoryPoint]


class NetFlowStation(BaseModel):
    """One station's net change in bikes over the window; null when excluded."""

    station_key: int
    net_flow: float | None
    excluded: Literal["rebalance", "closed", "missing"] | None


class CityNetFlow(BaseModel):
    """``GET /v1/cities/{city}/netflow`` (PRD 10.6): net change, not separate trips."""

    city: str
    window_min: int
    ts: datetime
    stations: list[NetFlowStation]


class Alternative(BaseModel):
    """A nearby station with bikes forecast at the horizon."""

    station_key: int
    name: str
    lat: float
    lon: float
    distance_m: float
    walk_m: float
    bikes_p10: float
    bikes_p50: float
    bikes_p90: float


class StationAlternatives(BaseModel):
    """``GET /v1/stations/{station_key}/alternatives``: the 2 nearest with P50 >= 3 bikes.

    ``walk_m`` is the straight-line distance x 1.3, an approximation (PRD 16.4).
    """

    station_key: int
    horizon_min: int
    issued_at: datetime
    alternatives: list[Alternative]


class Driver(BaseModel):
    """One feature group's TreeSHAP contribution to the raw P50 forecast, in bikes."""

    feature_group: str
    contribution: float


class StationDrivers(BaseModel):
    """``GET /v1/stations/{station_key}/drivers``, sorted by absolute contribution."""

    station_key: int
    horizon_min: int
    issued_at: datetime
    drivers: list[Driver]


class BacktestRow(BaseModel):
    """Mean over folds of one model, horizon and slice value."""

    model_name: str
    horizon_min: int
    slice_value: str
    folds: int
    n: int
    mae: float | None
    rmse: float | None
    mase: float | None
    coverage_80: float | None
    interval_width: float | None


class Backtest(BaseModel):
    """``GET /v1/model/backtest``."""

    experiment: str
    run_id: str
    slice_kind: str
    rows: list[BacktestRow]


class FoldWindow(BaseModel):
    """One rolling-origin fold (``reports/folds.json``)."""

    fold: int
    train_end: datetime
    test_start: datetime
    test_end: datetime


class HorizonError(BaseModel):
    """MAE of one model at one horizon over every test row."""

    horizon_min: int
    model_name: str
    mae: float


class HeatmapRow(BaseModel):
    """MAE at +60 by local hour for one station (None where the hour has no rows)."""

    station_key: int
    name: str
    mae: list[float | None]


class ErrorAnalysis(BaseModel):
    """``GET /v1/model/error-analysis``: slices pre-computed by ``make error-analysis``."""

    run_id: str
    e2_run_id: str | None
    git_commit: str
    generated_at: datetime
    folds: list[FoldWindow]
    horizon_growth: list[HorizonError]
    heatmap_hours: list[int]
    heatmap: list[HeatmapRow]


class DataHealth(BaseModel):
    """Collector uptime over 7 days and what the served model covers (PRD 16.5)."""

    collector_polls_7d: int
    expected_polls_7d: int
    collector_uptime_7d: float
    stations_modelled: int
    train_end: datetime | None


class ChampionModel(BaseModel):
    """A champion model version and its backtest metrics."""

    model_version: str
    horizon_min: int | None
    trained_at: datetime
    train_end: datetime
    metrics: dict[str, Any]


class ModelSummary(BaseModel):
    """``GET /v1/model/summary``."""

    champions: list[ChampionModel]
    last_retrain: datetime | None
    data_health: DataHealth
