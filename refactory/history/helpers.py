"""Helpers to record history from API / engine call sites."""

from __future__ import annotations

import time
from typing import Any


def git_context(container: Any) -> dict[str, Any]:
    """Best-effort branch / commit / repo name from GitService."""
    out: dict[str, Any] = {
        "branch": None,
        "commit": None,
        "repository_name": "",
    }
    try:
        git = container.git_service
        meta = git.get_repository_metadata()
        out["repository_name"] = getattr(meta, "name", "") or ""
        out["branch"] = getattr(meta, "current_branch", None) or git.get_current_branch()
        out["commit"] = getattr(meta, "head_sha", None) or git.get_head_sha()
    except Exception:  # noqa: BLE001
        pass
    return out


def record_history(
    container: Any,
    *,
    analysis_type: str,
    status: str = "completed",
    summary: str = "",
    duration_ms: float = 0.0,
    result_data: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    repository_id: str | None = None,
) -> None:
    """Record into analysis_history when repository is known."""
    service = getattr(container, "analysis_history_service", None)
    if service is None:
        return
    rid = repository_id
    if not rid:
        try:
            from pathlib import Path

            root = Path(container.git_service.get_root_path()).resolve()
            repo = container.query_service.get_repository_by_root(str(root))
            rid = repo["id"] if repo else None
        except Exception:  # noqa: BLE001
            rid = None
    if not rid:
        return
    ctx = git_context(container)
    service.record(
        repository_id=rid,
        analysis_type=analysis_type,
        repository_name=ctx["repository_name"],
        branch=ctx["branch"],
        commit=ctx["commit"],
        status=status,
        duration_ms=duration_ms,
        summary=summary,
        result_data=result_data,
        metadata=metadata,
    )


class timed:
    """Context manager measuring duration_ms."""

    def __init__(self) -> None:
        self.start = 0.0
        self.duration_ms = 0.0

    def __enter__(self) -> "timed":
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args: object) -> None:
        self.duration_ms = round((time.perf_counter() - self.start) * 1000.0, 3)
