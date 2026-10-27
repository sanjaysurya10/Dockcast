"""Cities, stations and station forecasts (PRD 15.1)."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response
from sqlalchemy import Engine

from dockcast.api import queries
from dockcast.api.errors import ApiError, stale, station_not_found
from dockcast.api.schemas import City, Freshness, HorizonForecast, Station, StationForecast, Status
from dockcast.config import load_project_config

router = APIRouter()


def _engine(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def _cache(response: Response, seconds: int) -> None:
    response.headers["Cache-Control"] = f"public, max-age={seconds}"


@router.get("/cities", response_model=list[City])
def list_cities(request: Request, response: Response) -> list[City]:
    """Cities with centre and zoom."""
    _cache(response, 3600)
    with _engine(request).connect() as conn:
        return [City.model_validate(c) for c in queries.cities(conn)]


@router.get("/cities/{city}/stations", response_model=list[Station])
def list_stations(city: str, request: Request, response: Response) -> list[Station]:
    """All stations of a city with their latest status."""
    _cache(response, 60)
    with _engine(request).connect() as conn:
        if city not in {c["city_code"] for c in queries.cities(conn)}:
            raise ApiError(404, "city_not_found", f"no city {city!r}")
        return [Station.model_validate(s) for s in queries.stations(conn, city=city)]


@router.get("/stations/{station_key}", response_model=Station)
def get_station(station_key: int, request: Request, response: Response) -> Station:
    """One station with its latest status."""
    _cache(response, 60)
    with _engine(request).connect() as conn:
        rows = queries.stations(conn, station_key=station_key)
    if not rows:
        raise station_not_found(station_key)
    return Station.model_validate(rows[0])


@router.get("/stations/{station_key}/forecast", response_model=StationForecast)
def get_forecast(station_key: int, request: Request, response: Response) -> StationForecast:
    """Latest P10/P50/P90 forecasts at +30/+60/+120 (PRD 15.2); 503 when stale."""
    with _engine(request).connect() as conn:
        rows = queries.stations(conn, station_key=station_key)
        if not rows:
            raise station_not_found(station_key)
        forecasts = queries.latest_forecast(conn, station_key)
    station = rows[0]
    if not forecasts:
        raise ApiError(404, "forecast_not_found", f"no forecast for station {station_key}")
    now = datetime.now(UTC)
    status = Status.model_validate(station["now"]) if station["now"] else None
    issued = forecasts[0]["issued_at"]
    status_age = int((now - status.observed_at).total_seconds()) if status else None
    forecast_age = int((now - issued).total_seconds())
    limit = timedelta(minutes=load_project_config().serving.stale_after_min).total_seconds()
    if forecast_age > limit or status_age is None or status_age > limit:
        raise stale(f"forecast for station {station_key} is older than {limit / 60:g} min")
    _cache(response, max(0, 900 - forecast_age))
    return StationForecast(
        station_key=station_key,
        name=station["name"],
        capacity=station["capacity"],
        issued_at=issued,
        model_version=forecasts[0]["model_version"],
        now=status,
        forecasts=[HorizonForecast.model_validate(f) for f in forecasts],
        risk=None,
        data_freshness=Freshness(status_age_s=status_age, forecast_age_s=forecast_age, stale=False),
    )
