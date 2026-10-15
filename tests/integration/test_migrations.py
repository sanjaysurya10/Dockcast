import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from dockcast.config import PROJECT_ROOT

pytestmark = pytest.mark.integration


def _alembic_config(url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _current_revision(url: str) -> str | None:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            exists = conn.execute(text("SELECT to_regclass('alembic_version')")).scalar()
            if exists is None:
                return None
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        engine.dispose()


def test_migrations_upgrade_and_downgrade(postgres_url: str) -> None:
    config = _alembic_config(postgres_url)
    command.upgrade(config, "head")
    assert _current_revision(postgres_url) == "0001"
    command.downgrade(config, "base")
    assert _current_revision(postgres_url) is None
