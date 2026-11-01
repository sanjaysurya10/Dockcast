import pytest

from dockcast.api import openapi_export

pytestmark = pytest.mark.unit


def test_committed_openapi_matches_the_app() -> None:
    committed = openapi_export.OPENAPI_PATH.read_text(encoding="utf-8")
    assert committed == openapi_export.render(openapi_export.openapi_document()), (
        "web/openapi.json is stale: run `make web-api`"
    )


def test_openapi_lists_the_v1_routes() -> None:
    paths = openapi_export.openapi_document()["paths"]
    assert "/v1/stations/{station_key}/forecast" in paths and "/health" in paths
