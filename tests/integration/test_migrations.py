import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration

PRD_TABLES = {
    "cities",
    "stations",
    "station_id_map",
    "station_status_raw",
    "station_status_15m",
    "weather_hourly",
    "calendar_days",
    "model_versions",
    "forecasts",
    "risk_scores",
    "backtest_results",
    "collector_runs",
    "data_quality_files",
    "data_gaps",
    "station_capacity",
}


def _current_revision(url: str) -> str | None:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            if conn.execute(text("SELECT to_regclass('alembic_version')")).scalar() is None:
                return None
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        engine.dispose()


def test_migrations_upgrade_and_downgrade(postgres_url: str) -> None:
    config = alembic_config(postgres_url)
    command.upgrade(config, "head")
    assert _current_revision(postgres_url) == "0006"
    engine = create_engine(postgres_url)
    assert set(inspect(engine).get_table_names()) >= PRD_TABLES
    engine.dispose()
    command.downgrade(config, "base")
    assert _current_revision(postgres_url) is None
