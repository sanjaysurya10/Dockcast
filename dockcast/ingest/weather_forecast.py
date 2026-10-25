"""Met Éireann point forecasts into ``weather_hourly`` (``kind='forecast'``) (PRD 5.1 D3, 9.5).

Verified 2026-10-25 on ``openaccess.pf.api.met.ie/metno-wdb2ts/locationforecast``: XML
(``weatherapi-0.4.xsd``) with ``<meta><model .../></meta>``; instant ``<time from=to>`` elements
carry temperature, windSpeed (m/s), humidity and cloudiness (%); 1-hour interval elements carry
precipitation (mm), assigned to the hour the interval ends (as in the observed ``rain`` column).
Only the first model's window (HARMONIE, ~45 h) is kept. ``issued_at`` is that model's
``runended`` time — when the forecast became available — so features at time ``t`` may use only
issues with ``issued_at < t`` (PRD 10.1, v2).
"""

import argparse
import time
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import pandas as pd
import structlog
from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert

from dockcast.config import CityConfig, get_env_settings, load_city_config
from dockcast.db.engine import make_engine
from dockcast.db.models import WeatherHourly
from dockcast.ingest.weather_history import WEATHER_COLUMNS, nan_to_none

log = structlog.get_logger(job="weather_forecast")


@dataclass(frozen=True)
class ForecastIssue:
    """One parsed forecast issue."""

    model: str
    issued_at: datetime
    frame: pd.DataFrame  # WEATHER_COLUMNS


def _ts(value: str) -> pd.Timestamp:
    return pd.Timestamp(value).tz_convert("UTC")


def _float(element: ET.Element | None, attr: str) -> float | None:
    if element is None or element.get(attr) is None:
        return None
    return float(element.get(attr, "nan"))


def parse_locationforecast(xml_text: str) -> ForecastIssue:
    """Parse a locationforecast response, keeping the first model's window.

    Args:
        xml_text: Response body.

    Returns:
        The issue with hourly rows in ``WEATHER_COLUMNS``.

    Raises:
        ValueError: If the document has no model metadata.
    """
    root = ET.fromstring(xml_text)
    model = root.find("meta/model")
    if model is None:
        raise ValueError("locationforecast without <meta><model>")
    window_start, window_end = _ts(model.get("from", "")), _ts(model.get("to", ""))
    instants: dict[pd.Timestamp, dict[str, float | None]] = {}
    precip: dict[pd.Timestamp, float | None] = {}
    for item in root.iterfind("product/time"):
        start, end = _ts(item.get("from", "")), _ts(item.get("to", ""))
        loc = item.find("location")
        if loc is None:
            continue
        if start == end:
            instants[start] = {
                "temp_c": _float(loc.find("temperature"), "value"),
                "wind_speed_ms": _float(loc.find("windSpeed"), "mps"),
                "humidity_pct": _float(loc.find("humidity"), "value"),
                "cloud_pct": _float(loc.find("cloudiness"), "percent"),
            }
        elif (end - start).total_seconds() == 3600:
            precip[end] = _float(loc.find("precipitation"), "value")
    rows = [
        {"ts": ts, **values, "precip_mm": precip.get(ts)}
        for ts, values in sorted(instants.items())
        if window_start <= ts <= window_end
    ]
    frame = pd.DataFrame(rows, columns=WEATHER_COLUMNS)
    return ForecastIssue(
        model=model.get("name", ""),
        issued_at=_ts(model.get("runended", "")).to_pydatetime(),
        frame=frame,
    )


def store_forecast(engine: Engine, city_code: str, issue: ForecastIssue) -> int:
    """Upsert one issue (idempotent on ``(city, ts, 'forecast', issued_at)``).

    Args:
        engine: Database engine.
        city_code: City code.
        issue: Parsed issue.

    Returns:
        Rows written.
    """
    records = [
        {"city_code": city_code, "kind": "forecast", "issued_at": issue.issued_at, **row}
        for row in nan_to_none(issue.frame)
    ]
    if not records:
        return 0
    stmt = (
        insert(WeatherHourly)
        .values(records)
        .on_conflict_do_nothing(index_elements=["city_code", "ts", "kind", "issued_at"])
        .returning(WeatherHourly.id)
    )
    with engine.begin() as conn:
        return len(conn.execute(stmt).all())


def fetch_and_store(engine: Engine, city: CityConfig, client: httpx.Client, url: str) -> int:
    """Fetch the forecast for the city centre and store it.

    Args:
        engine: Database engine.
        city: City configuration (centre point).
        client: HTTP client.
        url: Base ``locationforecast`` URL.

    Returns:
        Rows written (0 when the issue was already stored).
    """
    response = client.get(f"{url}?lat={city.centre_lat};long={city.centre_lon}")
    response.raise_for_status()
    issue = parse_locationforecast(response.text)
    written = store_forecast(engine, city.city_code, issue)
    log.info(
        "forecast_stored",
        model=issue.model,
        issued_at=issue.issued_at.isoformat(),
        hours=len(issue.frame),
        rows=written,
    )
    return written


def main(argv: Sequence[str] | None = None) -> None:
    """``python -m dockcast.ingest.weather_forecast [--loop]`` (hourly at minute 20)."""
    parser = argparse.ArgumentParser(description="Store Met Éireann point forecasts.")
    parser.add_argument("--loop", action="store_true", help="fetch every hour until stopped")
    args = parser.parse_args(argv)
    settings = get_env_settings()
    city = load_city_config(settings.city)
    engine = make_engine()
    with httpx.Client(headers={"User-Agent": settings.user_agent}, timeout=60) as client:
        while True:
            try:
                fetch_and_store(engine, city, client, settings.met_forecast_url)
            except Exception as exc:  # keep looping; next hour retries
                log.error("forecast_failed", error=f"{type(exc).__name__}: {exc}")
                if not args.loop:
                    raise
            if not args.loop:
                return
            now = datetime.now(UTC)
            seconds_past_hour = now.minute * 60 + now.second
            time.sleep((20 * 60 - seconds_past_hour) % 3600 or 3600)


if __name__ == "__main__":
    main()
