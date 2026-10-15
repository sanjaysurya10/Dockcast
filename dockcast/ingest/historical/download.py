"""Download the historical Dublin Bikes monthly CSVs listed on data.gov.ie (PRD 9.2 step 1)."""

import re
from dataclasses import dataclass
from pathlib import Path

import httpx
import structlog

from dockcast.config import get_env_settings, load_city_config

log = structlog.get_logger(job="backfill_download")

# Monthly files in scope (PRD 5.3). Quarterly 2018-2021 files use another layout and are listed
# as out of scope until the owner decides whether to include them.
FORMAT_A_FILE = re.compile(r"^dublinbike-historical-data-(\d{4})-(\d{2})\.csv$")
FORMAT_B_FILE = re.compile(r"^dublin-bikes_station_status_(\d{2})(\d{4})\.csv$")


@dataclass(frozen=True)
class HistoricalResource:
    """One CSV resource from the CKAN listing."""

    name: str
    url: str
    file_name: str
    in_scope: bool


def list_resources(package_url: str, client: httpx.Client) -> list[HistoricalResource]:
    """List CSV resources in the CKAN package, marking monthly A/B files as in scope.

    Args:
        package_url: CKAN ``package_show`` URL.
        client: HTTP client.

    Returns:
        All CSV resources, in listing order.
    """
    response = client.get(package_url)
    response.raise_for_status()
    resources: list[HistoricalResource] = []
    for item in response.json()["result"]["resources"]:
        if str(item.get("format", "")).upper() != "CSV":
            continue
        url = str(item["url"])
        file_name = url.rsplit("/", 1)[-1]
        in_scope = bool(FORMAT_A_FILE.match(file_name) or FORMAT_B_FILE.match(file_name))
        resources.append(HistoricalResource(str(item["name"]), url, file_name, in_scope))
    return resources


def download_file(url: str, dest: Path, client: httpx.Client) -> int:
    """Stream ``url`` to ``dest`` via a ``.part`` file; skip if ``dest`` already exists.

    Args:
        url: Source URL.
        dest: Final path.
        client: HTTP client.

    Returns:
        Size of ``dest`` in bytes.
    """
    if dest.exists() and dest.stat().st_size > 0:
        return dest.stat().st_size
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with part.open("wb") as fh:
            for chunk in response.iter_bytes(1 << 20):
                fh.write(chunk)
    part.replace(dest)
    return dest.stat().st_size


def download_all(dest_dir: Path | None = None) -> list[Path]:
    """Download every in-scope historical CSV to ``data/raw/hist``.

    Args:
        dest_dir: Override for the destination directory.

    Returns:
        Paths of the downloaded (or already present) files.
    """
    settings = get_env_settings()
    city = load_city_config(settings.city)
    target = dest_dir or settings.data_dir / "raw" / "hist"
    paths: list[Path] = []
    headers = {"User-Agent": settings.user_agent}
    with httpx.Client(headers=headers, timeout=120, follow_redirects=True) as client:
        for res in list_resources(city.ckan_package_url, client):
            if not res.in_scope:
                log.info("skip_out_of_scope", name=res.name)
                continue
            size = download_file(res.url, target / res.file_name, client)
            log.info("downloaded", file=res.file_name, bytes=size)
            if size == 0:
                log.warning("empty_file", file=res.file_name)
            paths.append(target / res.file_name)
    return paths


if __name__ == "__main__":
    download_all()
