"""Cities, stations, station forecasts and city risk (PRD 15.1)."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import Connection, Engine, text

from dockcast.api import queries, risk
from dockcast.api.errors import ApiError, stale, station_not_found
from dockcast.api.schemas import (
    Alternative,
    City,
    CityNetFlow,
    CityRisk,
    Driver,
    Freshness,
    HistoryPoint,
    HorizonForecast,
    NetFlowStation,
    RiskStation,
    Station,
    StationAlternatives,
    StationDrivers,
    StationForecast,
    StationHistory,
    Status,
)
from dockcast.config import city_codes, load_city_config, load_project_config
from dockcast.ingest.historical.reconcile import haversine_m

router = APIRouter()


def _engine(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def _city_config(city_code: str) -> dict[str, Any]:
    """Attribution and forecast flag from ``config/cities/<city>.toml`` (empty if absent)."""
    if city_code not in city_codes():
        return {}
    city = load_city_config(city_code)
    return city.model_dump(
        include={"forecasts", "attribution", "source_url", "licence_name", "licence_url"}
    )


def _cache(response: Response, seconds: int) -> None:
    response.headers["Cache-Control"] = f"public, max-age={seconds}"


@router.get("/cities", response_model=list[City])
def list_cities(request: Request, response: Response) -> list[City]:
    """Cities with centre, zoom, attribution and whether they have forecasts."""
    _cache(response, 3600)
    with _engine(request).connect() as conn:
        rows = queries.cities(conn)
    return [City.model_validate({**_city_config(row["city_code"]), **row}) for row in rows]


@router.get("/cities/{city}/stations", response_model=list[Station])
def list_stations(city: str, request: Request, response: Response) -> list[Station]:
    """All stations of a city with their latest status."""
    _cache(response, 60)
    with _engine(request).connect() as conn:
        if city not in {c["city_code"] for c in queries.cities(conn)}:
            raise ApiError(404, "city_not_found", f"no city {city!r}")
        return [Station.model_validate(s) for s in queries.stations(conn, city=city)]


@router.get("/cities/{city}/risk", response_model=CityRisk)
def city_risk(
    city: str,
    request: Request,
    response: Response,
    window: int = 60,
    kind: Literal["empty", "full"] = "empty",
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CityRisk:
    """Stations ranked by empty or full risk at ``window`` minutes (interim, forecast range)."""
    horizons = load_project_config().forecast.horizons_min
    if window not in horizons:
        raise ApiError(422, "invalid_request", f"window must be one of {horizons}")
    with _engine(request).connect() as conn:
        if city not in {c["city_code"] for c in queries.cities(conn)}:
            raise ApiError(404, "city_not_found", f"no city {city!r}")
        stations = {s["station_key"]: s for s in queries.stations(conn, city=city)}
        rows = queries.city_forecast(conn, city)
    if not rows:
        raise ApiError(404, "forecast_not_found", f"no forecast for city {city!r}")
    issued = rows[0]["issued_at"]
    forecast_age = (datetime.now(UTC) - issued).total_seconds()
    limit_s = timedelta(minutes=load_project_config().serving.stale_after_min).total_seconds()
    if forecast_age > limit_s:
        raise stale(f"forecasts for {city!r} are older than {limit_s / 60:g} min")
    by_station: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_station.setdefault(row["station_key"], []).append(row)
    ranked: list[tuple[tuple[int, float], RiskStation]] = []
    model_version = ""
    for station_key, forecasts in by_station.items():
        station = stations.get(station_key)
        at_window = next((f for f in forecasts if f["horizon_min"] == window), None)
        if station is None or at_window is None:
            continue
        model_version = at_window["model_version"]
        capacity = int(station["capacity"])
        p10, p50, p90 = (float(at_window[k]) for k in ("bikes_p10", "bikes_p50", "bikes_p90"))
        levels = {"empty": risk.empty_level(p10, p50), "full": risk.full_level(p50, p90, capacity)}
        item = RiskStation(
            station_key=station_key,
            name=station["name"],
            lat=station["lat"],
            lon=station["lon"],
            capacity=capacity,
            now=Status.model_validate(station["now"]) if station["now"] else None,
            horizon_min=window,
            bikes_p10=p10,
            bikes_p50=p50,
            bikes_p90=p90,
            empty_level=levels["empty"],
            full_level=levels["full"],
            eta_empty_min=risk.eta_min(forecasts, "empty", capacity),
            eta_full_min=risk.eta_min(forecasts, "full", capacity),
        )
        ranked.append((risk.rank_key(levels[kind], p50, capacity, kind), item))
    ranked.sort(key=lambda pair: (pair[0], pair[1].station_key))
    _cache(response, 60)
    return CityRisk(
        city=city,
        window_min=window,
        kind=kind,
        basis="forecast_range",
        issued_at=issued,
        model_version=model_version,
        total=len(ranked),
        stations=[item for _, item in ranked[offset : offset + limit]],
    )


@router.get("/cities/{city}/netflow", response_model=CityNetFlow)
def city_net_flow(
    city: str,
    request: Request,
    response: Response,
    window: Annotated[int, Query(ge=15, le=120, multiple_of=15)] = 60,
) -> CityNetFlow:
    """Net change in bikes per station over ``window`` minutes (PRD 10.6), not trips."""
    with _engine(request).connect() as conn:
        if city not in {c["city_code"] for c in queries.cities(conn)}:
            raise ApiError(404, "city_not_found", f"no city {city!r}")
        end_ts = queries.latest_bucket(conn, city)
        if end_ts is None:
            raise ApiError(404, "netflow_not_found", f"no 15-min states for city {city!r}")
        limit_s = timedelta(minutes=load_project_config().serving.stale_after_min).total_seconds()
        if (datetime.now(UTC) - end_ts).total_seconds() > limit_s:
            raise stale(f"15-min states for {city!r} are older than {limit_s / 60:g} min")
        rows = queries.net_flow(conn, city, end_ts, window)
    _cache(response, 60)
    return CityNetFlow(
        city=city,
        window_min=window,
        ts=end_ts,
        stations=[_net_flow_station(row) for row in rows],
    )


def _net_flow_station(row: dict[str, Any]) -> NetFlowStation:
    excluded: Literal["rebalance", "closed", "missing"] | None = None
    if row["bikes_end"] is None or row["bikes_start"] is None:
        excluded = "missing"
    elif row["closed"]:
        excluded = "closed"
    elif row["rebalanced"]:
        excluded = "rebalance"
    net = None if excluded else float(row["bikes_end"]) - float(row["bikes_start"])
    return NetFlowStation(station_key=row["station_key"], net_flow=net, excluded=excluded)


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


WALK_FACTOR = 1.3  # PRD 16.4: haversine x 1.3, labelled "approx."
MIN_BIKES = 3.0  # PRD 15.1: alternatives need P50 >= 3 bikes
ALTERNATIVES = 2


def _require_station(conn: Connection, station_key: int) -> dict[str, Any]:
    rows = queries.stations(conn, station_key=station_key)
    if not rows:
        raise station_not_found(station_key)
    return rows[0]


@router.get("/stations/{station_key}/history", response_model=StationHistory)
def station_history(
    station_key: int,
    request: Request,
    response: Response,
    hours: Annotated[int, Query(ge=1, le=48)] = 24,
) -> StationHistory:
    """15-min states for the chart (PRD 16.4), ending at the newest bucket."""
    with _engine(request).connect() as conn:
        _require_station(conn, station_key)
        points = queries.history(conn, station_key, hours)
    _cache(response, 300)
    return StationHistory(
        station_key=station_key,
        hours=hours,
        points=[HistoryPoint.model_validate(p) for p in points],
    )


@router.get("/stations/{station_key}/alternatives", response_model=StationAlternatives)
def station_alternatives(
    station_key: int, request: Request, response: Response, horizon: int = 30
) -> StationAlternatives:
    """The 2 nearest stations with P50 >= 3 bikes at ``horizon`` (PRD 15.1, 16.4)."""
    horizons = load_project_config().forecast.horizons_min
    if horizon not in horizons:
        raise ApiError(422, "invalid_request", f"horizon must be one of {horizons}")
    with _engine(request).connect() as conn:
        origin = _require_station(conn, station_key)
        city = conn.execute(
            text("SELECT city_code FROM stations WHERE station_key = :k"), {"k": station_key}
        ).scalar_one()
        others = {s["station_key"]: s for s in queries.stations(conn, city=city)}
        rows = [r for r in queries.city_forecast(conn, city) if r["horizon_min"] == horizon]
    if not rows:
        raise ApiError(404, "forecast_not_found", f"no forecast for station {station_key}")
    candidates: list[Alternative] = []
    for row in rows:
        other = others.get(row["station_key"])
        if other is None or row["station_key"] == station_key or row["bikes_p50"] < MIN_BIKES:
            continue
        distance = haversine_m(origin["lat"], origin["lon"], other["lat"], other["lon"])
        candidates.append(
            Alternative(
                station_key=row["station_key"],
                name=other["name"],
                lat=other["lat"],
                lon=other["lon"],
                distance_m=round(distance, 1),
                walk_m=round(distance * WALK_FACTOR, 1),
                bikes_p10=row["bikes_p10"],
                bikes_p50=row["bikes_p50"],
                bikes_p90=row["bikes_p90"],
            )
        )
    candidates.sort(key=lambda alt: alt.distance_m)
    _cache(response, 300)
    return StationAlternatives(
        station_key=station_key,
        horizon_min=horizon,
        issued_at=rows[0]["issued_at"],
        alternatives=candidates[:ALTERNATIVES],
    )


@router.get("/stations/{station_key}/drivers", response_model=StationDrivers)
def station_drivers(
    station_key: int, request: Request, response: Response, horizon: int = 60
) -> StationDrivers:
    """TreeSHAP feature-group drivers of the latest P50 forecast, largest first (PRD 16.4)."""
    with _engine(request).connect() as conn:
        _require_station(conn, station_key)
        rows = queries.drivers(conn, station_key, horizon)
    if not rows:
        raise ApiError(404, "drivers_not_found", f"no drivers for station {station_key}")
    _cache(response, 300)
    ranked = sorted(rows, key=lambda r: abs(r["contribution"]), reverse=True)
    return StationDrivers(
        station_key=station_key,
        horizon_min=horizon,
        issued_at=rows[0]["issued_at"],
        drivers=[
            Driver(feature_group=r["feature_group"], contribution=r["contribution"]) for r in ranked
        ],
    )
