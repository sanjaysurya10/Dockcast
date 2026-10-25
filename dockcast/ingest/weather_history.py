"""Observed hourly weather from Met Éireann station files into ``weather_hourly`` (PRD 9.5, D4).

Verified 2026-10-25 on ``hly532.csv`` (Dublin Airport): a free-text preamble, then a ``date,...``
header; ``date`` is "Date and Time (utc)" as ``dd-mon-yyyy HH:MM``; ``rain`` is the amount in the
hour ending at ``date`` (mm), ``wdsp`` knots, ``clamt`` cloud cover in oktas (0-8). Recent rows
carry indicator 111 ("investigation required"), i.e. not yet quality-controlled; values are kept.
"""

import io
import math
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd
import structlog
from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert

from dockcast.config import CityConfig, get_env_settings, load_city_config
from dockcast.db.engine import make_engine
from dockcast.db.models import WeatherHourly

log = structlog.get_logger(job="weather_history")

KNOT_TO_MS = 0.514444
WEATHER_COLUMNS = ["ts", "temp_c", "precip_mm", "wind_speed_ms", "humidity_pct", "cloud_pct"]


def parse_station_csv(text: str, start: datetime | None = None) -> pd.DataFrame:
    """Parse a Met Éireann hourly station file into canonical weather columns.

    Args:
        text: Full file contents.
        start: Drop rows before this UTC time.

    Returns:
        Columns ``ts`` (UTC) plus ``temp_c, precip_mm, wind_speed_ms, humidity_pct, cloud_pct``;
        variables a station does not report are NaN.
    """
    lines = text.splitlines()
    header_at = next(i for i, line in enumerate(lines) if line.startswith("date,"))
    raw = pd.read_csv(io.StringIO("\n".join(lines[header_at:])), dtype=str)
    raw.columns = [c.strip() for c in raw.columns]

    def numeric(name: str) -> pd.Series:
        if name not in raw:
            return pd.Series(float("nan"), index=raw.index)
        return pd.to_numeric(raw[name].str.strip(), errors="coerce")

    oktas = numeric("clamt").where(lambda s: s.between(0, 8))
    frame = pd.DataFrame(
        {
            "ts": pd.to_datetime(raw["date"].str.strip(), format="%d-%b-%Y %H:%M", utc=True),
            "temp_c": numeric("temp"),
            "precip_mm": numeric("rain"),
            "wind_speed_ms": numeric("wdsp") * KNOT_TO_MS,
            "humidity_pct": numeric("rhum"),
            "cloud_pct": oktas / 8 * 100,
        }
    )
    if start is not None:
        frame = frame[frame["ts"] >= pd.Timestamp(start)]
    return frame.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


def nan_to_none(frame: pd.DataFrame) -> list[dict[str, object]]:
    """Rows as dicts with NaN replaced by ``None`` (SQL NULL).

    Args:
        frame: Any frame.

    Returns:
        One dict per row.
    """
    return [
        {str(k): (None if isinstance(v, float) and math.isnan(v) else v) for k, v in row.items()}
        for row in frame.to_dict("records")
    ]


def store_observed(engine: Engine, city_code: str, frame: pd.DataFrame) -> int:
    """Upsert observed rows (``kind='observed'``, ``issued_at`` NULL).

    Args:
        engine: Database engine.
        city_code: City code.
        frame: Output of :func:`parse_station_csv`.

    Returns:
        Number of rows written.
    """
    records = [
        {"city_code": city_code, "kind": "observed", "issued_at": None, **row}
        for row in nan_to_none(frame)
    ]
    written = 0
    with engine.begin() as conn:
        for chunk_start in range(0, len(records), 5000):
            chunk = records[chunk_start : chunk_start + 5000]
            base = insert(WeatherHourly).values(chunk)
            upsert = base.on_conflict_do_update(
                index_elements=["city_code", "ts", "kind", "issued_at"],
                set_={c: base.excluded[c] for c in WEATHER_COLUMNS if c != "ts"},
            ).returning(WeatherHourly.id)
            written += len(conn.execute(upsert).all())
    return written


def load_history(
    engine: Engine, city: CityConfig, client: httpx.Client, raw_dir: Path | None = None
) -> int:
    """Download the station file, keep a raw copy, and upsert observations.

    Args:
        engine: Database engine.
        city: City configuration (``weather_history_url``, ``weather_history_start``).
        client: HTTP client.
        raw_dir: Where to keep the downloaded file (``data/raw/weather`` by default).

    Returns:
        Rows written.
    """
    response = client.get(city.weather_history_url)
    response.raise_for_status()
    target = raw_dir or get_env_settings().data_dir / "raw" / "weather"
    target.mkdir(parents=True, exist_ok=True)
    (target / city.weather_history_url.rsplit("/", 1)[-1]).write_bytes(response.content)
    start = datetime.fromisoformat(city.weather_history_start).replace(tzinfo=UTC)
    frame = parse_station_csv(response.text, start)
    written = store_observed(engine, city.city_code, frame)
    log.info(
        "weather_history_loaded",
        station=city.weather_station,
        rows=written,
        first=str(frame["ts"].min()),
        last=str(frame["ts"].max()),
    )
    return written


def main() -> None:
    """Entry point for ``make weather``."""
    settings = get_env_settings()
    with httpx.Client(
        headers={"User-Agent": settings.user_agent}, timeout=180, follow_redirects=True
    ) as client:
        load_history(make_engine(), load_city_config(settings.city), client)


if __name__ == "__main__":
    main()
