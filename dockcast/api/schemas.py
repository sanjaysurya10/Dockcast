"""Response models of the read-only API (PRD 15)."""

from datetime import datetime
from typing import Any

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
