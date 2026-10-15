import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from dockcast.ingest.gbfs import (
    GbfsError,
    fetch_json,
    parse_feed_urls,
    parse_station_information,
    parse_station_status,
)

pytestmark = pytest.mark.unit
FIXTURES = Path(__file__).parent.parent / "fixtures" / "gbfs"


def _load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def test_parse_feed_urls_uses_first_language() -> None:
    feeds = parse_feed_urls(_load("gbfs"))
    assert feeds["station_status"].endswith("/v2/station_status.json")
    assert "station_information" in feeds


def test_parse_station_information() -> None:
    infos = {i.station_id: i for i in parse_station_information(_load("station_information"))}
    assert infos["1"].name == "CLARENDON ROW"
    assert infos["1"].capacity == 31
    assert isinstance(infos["1"].lat, float)


def test_parse_station_status_converts_epoch_to_utc() -> None:
    statuses = {s.station_id: s for s in parse_station_status(_load("station_status"))}
    one = statuses["1"]
    assert one.bikes_available == 8 and one.docks_available == 23
    assert one.last_reported == datetime.fromtimestamp(1792029806, tz=UTC)
    assert statuses["118"].is_renting is False


@respx.mock
def test_fetch_json_retries_server_errors_with_backoff() -> None:
    route = respx.get("https://feed.test/s.json").mock(
        side_effect=[httpx.Response(503), httpx.ConnectError("boom"), httpx.Response(200, json={})]
    )
    sleeps: list[float] = []
    with httpx.Client() as client:
        assert fetch_json(client, "https://feed.test/s.json", [1, 4, 16], sleeps.append) == {}
    assert route.call_count == 3
    assert sleeps == [1, 4]


@respx.mock
def test_fetch_json_does_not_retry_client_errors() -> None:
    route = respx.get("https://feed.test/s.json").mock(return_value=httpx.Response(404))
    with httpx.Client() as client, pytest.raises(GbfsError):
        fetch_json(client, "https://feed.test/s.json", [1, 4, 16], lambda _: None)
    assert route.call_count == 1


@respx.mock
def test_fetch_json_gives_up_after_all_attempts() -> None:
    route = respx.get("https://feed.test/s.json").mock(return_value=httpx.Response(500))
    with httpx.Client() as client, pytest.raises(GbfsError):
        fetch_json(client, "https://feed.test/s.json", [1, 4, 16], lambda _: None)
    assert route.call_count == 4
