"""Database engine and session factory."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from refactory_backend.core.config import Settings, get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _sqlite_connect_args(url: str) -> dict[str, object]:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def get_engine(settings: Settings | None = None) -> Engine:
    global _engine, _SessionLocal
    settings = settings or get_settings()
    if _engine is None:
        _engine = create_engine(
            settings.database_url,
            connect_args=_sqlite_connect_args(settings.database_url),
            future=True,
        )

        # Enable FK constraints for SQLite.
        if settings.database_url.startswith("sqlite"):

            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragma(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _engine


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    get_engine(settings)
    assert _SessionLocal is not None
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def reset_engine() -> None:
    """Test helper: dispose engine so a new DATABASE_URL can be applied."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
