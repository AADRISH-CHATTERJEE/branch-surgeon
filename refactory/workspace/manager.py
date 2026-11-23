"""Workspace management — manage multiple repository workspaces.

Stores workspace configuration in ~/.refactory/workspaces.json.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from loguru import Logger

WORKSPACES_FILE = "workspaces.json"
REFACTORY_HOME = Path.home() / ".refactory"


class Workspace(BaseModel):
    """A single workspace configuration."""

    name: str
    path: str
    branch: str = ""
    active: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_used: datetime | None = None
    cached_graph: bool = False
    cached_index: bool = False


class WorkspaceConfig(BaseModel):
    """Collection of workspace configurations."""

    workspaces: list[Workspace] = Field(default_factory=list)
    active_workspace: str | None = None


class WorkspaceManager:
    """Manage multiple repository workspaces."""

    def __init__(self, logger: "Logger", config_dir: Path | None = None) -> None:
        self._logger = logger
        self._dir = config_dir or REFACTORY_HOME
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._config = self._load()

    @property
    def config(self) -> WorkspaceConfig:
        return self._config

    def add(self, name: str, path: str) -> Workspace:
        """Add a new workspace."""
        with self._lock:
            for ws in self._config.workspaces:
                if ws.name == name:
                    raise ValueError(f"Workspace '{name}' already exists")

            resolved = str(Path(path).resolve())
            workspace = Workspace(name=name, path=resolved)
            self._config.workspaces.append(workspace)

            if len(self._config.workspaces) == 1:
                workspace.active = True
                self._config.active_workspace = name

            self._persist()
            self._logger.info("Workspace added: {} -> {}", name, resolved)
            return workspace

    def remove(self, name: str) -> None:
        """Remove a workspace by name."""
        with self._lock:
            before = len(self._config.workspaces)
            self._config.workspaces = [
                ws for ws in self._config.workspaces if ws.name != name
            ]
            if len(self._config.workspaces) == before:
                raise ValueError(f"Workspace '{name}' not found")

            if self._config.active_workspace == name:
                self._config.active_workspace = (
                    self._config.workspaces[0].name
                    if self._config.workspaces else None
                )
                for ws in self._config.workspaces:
                    ws.active = ws.name == self._config.active_workspace

            self._persist()
            self._logger.info("Workspace removed: {}", name)

    def use(self, name: str) -> Workspace:
        """Set a workspace as active."""
        with self._lock:
            target: Workspace | None = None
            for ws in self._config.workspaces:
                if ws.name == name:
                    ws.active = True
                    ws.last_used = datetime.now(timezone.utc)
                    target = ws
                    self._config.active_workspace = name
                else:
                    ws.active = False
            if target is None:
                raise ValueError(f"Workspace '{name}' not found")
            self._persist()
            self._logger.info("Workspace activated: {}", name)
            return target

    def list_workspaces(self) -> list[Workspace]:
        """List all workspaces."""
        return list(self._config.workspaces)

    def get_active(self) -> Workspace | None:
        """Get the currently active workspace."""
        for ws in self._config.workspaces:
            if ws.active:
                return ws
        return None

    def get(self, name: str) -> Workspace | None:
        """Get a workspace by name."""
        for ws in self._config.workspaces:
            if ws.name == name:
                return ws
        return None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> WorkspaceConfig:
        path = self._dir / WORKSPACES_FILE
        if not path.is_file():
            return WorkspaceConfig()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return WorkspaceConfig.model_validate(data)
        except (json.JSONDecodeError, OSError, ValueError):
            return WorkspaceConfig()

    def _persist(self) -> None:
        path = self._dir / WORKSPACES_FILE
        try:
            path.write_text(
                self._config.model_dump_json(indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            self._logger.warning("Failed to persist workspaces: {}", exc)
