"""Configuration: environment variables plus `config/settings.toml` and per-city TOML files."""

import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


class EnvSettings(BaseSettings):
    """Runtime settings read from env vars and `.env` (PRD 18.3)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://dockcast:dockcast@localhost:5432/dockcast"
    city: str = "dublin"
    gbfs_root_url: str = ""
    # Host moved from metwdb-openaccess.ichec.ie (no longer resolves; checked 2026-10-25).
    met_forecast_url: str = "http://openaccess.pf.api.met.ie/metno-wdb2ts/locationforecast"
    mlflow_tracking_uri: str = "file:./mlruns"
    archive_bucket_url: str = ""
    api_cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"
    contact_email: str = ""
    data_dir: Path = PROJECT_ROOT / "data"

    @property
    def user_agent(self) -> str:
        """User-Agent sent to data sources (PRD 21): ``DockCast/<version> (<contact>)``."""
        from dockcast import __version__

        contact = f" ({self.contact_email})" if self.contact_email else ""
        return f"DockCast/{__version__}{contact}"

    @property
    def cors_origins(self) -> list[str]:
        """CORS origins as a list (comma-separated in the env var)."""
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


class ForecastConfig(BaseModel):
    """Forecast horizons, quantiles and bucket sizes."""

    horizons_min: list[int]
    quantiles: list[float]
    bucket_min: int
    event_window_min: int


class BacktestConfig(BaseModel):
    """Rolling-origin backtest protocol (PRD 13.1)."""

    n_folds: int
    test_window_days: int
    gap_min: int


class SpatialConfig(BaseModel):
    """Neighbour-set parameters (PRD 10.5)."""

    neighbour_k: int
    neighbour_radius_m: float


class CollectorConfig(BaseModel):
    """Live collector behaviour (PRD 9.1)."""

    poll_interval_s: int = Field(ge=60)
    station_info_refresh_h: int
    request_timeout_s: float
    retry_backoff_s: list[float]
    stale_after_min: int


class RetentionConfig(BaseModel):
    """Raw-data retention in the hosted database (PRD 18.4)."""

    raw_live_days: int = Field(ge=1)


class ProjectConfig(BaseModel):
    """Contents of `config/settings.toml`."""

    forecast: ForecastConfig
    backtest: BacktestConfig
    spatial: SpatialConfig
    collector: CollectorConfig
    retention: RetentionConfig


class CityConfig(BaseModel):
    """Contents of `config/cities/<city>.toml`."""

    city_code: str
    name: str
    timezone: str
    centre_lat: float = Field(ge=-90, le=90)
    centre_lon: float = Field(ge=-180, le=180)
    default_zoom: float
    gbfs_root_url: str = ""
    ckan_package_url: str = ""
    weather_station: str = ""
    weather_history_url: str = ""
    weather_history_start: str = "2021-09-30"


def _read_toml(path: Path) -> dict[str, object]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def load_project_config(path: Path = CONFIG_DIR / "settings.toml") -> ProjectConfig:
    """Load and validate the project settings TOML.

    Args:
        path: Path to the settings file.

    Returns:
        The validated project configuration.
    """
    return ProjectConfig.model_validate(_read_toml(path))


def load_city_config(city: str, config_dir: Path = CONFIG_DIR / "cities") -> CityConfig:
    """Load a city TOML; `GBFS_ROOT_URL` from the environment overrides the file value.

    Args:
        city: City code, e.g. ``"dublin"``.
        config_dir: Directory holding ``<city>.toml`` files.

    Returns:
        The validated city configuration.
    """
    city_config = CityConfig.model_validate(_read_toml(config_dir / f"{city}.toml"))
    env_url = get_env_settings().gbfs_root_url
    if env_url:
        city_config = city_config.model_copy(update={"gbfs_root_url": env_url})
    return city_config


@lru_cache(maxsize=1)
def get_env_settings() -> EnvSettings:
    """Return cached environment settings (validated once, fail fast)."""
    return EnvSettings()
