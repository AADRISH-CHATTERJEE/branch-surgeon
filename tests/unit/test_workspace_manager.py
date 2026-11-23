"""Tests for WorkspaceManager."""

from __future__ import annotations

from pathlib import Path

import pytest

from refactory.workspace.manager import Workspace, WorkspaceConfig, WorkspaceManager


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".refactory"
    d.mkdir()
    return d


@pytest.fixture
def manager(config_dir: Path) -> WorkspaceManager:
    from loguru import logger
    return WorkspaceManager(logger=logger, config_dir=config_dir)


class TestWorkspaceManager:
    def test_add_workspace(self, manager: WorkspaceManager):
        ws = manager.add("test-project", "/tmp/repo")
        assert ws.name == "test-project"
        assert ws.active is True

    def test_add_duplicate_raises(self, manager: WorkspaceManager):
        manager.add("proj", "/tmp/a")
        with pytest.raises(ValueError, match="already exists"):
            manager.add("proj", "/tmp/b")

    def test_remove_workspace(self, manager: WorkspaceManager):
        manager.add("proj", "/tmp/a")
        manager.remove("proj")
        assert manager.list_workspaces() == []

    def test_remove_nonexistent_raises(self, manager: WorkspaceManager):
        with pytest.raises(ValueError, match="not found"):
            manager.remove("nope")

    def test_use_workspace(self, manager: WorkspaceManager):
        manager.add("a", "/tmp/a")
        manager.add("b", "/tmp/b")
        ws = manager.use("b")
        assert ws.active is True
        assert manager.get_active().name == "b"

    def test_use_nonexistent_raises(self, manager: WorkspaceManager):
        with pytest.raises(ValueError, match="not found"):
            manager.use("nope")

    def test_list_workspaces(self, manager: WorkspaceManager):
        manager.add("a", "/tmp/a")
        manager.add("b", "/tmp/b")
        workspaces = manager.list_workspaces()
        assert len(workspaces) == 2
        names = {ws.name for ws in workspaces}
        assert names == {"a", "b"}

    def test_first_workspace_is_active(self, manager: WorkspaceManager):
        manager.add("first", "/tmp/first")
        ws = manager.get_active()
        assert ws is not None
        assert ws.name == "first"

    def test_get_by_name(self, manager: WorkspaceManager):
        manager.add("x", "/tmp/x")
        ws = manager.get("x")
        assert ws is not None
        assert ws.name == "x"

    def test_get_missing_returns_none(self, manager: WorkspaceManager):
        assert manager.get("missing") is None

    def test_persistence(self, config_dir: Path):
        from loguru import logger
        m1 = WorkspaceManager(logger=logger, config_dir=config_dir)
        m1.add("proj", "/tmp/proj")
        del m1

        m2 = WorkspaceManager(logger=logger, config_dir=config_dir)
        workspaces = m2.list_workspaces()
        assert len(workspaces) == 1
        assert workspaces[0].name == "proj"

    def test_remove_active_switches(self, manager: WorkspaceManager):
        manager.add("a", "/tmp/a")
        manager.add("b", "/tmp/b")
        manager.use("a")
        manager.remove("a")
        active = manager.get_active()
        assert active is not None
        assert active.name == "b"

    def test_path_resolved(self, manager: WorkspaceManager, tmp_path: Path):
        sub = tmp_path / "repo"
        sub.mkdir()
        ws = manager.add("local", str(sub))
        assert Path(ws.path).is_absolute()

    def test_workspace_model_defaults(self):
        ws = Workspace(name="test", path="/tmp/test")
        assert ws.branch == ""
        assert ws.active is False
        assert ws.cached_graph is False

    def test_config_model_defaults(self):
        cfg = WorkspaceConfig()
        assert cfg.workspaces == []
        assert cfg.active_workspace is None
