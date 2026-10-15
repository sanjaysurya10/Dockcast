"""SQLAlchemy engine and session factory."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from dockcast.config import get_env_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models; Alembic autogenerate targets its metadata."""


def make_engine(database_url: str | None = None) -> Engine:
    """Create an engine for the given URL, defaulting to `DATABASE_URL`.

    Args:
        database_url: SQLAlchemy URL; falls back to the configured one.

    Returns:
        A new SQLAlchemy engine.
    """
    return create_engine(database_url or get_env_settings().database_url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory bound to an engine.

    Args:
        engine: Engine to bind sessions to.

    Returns:
        A configured `sessionmaker`.
    """
    return sessionmaker(bind=engine, expire_on_commit=False)
