"""API contract tests (PRD 15, 19.5) against a migrated test database."""

import json
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


def test_city_risk_ranks_stations_from_the_forecast_range(
    seeded: tuple[TestClient, dict[str, int]],
) -> None:
    client, keys = seeded
    response = client.get("/v1/cities/dublin/risk?window=60&kind=empty&limit=200")
    assert response.status_code == 200
    body = response.json()
    assert body["basis"] == "forecast_range" and body["window_min"] == 60
    assert body["total"] == 2 and {s["station_key"] for s in body["stations"]} == set(keys.values())
    assert body["model_version"] == "lgbm-q-test-h60"
    rank = {"likely": 0, "possible": 1, "low": 2}
    order = [(rank[s["empty_level"]], s["bikes_p50"]) for s in body["stations"]]
    assert order == sorted(order)
    first = body["stations"][0]
    assert first["horizon_min"] == 60 and first["now"] is not None
    assert first["bikes_p10"] <= first["bikes_p50"] <= first["bikes_p90"]
    page = client.get("/v1/cities/dublin/risk?window=60&kind=full&limit=1&offset=1").json()
    assert page["total"] == 2 and len(page["stations"]) == 1


def test_city_risk_rejects_bad_input_and_stale_forecasts(
    seeded: tuple[TestClient, dict[str, int]], db_engine: Engine
) -> None:
    client, _ = seeded
    assert client.get("/v1/cities/dublin/risk?window=45").json()["error"]["code"] == (
        "invalid_request"
    )
    assert client.get("/v1/cities/dublin/risk?kind=both").status_code == 422
    assert client.get("/v1/cities/dublin/risk?limit=201").status_code == 422
    assert client.get("/v1/cities/paris/risk").json()["error"]["code"] == "city_not_found"
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE forecasts SET issued_at = issued_at - INTERVAL '2 hours'"))
    response = client.get("/v1/cities/dublin/risk")
    assert response.status_code == 503 and response.json()["error"]["code"] == "data_stale"


def test_history_alternatives_and_drivers(seeded: tuple[TestClient, dict[str, int]]) -> None:
    client, keys = seeded
    history = client.get(f"/v1/stations/{keys['A']}/history?hours=6").json()
    assert history["hours"] == 6 and 1 <= len(history["points"]) <= 24
    stamps = [p["ts"] for p in history["points"]]
    assert stamps == sorted(stamps)
    assert all(p["bikes"] + p["docks"] == 30 for p in history["points"] if p["bikes"] is not None)
    assert client.get(f"/v1/stations/{keys['A']}/history?hours=49").status_code == 422

    alternatives = client.get(f"/v1/stations/{keys['A']}/alternatives?horizon=30").json()
    assert alternatives["horizon_min"] == 30 and len(alternatives["alternatives"]) <= 2
    for alt in alternatives["alternatives"]:
        assert alt["station_key"] != keys["A"] and alt["bikes_p50"] >= 3
        assert alt["walk_m"] == pytest.approx(alt["distance_m"] * 1.3, abs=0.2)
    assert client.get(f"/v1/stations/{keys['A']}/alternatives?horizon=45").status_code == 422

    drivers = client.get(f"/v1/stations/{keys['A']}/drivers?horizon=60").json()
    sizes = [abs(d["contribution"]) for d in drivers["drivers"]]
    assert drivers["horizon_min"] == 60 and sizes == sorted(sizes, reverse=True)
    assert {d["feature_group"] for d in drivers["drivers"]} >= {"lags", "calendar"}
    missing = client.get("/v1/stations/99999/drivers").json()["error"]["code"]
    assert missing == "station_not_found"


def test_net_flow_is_the_change_over_the_window_without_rebalancing(
    seeded: tuple[TestClient, dict[str, int]], db_engine: Engine
) -> None:
    client, keys = seeded
    body = client.get("/v1/cities/dublin/netflow?window=60").json()
    assert body["window_min"] == 60 and {s["station_key"] for s in body["stations"]} == set(
        keys.values()
    )
    end = datetime.fromisoformat(body["ts"])
    with db_engine.connect() as conn:
        bikes = dict(
            conn.execute(
                text(
                    "SELECT ts, bikes_last FROM station_status_15m WHERE station_key = :k "
                    "AND ts IN (:end, :start)"
                ),
                {"k": keys["A"], "end": end, "start": end - timedelta(minutes=60)},
            ).all()
        )
    expected = bikes[end] - bikes[end - timedelta(minutes=60)]
    station_a = next(s for s in body["stations"] if s["station_key"] == keys["A"])
    assert station_a["excluded"] is None and station_a["net_flow"] == pytest.approx(expected)

    with db_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE station_status_15m SET rebalance_flag = true "
                "WHERE station_key = :k AND ts = :t"
            ),
            {"k": keys["A"], "t": end - timedelta(minutes=15)},
        )
    flagged = client.get("/v1/cities/dublin/netflow").json()["stations"]
    station_a = next(s for s in flagged if s["station_key"] == keys["A"])
    assert station_a == {"station_key": keys["A"], "net_flow": None, "excluded": "rebalance"}
    assert client.get("/v1/cities/dublin/netflow?window=20").status_code == 422
    assert client.get("/v1/cities/paris/netflow").json()["error"]["code"] == "city_not_found"


def test_drivers_keep_only_the_latest_issue(
    seeded: tuple[TestClient, dict[str, int]], db_engine: Engine
) -> None:
    with db_engine.connect() as conn:
        issues = conn.execute(text("SELECT count(DISTINCT issued_at) FROM forecast_drivers"))
        assert issues.scalar() == 1


def test_backtest_and_summary_health(
    seeded: tuple[TestClient, dict[str, int]], db_engine: Engine
) -> None:
    client, _ = seeded
    assert client.get("/v1/model/backtest").json()["error"]["code"] == "backtest_not_found"
    with db_engine.begin() as conn:
        for run, folds in (("small", 1), ("full", 2)):
            for fold in range(1, folds + 1):
                conn.execute(
                    text(
                        "INSERT INTO backtest_results (run_id, experiment, model_name, fold, "
                        "horizon_min, slice_kind, slice_value, n, mae, coverage_80) VALUES "
                        "(:run, 'E1', 'lgbm_global', :fold, 60, 'overall', 'all', 100, :mae, 0.8)"
                    ),
                    {"run": run, "fold": fold, "mae": 1.0 + fold},
                )
    body = client.get("/v1/model/backtest?experiment=E1").json()
    assert body["run_id"] == "full"  # most folds wins
    row = body["rows"][0]
    assert row["folds"] == 2 and row["n"] == 200 and row["mae"] == pytest.approx(2.5)
    picked = client.get("/v1/model/backtest?run_id=small").json()
    assert picked["run_id"] == "small"
    assert client.get("/v1/model/backtest?slice_kind=station").status_code == 422

    health = client.get("/v1/model/summary").json()["data_health"]
    assert health["collector_polls_7d"] == 1 and health["expected_polls_7d"] == 10080
    assert health["stations_modelled"] == 2 and health["train_end"] is not None


def test_error_analysis_is_served_from_the_reports_folder(
    seeded: tuple[TestClient, dict[str, int]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = seeded
    from dockcast.api.routes import model as model_routes
    from dockcast.config import EnvSettings

    monkeypatch.setattr(model_routes, "get_env_settings", lambda: EnvSettings(reports_dir=tmp_path))
    assert client.get("/v1/model/error-analysis").status_code == 404
    payload = {
        "run_id": "r1", "e2_run_id": None, "git_commit": "abc",
        "generated_at": "2026-11-01T00:00:00Z",
        "folds": [{"fold": 1, "train_end": "2026-05-05T21:45:00Z",
                   "test_start": "2026-05-05T23:45:00Z", "test_end": "2026-05-12T23:45:00Z"}],
        "horizon_growth": [{"horizon_min": 60, "model_name": "lgbm_global", "mae": 1.46}],
        "heatmap_hours": [0, 1], "heatmap": [{"station_key": 1, "name": "A", "mae": [0.5, None]}],
    }  # fmt: skip
    (tmp_path / "error_analysis.json").write_text(json.dumps(payload), encoding="utf-8")
    body = client.get("/v1/model/error-analysis").json()
    assert body["heatmap"][0]["mae"] == [0.5, None] and body["folds"][0]["fold"] == 1
