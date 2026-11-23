"""Best-effort Activity + History audit for organization admin mutations."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def resolve_audit_repository_id(
    container: Any,
    *,
    organization_id: str | None = None,
) -> str | None:
    """Resolve a repository_id required by analysis_runs / analysis_history."""
    # Prefer active git root when it is a valid repository.
    try:
        root = Path(container.git_service.get_root_path()).resolve()
        repo = container.query_service.get_repository_by_root(str(root))
        if repo and repo.get("id"):
            return str(repo["id"])
        created = _ensure_repository_row(container, root)
        if created:
            return created
    except Exception:  # noqa: BLE001
        pass

    # Fall back to any repository linked to the organization.
    if organization_id:
        try:
            links = container.organization_management_service.list_repositories(
                organization_id
            )
            for link in links or []:
                rid = link.get("repository_id")
                if rid:
                    return str(rid)
                root_path = (
                    link.get("repository_root_path")
                    or link.get("root_path")
                    or link.get("path")
                )
                if not root_path:
                    continue
                root = Path(str(root_path)).resolve()
                repo = container.query_service.get_repository_by_root(str(root))
                if repo and repo.get("id"):
                    return str(repo["id"])
                created = _ensure_repository_row(container, root)
                if created:
                    return created
        except Exception:  # noqa: BLE001
            pass

    return None


def _ensure_repository_row(container: Any, root: Path) -> str | None:
    persistence = getattr(container, "persistence_service", None)
    if persistence is None or not hasattr(persistence, "get_or_create_repository"):
        return None
    try:
        name = root.name
        try:
            meta = container.git_service.get_repository_metadata()
            name = getattr(meta, "name", None) or name
        except Exception:  # noqa: BLE001
            pass
        created = persistence.get_or_create_repository(name=name, root_path=str(root))
        return str(created["id"]) if created and created.get("id") else None
    except Exception:  # noqa: BLE001
        return None


def record_admin_audit(
    container: Any,
    *,
    command: str,
    organization_id: str | None,
    summary: str,
    result_data: dict[str, Any] | None = None,
    actor_email: str | None = None,
) -> None:
    """Persist one Activity row (mirrors into History). Never raises."""
    persistence = getattr(container, "persistence_service", None)
    if persistence is None:
        return
    rid = resolve_audit_repository_id(container, organization_id=organization_id)
    if not rid:
        return
    payload = dict(result_data or {})
    payload.setdefault("organization_id", organization_id)
    payload.setdefault("summary", summary)
    payload.setdefault("action", command)
    actor = actor_email or "local@refactory.dev"
    try:
        persistence.persist_analysis_run(
            repository_id=rid,
            command=command,
            result_type="organization_admin",
            status="completed",
            summary=summary,
            result_data=payload,
            metadata={
                "organization_id": organization_id,
                "created_by_user": actor,
                "kind": "organization_admin",
            },
            organization_id=organization_id,
            created_by_user=actor,
        )
    except Exception:  # noqa: BLE001
        pass
