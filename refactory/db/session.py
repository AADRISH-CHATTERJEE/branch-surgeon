"""Session factory management."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


class SessionFactory:
    """Thin wrapper around sessionmaker for DI friendliness."""

    def __init__(self, engine: Engine) -> None:
        self._factory = sessionmaker(
            bind=engine,
            expire_on_commit=False,
            autoflush=True,
        )

    def __call__(self) -> Session:
        """Create a new session."""
        return self._factory()

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """Context manager that commits on success, rolls back on error."""
        session = self._factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def get_session_factory(engine: Engine) -> SessionFactory:
    """Create a SessionFactory from an engine."""
    return SessionFactory(engine)
