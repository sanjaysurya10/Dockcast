from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text

from dockcast.config import PROJECT_ROOT


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


def alembic_config(url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture
def db_engine(postgres_url: str) -> Iterator[Engine]:
    """Engine on a freshly migrated schema; all tables emptied after the test."""
    command.upgrade(alembic_config(postgres_url), "head")
    engine = create_engine(postgres_url)
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            tables = conn.execute(
                text(
                    "SELECT string_agg(quote_ident(tablename), ', ') FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                )
            ).scalar_one()
            conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        engine.dispose()
