from pathlib import Path

import httpx
import pytest
import respx

from dockcast.ingest.historical.download import download_file, list_resources

pytestmark = pytest.mark.unit
CKAN = "https://ckan.test/package_show"
BASE = "https://data.test/download"


@respx.mock
def test_list_resources_marks_monthly_a_and_b_in_scope() -> None:
    resources = [
        {"format": "CSV", "name": "A", "url": f"{BASE}/dublinbike-historical-data-2021-10.csv"},
        {"format": "CSV", "name": "B", "url": f"{BASE}/dublin-bikes_station_status_052024.csv"},
        {"format": "CSV", "name": "Q", "url": f"{BASE}/dublinbikes_20180701_20181001.csv"},
        {"format": "GeoJSON", "name": "G", "url": f"{BASE}/stations.geojson"},
    ]
    respx.get(CKAN).mock(
        return_value=httpx.Response(200, json={"result": {"resources": resources}})
    )
    with httpx.Client() as client:
        listed = list_resources(CKAN, client)
    assert [(r.name, r.in_scope) for r in listed] == [("A", True), ("B", True), ("Q", False)]


@respx.mock
def test_download_file_streams_then_skips_existing(tmp_path: Path) -> None:
    route = respx.get(f"{BASE}/f.csv").mock(return_value=httpx.Response(200, content=b"a,b\n1,2\n"))
    dest = tmp_path / "hist" / "f.csv"
    with httpx.Client() as client:
        assert download_file(f"{BASE}/f.csv", dest, client) == 8
        assert download_file(f"{BASE}/f.csv", dest, client) == 8
    assert route.call_count == 1
    assert not dest.with_suffix(".csv.part").exists()
