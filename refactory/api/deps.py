"""FastAPI dependencies — reuse ServiceContainer (no second DI container)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import Depends, Header, Query
from loguru import logger

from refactory.api.repo_root import choose_repo_root, validate_repository_root
from refactory.core.container import ServiceContainer, build_container

# Process-local cache: one container per resolved repo root.
_containers: dict[str, ServiceContainer] = {}


def resolve_repo_root(
    root: Annotated[
        str | None,
        Query(description="Repository root path override"),
    ] = None,
    x_repo_root: Annotated[
        str | None,
        Header(description="Repository root from UI (X-Repo-Root)"),
    ] = None,
) -> Path:
    """Resolve the target repository for this request.

    Priority:
    1. ``X-Repo-Root`` header (UI Settings)
    2. ``?root=`` query parameter
    3. ``REFACTORY_REPO_ROOT`` configured setting
    4. ``Path.cwd()`` last resort
    """
    candidate, source = choose_repo_root(x_repo_root=x_repo_root, query_root=root)
    logger.info(
        "Repository root source: {} | candidate: {} | cwd: {}",
        source,
        candidate,
        Path.cwd().resolve(),
    )
    return candidate


def get_container(
    repo_root: Annotated[Path, Depends(resolve_repo_root)],
) -> ServiceContainer:
    """Return a cached ServiceContainer for a validated repository root."""
    validated = validate_repository_root(repo_root)
    logger.info("Repository validated: {}", validated)

    key = str(validated)
    existing = _containers.get(key)
    if existing is not None:
        return existing

    logger.info("Building ServiceContainer for {}", key)
    container = build_container(repo_root=validated)
    _containers[key] = container
    git_root = Path(container.git_service.get_root_path()).resolve()
    logger.info("Git root detected: {}", git_root)
    return container


def clear_container_cache() -> None:
    """Test helper — drop cached containers."""
    _containers.clear()


ContainerDep = Annotated[ServiceContainer, Depends(get_container)]
RepoRootDep = Annotated[Path, Depends(resolve_repo_root)]
