"""AI Session Context — allows multiple commands to share repository state.

Avoids rebuilding graph, index, and embeddings for each command invocation.
Thread-safe singleton scoped to a repository root.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from refactory.indexer.models import RepositoryIndex

if TYPE_CHECKING:
    from loguru import Logger
    from refactory.graph.models import RepositoryGraph


@dataclass
class SessionState:
    """Cached state for the current AI session."""

    repo_root: Path
    index: RepositoryIndex | None = None
    graph_built: bool = False
    embeddings_ready: bool = False
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    command_count: int = 0


class SessionContext:
    """Per-repository session that persists across CLI commands."""

    def __init__(self, logger: "Logger") -> None:
        self._logger = logger
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.Lock()

    def get_or_create(self, repo_root: Path) -> SessionState:
        """Get existing session or create a new one for the given root."""
        key = str(repo_root.resolve())
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                session = SessionState(repo_root=repo_root.resolve())
                self._sessions[key] = session
                self._logger.debug("Created new session for {}", key)
            session.last_accessed = time.time()
            session.command_count += 1
            return session

    def update_index(self, repo_root: Path, index: RepositoryIndex) -> None:
        """Cache an index in the session."""
        session = self.get_or_create(repo_root)
        with self._lock:
            session.index = index

    def mark_graph_built(self, repo_root: Path) -> None:
        """Mark the graph as built for the session."""
        session = self.get_or_create(repo_root)
        with self._lock:
            session.graph_built = True

    def mark_embeddings_ready(self, repo_root: Path) -> None:
        """Mark embeddings as loaded for the session."""
        session = self.get_or_create(repo_root)
        with self._lock:
            session.embeddings_ready = True

    def clear(self, repo_root: Path | None = None) -> None:
        """Clear session state."""
        with self._lock:
            if repo_root is None:
                self._sessions.clear()
            else:
                self._sessions.pop(str(repo_root.resolve()), None)

    def active_sessions(self) -> list[SessionState]:
        """Return all active sessions."""
        with self._lock:
            return list(self._sessions.values())

    def session_info(self, repo_root: Path) -> dict[str, object]:
        """Return session metadata."""
        session = self.get_or_create(repo_root)
        elapsed = time.time() - session.created_at
        return {
            "repo_root": str(session.repo_root),
            "index_cached": session.index is not None,
            "graph_built": session.graph_built,
            "embeddings_ready": session.embeddings_ready,
            "commands_run": session.command_count,
            "session_age_seconds": round(elapsed, 1),
        }
