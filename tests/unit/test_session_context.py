"""Tests for AI Session Context."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from refactory.core.logger import get_service_logger
from refactory.indexer.models import (
    IndexedFile,
    RepositoryIndex,
    RepositoryStatistics,
    RepositorySummary,
)
from refactory.intelligence.session import SessionContext, SessionState

_NOW = datetime.now(timezone.utc)


def _make_index() -> RepositoryIndex:
    return RepositoryIndex(
        summary=RepositorySummary(
            repository_name="test",
            repository_root="/tmp/test",
            total_indexed_files=0,
            timestamp=_NOW,
        ),
        statistics=RepositoryStatistics(),
        files=[],
        file_hashes={},
    )


class TestSessionState:
    def test_defaults(self):
        s = SessionState(repo_root=Path("/tmp/test"))
        assert s.index is None
        assert not s.graph_built
        assert not s.embeddings_ready
        assert s.command_count == 0


class TestSessionContext:
    def test_create_session(self):
        ctx = SessionContext(logger=get_service_logger("test"))
        session = ctx.get_or_create(Path("/tmp/repo"))
        assert session.repo_root == Path("/tmp/repo").resolve()
        assert session.command_count == 1

    def test_reuse_session(self):
        ctx = SessionContext(logger=get_service_logger("test"))
        s1 = ctx.get_or_create(Path("/tmp/repo"))
        s2 = ctx.get_or_create(Path("/tmp/repo"))
        assert s1 is s2
        assert s2.command_count == 2

    def test_different_repos_different_sessions(self):
        ctx = SessionContext(logger=get_service_logger("test"))
        s1 = ctx.get_or_create(Path("/tmp/repo1"))
        s2 = ctx.get_or_create(Path("/tmp/repo2"))
        assert s1 is not s2

    def test_update_index(self):
        ctx = SessionContext(logger=get_service_logger("test"))
        index = _make_index()
        ctx.update_index(Path("/tmp/repo"), index)
        session = ctx.get_or_create(Path("/tmp/repo"))
        assert session.index is index

    def test_mark_graph_built(self):
        ctx = SessionContext(logger=get_service_logger("test"))
        ctx.mark_graph_built(Path("/tmp/repo"))
        session = ctx.get_or_create(Path("/tmp/repo"))
        assert session.graph_built is True

    def test_mark_embeddings_ready(self):
        ctx = SessionContext(logger=get_service_logger("test"))
        ctx.mark_embeddings_ready(Path("/tmp/repo"))
        session = ctx.get_or_create(Path("/tmp/repo"))
        assert session.embeddings_ready is True

    def test_clear_specific(self):
        ctx = SessionContext(logger=get_service_logger("test"))
        ctx.get_or_create(Path("/tmp/repo1"))
        ctx.get_or_create(Path("/tmp/repo2"))
        ctx.clear(Path("/tmp/repo1"))
        assert len(ctx.active_sessions()) == 1

    def test_clear_all(self):
        ctx = SessionContext(logger=get_service_logger("test"))
        ctx.get_or_create(Path("/tmp/repo1"))
        ctx.get_or_create(Path("/tmp/repo2"))
        ctx.clear()
        assert len(ctx.active_sessions()) == 0

    def test_session_info(self):
        ctx = SessionContext(logger=get_service_logger("test"))
        ctx.get_or_create(Path("/tmp/repo"))
        info = ctx.session_info(Path("/tmp/repo"))
        assert info["commands_run"] >= 1
        assert info["index_cached"] is False
        assert info["graph_built"] is False

    def test_active_sessions(self):
        ctx = SessionContext(logger=get_service_logger("test"))
        ctx.get_or_create(Path("/tmp/a"))
        ctx.get_or_create(Path("/tmp/b"))
        assert len(ctx.active_sessions()) == 2

    def test_session_age(self):
        ctx = SessionContext(logger=get_service_logger("test"))
        ctx.get_or_create(Path("/tmp/repo"))
        info = ctx.session_info(Path("/tmp/repo"))
        assert info["session_age_seconds"] >= 0
