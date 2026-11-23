"""Persist engine runs into Activity (analysis_runs) + History."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from refactory.core.container import ServiceContainer
from refactory.history.helpers import git_context


def persist_repo_activity(
    container: ServiceContainer,
    *,
    command: str,
    result_type: str,
    summary: str,
    result_data: dict[str, Any] | None = None,
    status: str = "completed",
    duration_ms: float = 0.0,
) -> None:
    """Best-effort Activity write (also mirrors into History via PersistenceService)."""
    try:
        root = Path(container.git_service.get_root_path()).resolve()
        repo = container.query_service.get_repository_by_root(str(root))
        if repo is None:
            meta = container.git_service.get_repository_metadata()
            repo = container.persistence_service.get_or_create_repository(
                name=meta.name,
                root_path=str(root),
            )
        ctx = git_context(container)
        container.persistence_service.persist_analysis_run(
            repository_id=repo["id"],
            command=command,
            result_type=result_type,
            status=status,
            git_commit=ctx.get("commit"),
            branch=ctx.get("branch"),
            duration_ms=duration_ms,
            result_data=result_data,
            summary=summary,
        )
    except Exception:  # noqa: BLE001
        pass
