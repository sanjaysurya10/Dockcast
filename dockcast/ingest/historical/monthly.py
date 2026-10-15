"""Monthly backfill: load newly published historical months only (PRD 9.2 step 7)."""

from pathlib import Path

import httpx
import structlog
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from dockcast.config import PROJECT_ROOT, CityConfig, get_env_settings, load_city_config
from dockcast.db.engine import make_engine
from dockcast.db.models import DataQualityFile
from dockcast.ingest.historical.backfill import backfill
from dockcast.ingest.historical.download import HistoricalResource, download_file, list_resources
from dockcast.quality.gaps import refresh_gaps

log = structlog.get_logger(job="backfill_monthly")


def new_resources(
    listed: list[HistoricalResource], known_files: set[str]
) -> list[HistoricalResource]:
    """In-scope resources whose file has not been profiled yet.

    Args:
        listed: Resources from the CKAN listing.
        known_files: File names already in ``data_quality_files``.

    Returns:
        Resources to download and load.
    """
    return [r for r in listed if r.in_scope and r.file_name not in known_files]


def backfill_new_months(
    engine: Engine,
    city: CityConfig,
    client: httpx.Client,
    hist_dir: Path,
    reports_dir: Path = PROJECT_ROOT / "reports",
) -> list[str]:
    """Download and load months not yet in ``data_quality_files``; refresh gaps if any.

    Args:
        engine: Database engine.
        city: City configuration.
        client: HTTP client.
        hist_dir: Download directory.
        reports_dir: Directory for ``data_profile.md`` and ``data_gaps.md``.

    Returns:
        File names loaded in this run.
    """
    with Session(engine) as session:
        known = set(session.scalars(select(DataQualityFile.file_name)))
    todo = new_resources(list_resources(city.ckan_package_url, client), known)
    if not todo:
        log.info("no_new_months")
        return []
    paths = []
    for resource in todo:
        download_file(resource.url, hist_dir / resource.file_name, client)
        paths.append(hist_dir / resource.file_name)
    backfill(hist_dir, engine, city, client, reports_dir / "data_profile.md", files=paths)
    refresh_gaps(engine, reports_dir / "data_gaps.md")
    names = [p.name for p in paths]
    log.info("loaded_new_months", files=names)
    return names


def main() -> None:
    """Entry point for ``make backfill-new``."""
    settings = get_env_settings()
    with httpx.Client(
        headers={"User-Agent": settings.user_agent}, timeout=120, follow_redirects=True
    ) as client:
        backfill_new_months(
            make_engine(),
            load_city_config(settings.city),
            client,
            settings.data_dir / "raw" / "hist",
        )


if __name__ == "__main__":
    main()
