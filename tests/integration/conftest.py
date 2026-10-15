from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Start a throwaway Postgres 16 container and yield a psycopg SQLAlchemy URL."""
    testcontainers_pg = pytest.importorskip("testcontainers.postgres")
    try:
        container = testcontainers_pg.PostgresContainer("postgres:16", driver="psycopg")
        container.start()
    except Exception as exc:  # Docker not available
        pytest.skip(f"Docker unavailable: {exc}")
    try:
        yield container.get_connection_url()
    finally:
        container.stop()
