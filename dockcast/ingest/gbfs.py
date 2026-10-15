"""Fetch and parse the live GBFS feed (PRD 5.2, 9.1).

Verified against the Dublin feed on 2026-10-15: GBFS 2.3 served by JCDecaux at
``api.cyclocity.fr``; feeds are keyed by language (``"fr"``); no trip-level feeds.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import structlog

log = structlog.get_logger(job="gbfs")

JsonDict = dict[str, Any]


class GbfsError(RuntimeError):
    """Raised when the feed cannot be fetched or does not have the expected shape."""


@dataclass(frozen=True)
class StationInfo:
    """Static station attributes from ``station_information``."""

    station_id: str
    name: str
    lat: float
    lon: float
    capacity: int
    address: str | None


@dataclass(frozen=True)
class StationStatus:
    """One station's state from ``station_status``."""

    station_id: str
    bikes_available: int
    docks_available: int
    is_installed: bool
    is_renting: bool
    is_returning: bool
    last_reported: datetime | None


def epoch_to_utc(value: object) -> datetime | None:
    """Convert a GBFS POSIX timestamp to an aware UTC datetime (``None`` passes through)."""
    if value is None:
        return None
    return datetime.fromtimestamp(int(cast(int, value)), tz=UTC)


def parse_feed_urls(gbfs_doc: JsonDict) -> dict[str, str]:
    """Map feed name to URL from a ``gbfs.json`` document (first language present).

    Args:
        gbfs_doc: Parsed ``gbfs.json``.

    Returns:
        ``{feed_name: url}``.
    """
    languages = cast(dict[str, JsonDict], gbfs_doc["data"])
    if not languages:
        raise GbfsError("gbfs.json lists no languages")
    feeds = next(iter(languages.values()))["feeds"]
    return {str(feed["name"]): str(feed["url"]) for feed in feeds}


def parse_station_information(doc: JsonDict) -> list[StationInfo]:
    """Parse a ``station_information`` document.

    Args:
        doc: Parsed JSON.

    Returns:
        One record per station.
    """
    return [
        StationInfo(
            station_id=str(item["station_id"]),
            name=str(item["name"]),
            lat=float(item["lat"]),
            lon=float(item["lon"]),
            capacity=int(item["capacity"]),
            address=str(item["address"]) if item.get("address") else None,
        )
        for item in doc["data"]["stations"]
    ]


def parse_station_status(doc: JsonDict) -> list[StationStatus]:
    """Parse a ``station_status`` document.

    Args:
        doc: Parsed JSON.

    Returns:
        One record per station.
    """
    return [
        StationStatus(
            station_id=str(item["station_id"]),
            bikes_available=int(item["num_bikes_available"]),
            docks_available=int(item["num_docks_available"]),
            is_installed=bool(item["is_installed"]),
            is_renting=bool(item["is_renting"]),
            is_returning=bool(item["is_returning"]),
            last_reported=epoch_to_utc(item.get("last_reported")),
        )
        for item in doc["data"]["stations"]
    ]


def fetch_json(
    client: httpx.Client,
    url: str,
    backoff_s: list[float],
    sleep: Callable[[float], None] = time.sleep,
) -> JsonDict:
    """GET ``url`` as JSON, retrying on network/5xx errors with the given backoff.

    Args:
        client: HTTP client (carries timeout and User-Agent).
        url: URL to fetch.
        backoff_s: Sleep before each retry; ``len(backoff_s)`` retries after the first attempt.
        sleep: Injected for tests.

    Returns:
        The parsed JSON object.

    Raises:
        GbfsError: After all attempts fail.
    """
    last_error: Exception | None = None
    for attempt, delay in enumerate([0.0, *backoff_s]):
        if delay:
            sleep(delay)
        try:
            response = client.get(url)
            if response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"server error {response.status_code}",
                    request=response.request,
                    response=response,
                )
            response.raise_for_status()
            return cast(JsonDict, response.json())
        except (httpx.TransportError, httpx.HTTPStatusError, ValueError) as exc:
            last_error = exc
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                break
            log.warning("fetch_retry", url=url, attempt=attempt + 1, error=str(exc))
    raise GbfsError(f"failed to fetch {url}: {last_error}")
