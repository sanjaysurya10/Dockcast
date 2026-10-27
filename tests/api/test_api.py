"""API contract tests (PRD 15, 19.5) against a migrated test database."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dockcast.api.app import create_app
from dockcast.serving.bundle import Bundle
from dockcast.serving.forecast import register, run_cycle
from tests.integration.test_forecast_cycle import seed_live
from tests.unit.test_serving import tiny_bundle

pytestmark = pytest.mark.api


@pytest.fixture
def seeded(db_engine: Engine, tmp_path: Path) -> Iterator[tuple[TestClient, dict[str, int]]]:
    now = datetime.now(UTC)
    keys = seed_live(db_engine, now - timedelta(seconds=30), hours=3)
    bundle = Bundle(tiny_bundle(tmp_path))
    register(db_engine, bundle)
    run_cycle(db_engine, bundle, now)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO collector_runs (city_code, started_at, finished_at, status) "
                "VALUES ('dublin', :t, :t, 'ok')"
            ),
            {"t": now - timedelta(seconds=40)},
        )
    yield TestClient(create_app(db_engine, rate_limit="1000/minute")), keys


def test_health_is_ok_when_collector_and_forecasts_are_fresh(
    seeded: tuple[TestClient, dict[str, int]],
) -> None:
    client, _ = seeded
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["db"] == "ok"
    assert body["last_forecast_issued_at"] is not None


def test_cities_and_stations(seeded: tuple[TestClient, dict[str, int]]) -> None:
    client, keys = seeded
    cities = client.get("/v1/cities")
    assert cities.status_code == 200 and cities.json()[0]["city_code"] == "dublin"
    assert cities.headers["cache-control"] == "public, max-age=3600"
    stations = client.get("/v1/cities/dublin/stations").json()
    assert {s["station_key"] for s in stations} == set(keys.values())
    assert all(s["now"]["bikes"] + s["now"]["docks"] == 30 for s in stations)
    assert all(s["risk"] is None for s in stations)  # event models arrive in M10


def test_forecast_matches_prd_shape(seeded: tuple[TestClient, dict[str, int]]) -> None:
    client, keys = seeded
    response = client.get(f"/v1/stations/{keys['A']}/forecast")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "FIRST" and body["capacity"] == 30
    assert [f["horizon_min"] for f in body["forecasts"]] == [30, 60, 120]
    assert all(f["bikes_p10"] <= f["bikes_p50"] <= f["bikes_p90"] for f in body["forecasts"])
    assert body["model_version"] == "lgbm-q-test-h30"
    assert body["data_freshness"]["stale"] is False


def test_unknown_station_is_404_with_error_body(seeded: tuple[TestClient, dict[str, int]]) -> None:
    client, _ = seeded
    for path in ("/v1/stations/99999", "/v1/stations/99999/forecast"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "station_not_found"
    assert client.get("/v1/cities/paris/stations").json()["error"]["code"] == "city_not_found"
    assert client.get("/v1/stations/abc").json()["error"]["code"] == "invalid_request"


def test_stale_forecast_is_503_with_retry_after(
    seeded: tuple[TestClient, dict[str, int]], db_engine: Engine
) -> None:
    client, keys = seeded
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE forecasts SET issued_at = issued_at - INTERVAL '2 hours'"))
    response = client.get(f"/v1/stations/{keys['A']}/forecast")
    assert response.status_code == 503 and "retry-after" in response.headers
    assert response.json()["error"]["code"] == "data_stale"
    assert client.get("/health").json()["status"] == "degraded"


def test_model_summary_lists_champions_with_backtest_metrics(
    seeded: tuple[TestClient, dict[str, int]],
) -> None:
    client, _ = seeded
    body = client.get("/v1/model/summary").json()
    assert [c["horizon_min"] for c in body["champions"]] == [30, 60, 120]
    assert body["champions"][0]["metrics"]["e1_run_id"] == "e1-test"
    assert body["last_retrain"].startswith("2026-10-26")


def test_rate_limit_returns_429(db_engine: Engine) -> None:
    client = TestClient(create_app(db_engine, rate_limit="2/minute"))
    codes = [client.get("/v1/cities").status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert client.get("/v1/cities").json()["error"]["code"] == "rate_limited"


def test_openapi_lists_the_m5_endpoints(db_engine: Engine) -> None:
    paths = TestClient(create_app(db_engine)).get("/openapi.json").json()["paths"]
    for path in (
        "/health",
        "/v1/cities",
        "/v1/cities/{city}/stations",
        "/v1/stations/{station_key}",
        "/v1/stations/{station_key}/forecast",
        "/v1/model/summary",
    ):
        assert path in paths
