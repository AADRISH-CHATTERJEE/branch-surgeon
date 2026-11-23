"""Global organization catalog database (shared across local repositories)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from refactory.db.database import DatabaseManager
from refactory.db.session import SessionFactory

if TYPE_CHECKING:
    from loguru import Logger

_catalog_manager: DatabaseManager | None = None
_catalog_sessions: SessionFactory | None = None


def get_catalog_session_factory(
    *, logger: "Logger | None" = None
) -> SessionFactory:
    """Return a process-wide SessionFactory for ``~/.refactory/db/``."""
    global _catalog_manager, _catalog_sessions
    if _catalog_sessions is not None:
        return _catalog_sessions
    _catalog_manager = DatabaseManager(repo_root=None, logger=logger)
    _catalog_manager.create_all()
    _catalog_sessions = SessionFactory(_catalog_manager.engine)
    return _catalog_sessions


def reset_catalog_for_tests() -> None:
    """Drop cached catalog handles (tests only)."""
    global _catalog_manager, _catalog_sessions
    if _catalog_manager is not None:
        _catalog_manager.engine.dispose()
    _catalog_manager = None
    _catalog_sessions = None
