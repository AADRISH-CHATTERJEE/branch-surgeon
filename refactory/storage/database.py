"""Database engine and session management."""

from __future__ import annotations

from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from refactory.storage.models import Base

_DEFAULT_DB_PATH = Path.home() / ".refactory" / "storage" / "refactory.db"


def get_repo_db_path(repo_root: Path | None = None) -> Path:
    """Return the per-repository database path under .refactory/storage/."""
    if repo_root:
        return repo_root / ".refactory" / "storage" / "refactory.db"
    return _DEFAULT_DB_PATH


class DatabaseEngine:
    """Manages SQLAlchemy engine and session factory."""

    def __init__(self, url: str | None = None, *, echo: bool = False, repo_root: Path | None = None) -> None:
        if url is None:
            db_path = get_repo_db_path(repo_root)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{db_path}"

        connect_args = {}
        if url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}

        self._engine = create_engine(
            url,
            echo=echo,
            connect_args=connect_args,
            pool_pre_ping=True,
        )
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)

    def create_tables(self) -> None:
        """Create all tables (for development/testing)."""
        Base.metadata.create_all(self._engine)

    def drop_tables(self) -> None:
        """Drop all tables (for testing)."""
        Base.metadata.drop_all(self._engine)

    def get_session(self) -> Session:
        """Get a new session."""
        return self._session_factory()

    def session_scope(self) -> Generator[Session, None, None]:
        """Context manager for session lifecycle."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @property
    def engine(self):
        return self._engine
