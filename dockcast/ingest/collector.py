"""Live collector: poll GBFS ``station_status`` every minute and store raw rows (PRD 9.1)."""

import gzip
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import structlog
from sqlalchemy.orm import Session, sessionmaker

from dockcast.config import (
    CityConfig,
    CollectorConfig,
    get_env_settings,
    load_city_config,
    load_project_config,
)
from dockcast.db.engine import make_engine, make_session_factory
from dockcast.db.models import CollectorRun
from dockcast.db.queries import (
    StationRecord,
    ensure_city,
    insert_status_rows,
    station_keys,
    upsert_stations,
)
from dockcast.ingest.gbfs import (
    JsonDict,
    StationStatus,
    epoch_to_utc,
    fetch_json,
    parse_feed_urls,
    parse_station_information,
    parse_station_status,
)

log = structlog.get_logger(job="collector")


def utc_now() -> datetime:
    """Current UTC time truncated to the second."""
    return datetime.now(UTC).replace(microsecond=0)


def archive_path(archive_dir: Path, observed_at: datetime) -> Path:
    """Path for a raw response: ``<dir>/YYYY/MM/DD/HHMM.json.gz`` (UTC).

    Args:
        archive_dir: Root of the GBFS archive.
        observed_at: Poll time.

    Returns:
        The archive file path.
    """
    return archive_dir / observed_at.strftime("%Y/%m/%d/%H%M.json.gz")


def status_rows(
    statuses: list[StationStatus], keys: dict[str, int], observed_at: datetime
) -> list[dict[str, object]]:
    """Convert parsed statuses to ``station_status_raw`` rows for known stations.

    Args:
        statuses: Parsed station statuses.
        keys: ``{source_id: station_key}``.
        observed_at: Poll time.

    Returns:
        Rows ready for insertion.
    """
    return [
        {
            "station_key": keys[s.station_id],
            "observed_at": observed_at,
            "last_reported": s.last_reported,
            "bikes_available": s.bikes_available,
            "docks_available": s.docks_available,
            "is_renting": s.is_renting,
            "is_returning": s.is_returning,
            "source": "live",
        }
        for s in statuses
        if s.station_id in keys
    ]


def sync_station_information(
    session: Session,
    client: httpx.Client,
    city: CityConfig,
    backoff_s: list[float],
    now: datetime,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, str]:
    """Upsert the city and its stations from the live ``station_information`` feed.

    Args:
        session: Open session (caller commits).
        client: HTTP client.
        city: City configuration.
        backoff_s: Retry backoff.
        now: Timestamp recorded as first/last seen.
        sleep: Sleep function (injected for tests).

    Returns:
        ``{feed_name: url}`` discovered from ``gbfs.json``.
    """
    feeds = parse_feed_urls(fetch_json(client, city.gbfs_root_url, backoff_s, sleep))
    infos = parse_station_information(
        fetch_json(client, feeds["station_information"], backoff_s, sleep)
    )
    records = [StationRecord(i.station_id, i.name, i.lat, i.lon, i.capacity) for i in infos]
    ensure_city(session, city)
    upsert_stations(session, city.city_code, records, now)
    log.info("station_info_synced", stations=len(infos))
    return feeds


class Collector:
    """Stateful poller; one instance per city."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        client: httpx.Client,
        city: CityConfig,
        config: CollectorConfig,
        archive_dir: Path,
        clock: Callable[[], datetime] = utc_now,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Create a collector.

        Args:
            session_factory: DB session factory.
            client: HTTP client with timeout and User-Agent set.
            city: City configuration (needs ``gbfs_root_url``).
            config: Collector settings.
            archive_dir: Root directory for raw JSON archives.
            clock: Returns the current UTC time.
            sleep: Sleep function (injected for tests).
        """
        self._sessions = session_factory
        self._client = client
        self._city = city
        self._config = config
        self._archive_dir = archive_dir
        self._clock = clock
        self._sleep = sleep
        self._feeds: dict[str, str] = {}
        self._keys: dict[str, int] = {}
        self._info_refreshed_at: datetime | None = None

    def _fetch(self, url: str) -> JsonDict:
        return fetch_json(self._client, url, self._config.retry_backoff_s, self._sleep)

    def _refresh_station_info(self, session: Session, now: datetime) -> None:
        self._feeds = sync_station_information(
            session, self._client, self._city, self._config.retry_backoff_s, now, self._sleep
        )
        self._keys = station_keys(session, self._city.city_code)
        self._info_refreshed_at = now

    def _info_due(self, now: datetime) -> bool:
        if self._info_refreshed_at is None:
            return True
        return now - self._info_refreshed_at >= timedelta(hours=self._config.station_info_refresh_h)

    def _archive(self, doc: JsonDict, observed_at: datetime) -> None:
        path = archive_path(self._archive_dir, observed_at)
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump(doc, fh)

    def _check_feed_freshness(self, doc: JsonDict, run: CollectorRun, now: datetime) -> None:
        # Owner decision 2026-10-15: staleness is judged on the feed's top-level last_updated.
        # Per-station last_reported does not advance when counts change in the Dublin feed, so
        # the PRD 9.1 per-row rule is not applied; flat-lined stations are handled in M2 cleaning.
        run.feed_last_updated = epoch_to_utc(doc.get("last_updated"))
        limit = timedelta(minutes=self._config.stale_after_min)
        if run.feed_last_updated is None or now - run.feed_last_updated > limit:
            log.warning("feed_stale", feed_last_updated=str(run.feed_last_updated))

    def poll_once(self) -> CollectorRun:
        """Run one poll cycle and record it in ``collector_runs``.

        Returns:
            The persisted run record.
        """
        started = self._clock()
        run = CollectorRun(city_code=self._city.city_code, started_at=started, status="error")
        try:
            with self._sessions() as session:
                if self._info_due(started):
                    self._refresh_station_info(session, started)
                doc = self._fetch(self._feeds["station_status"])
                self._archive(doc, started)
                statuses = parse_station_status(doc)
                if any(s.station_id not in self._keys for s in statuses):
                    self._refresh_station_info(session, started)
                rows = status_rows(statuses, self._keys, started)
                run.rows_written = insert_status_rows(session, rows)
                run.stations_seen = len(statuses)
                run.status = "ok" if len(rows) == len(statuses) else "partial"
                self._check_feed_freshness(doc, run, started)
                session.commit()
        except Exception as exc:  # recorded in collector_runs, loop continues
            run.error = f"{type(exc).__name__}: {exc}"[:2000]
            self._info_refreshed_at = None  # station upserts may have been rolled back
            log.error("poll_failed", error=run.error)
        run.finished_at = self._clock()
        with self._sessions() as session:
            session.add(run)
            session.commit()
        log.info("poll", status=run.status, rows=run.rows_written, stations=run.stations_seen)
        return run

    def run_forever(self) -> None:
        """Poll on wall-clock multiples of the poll interval until interrupted."""
        interval = self._config.poll_interval_s
        while True:
            self.poll_once()
            now = time.time()
            self._sleep(interval - (now % interval))


def main() -> None:
    """Entry point for ``make collect``."""
    settings = get_env_settings()
    city = load_city_config(settings.city)
    config = load_project_config().collector
    client = httpx.Client(
        headers={"User-Agent": settings.user_agent}, timeout=config.request_timeout_s
    )
    collector = Collector(
        make_session_factory(make_engine()),
        client,
        city,
        config,
        settings.data_dir / "raw" / "gbfs",
    )
    collector.run_forever()


if __name__ == "__main__":
    main()
