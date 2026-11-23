"""GET /repository* — repository metadata, status, health, explorer reads."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query

from refactory.api.deps import ContainerDep, RepoRootDep
from refactory.api.routes._helpers import api_error, not_found, resolve_repository_record
from refactory.api.schemas import ApiResponse, ok
from refactory.api.serialize import to_data
from refactory.git.service import GitService

router = APIRouter(prefix="/repository", tags=["repository"])


@router.get(
    "",
    response_model=ApiResponse,
    summary="Get local repository metadata",
    description="Returns Git repository identity for the configured repo root.",
)
def get_repository(container: ContainerDep, repo_root: RepoRootDep) -> ApiResponse:
    # Same Git snapshot as Branch Surgeon (get_repository_info), not the narrower
    # metadata DTO — avoids losing HEAD when metadata fields drift.
    info = container.git_service.get_repository_info()
    wt = info.working_tree
    dirty_files = sorted(
        {
            *[item.path for item in wt.modified_files],
            *[item.path for item in wt.deleted_files],
            *[item.path for item in wt.renamed_files],
            *[item.path for item in wt.staged_files],
            *wt.untracked_files,
        }
    )
    working_tree_state = "dirty" if info.is_dirty else "clean"
    payload = {
        # Canonical fields (existing clients)
        "name": info.name,
        "root_path": info.root_path,
        "current_branch": info.current_branch,
        "default_branch": info.default_branch,
        "remote_url": info.remote_url,
        "head_sha": info.head_sha,
        "is_dirty": info.is_dirty,
        "is_detached": info.is_detached,
        "owner": info.owner,
        "full_name": info.full_name,
        "working_tree": working_tree_state,
        "dirty_files": dirty_files,
        "ahead": wt.ahead,
        "behind": wt.behind,
        # Aliases for clearer local-repo UX
        "root": info.root_path,
        "remote": info.remote_url,
        "branch": info.current_branch,
        "head": info.head_sha,
    }
    return ok(payload, meta={"repo_root": str(repo_root)})


@router.get(
    "/status",
    response_model=ApiResponse,
    summary="Get repository + service wiring status",
    description="Lightweight status snapshot (git + settings + index staleness).",
)
def get_repository_status(container: ContainerDep, repo_root: RepoRootDep) -> ApiResponse:
    settings = container.settings
    info = container.git_service.get_repository_info()
    root = Path(info.root_path)
    try:
        staleness = container.indexer_service.assess_staleness(root)
    except Exception as exc:  # noqa: BLE001
        staleness = {"error": str(exc)}

    return ok(
        {
            "name": info.name,
            "root": info.root_path,
            "root_path": info.root_path,
            "branch": info.current_branch,
            "current_branch": info.current_branch,
            "default_branch": info.default_branch,
            "head": info.head_sha,
            "head_sha": info.head_sha,
            "remote": info.remote_url,
            "remote_url": info.remote_url,
            "working_tree": "dirty" if info.is_dirty else "clean",
            "is_dirty": info.is_dirty,
            "ahead": info.working_tree.ahead,
            "behind": info.working_tree.behind,
            "ai_provider": settings.ai.provider,
            "ai_model": getattr(container.ai_gateway, "model", None),
            "cache_enabled": settings.cache.enabled,
            "backend_url": settings.backend.url or None,
            "index_staleness": to_data(staleness),
            "review_engine": type(container.review_engine).__name__,
        },
        meta={"repo_root": str(repo_root)},
    )


@router.get(
    "/health",
    response_model=ApiResponse,
    summary="Calculate repository health scores",
    description="Delegates to RecommendationEngine.calculate_health (no business logic in API).",
)
def get_repository_health(container: ContainerDep, repo_root: RepoRootDep) -> ApiResponse:
    from refactory.history.helpers import record_history, timed

    root = Path(container.git_service.get_root_path()).resolve()
    with timed() as t:
        report = container.recommendation_engine.calculate_health(root)
    data = to_data(report)
    scores = data.get("scores") if isinstance(data, dict) else None
    overall = (scores or {}).get("overall") if isinstance(scores, dict) else None
    # Keep recommendation truth + Branch Surgeon in sync after health scan.
    container.recommendation_stats_service.invalidate(repo_root=root)
    record_history(
        container,
        analysis_type="repository_health",
        summary=f"Health score {overall}" if overall is not None else "Health snapshot",
        duration_ms=t.duration_ms,
        result_data=data if isinstance(data, dict) else {"report": data},
    )
    return ok(data, meta={"repo_root": str(repo_root)})


def _resolve_file_id(container, repository_id: str, *, file_id: str | None, path: str | None):
    if file_id:
        return file_id
    if path:
        file_row = container.query_service.get_file(repository_id, path)
        if file_row is None:
            return None
        return file_row["id"]
    return None


@router.get(
    "/file",
    response_model=ApiResponse,
    summary="Read working-tree file content for preview",
    description=(
        "Safely resolves a repo-relative path, rejects traversal, and returns "
        "UTF-8 text content for the Monaco file viewer. Binary / oversized files "
        "are rejected with 415 / 413."
    ),
    responses={
        404: {"model": ApiResponse},
        413: {"model": ApiResponse},
        415: {"model": ApiResponse},
    },
)
def get_file_content(
    container: ContainerDep,
    repo_root: RepoRootDep,
    path: str = Query(..., min_length=1, description="Repository-relative file path"),
):
    repo = resolve_repository_record(container)
    # Repo row is optional for disk preview — still require a valid git root via deps.
    preview = container.git_service.preview_working_file(path)

    if preview.status == "unsafe":
        return api_error(400, "Invalid path", preview.message or "Path traversal rejected")
    if preview.status == "not_found":
        return not_found("File not found", preview.message or f"File '{path}' not found")
    if preview.status == "binary":
        return api_error(
            415,
            "Binary file cannot be previewed",
            preview.message or "Unsupported media type",
        )
    if preview.status == "too_large":
        return api_error(
            413,
            "File too large to preview",
            preview.message or "File exceeds preview size limit",
        )
    if preview.status != "ok" or preview.content is None:
        return api_error(
            500,
            "Unable to load file",
            preview.message or "Failed to read file",
        )

    indexed = None
    if repo is not None:
        indexed = container.query_service.get_file(repo["id"], preview.path)
        if indexed is None:
            # Try the caller path in case index uses a different separator form.
            indexed = container.query_service.get_file(repo["id"], path)

    language = (
        (indexed or {}).get("language")
        or preview.language
        or GitService.language_for_path(preview.path)
    )
    if not language or language == "unknown":
        language = GitService.language_for_path(preview.path)

    sha = (indexed or {}).get("sha256") or preview.sha
    size = (indexed or {}).get("size")
    if size is None:
        size = preview.size

    return ok(
        {
            "path": preview.path,
            "language": language,
            "size": size,
            "sha": sha,
            "sha256": sha,
            "content": preview.content,
            "truncated": preview.truncated,
            "id": (indexed or {}).get("id"),
        },
        meta={"repo_root": str(repo_root)},
    )


@router.get(
    "/files",
    response_model=ApiResponse,
    summary="List indexed files for the repository",
    description="Thin read over RepositoryQueryService.get_files.",
    responses={404: {"model": ApiResponse}},
)
def list_files(
    container: ContainerDep,
    repo_root: RepoRootDep,
    language: str | None = Query(None),
    limit: int = Query(1000, ge=1, le=10000),
):
    repo = resolve_repository_record(container)
    if repo is None:
        return not_found("Not found", "Repository not found in persistence DB")
    files = container.query_service.get_files(
        repo["id"], language=language, limit=limit
    )
    return ok(files, meta={"repo_root": str(repo_root), "count": len(files)})


@router.get(
    "/symbols",
    response_model=ApiResponse,
    summary="List symbols (optionally for one file)",
    description=(
        "Thin read over RepositoryQueryService.get_symbols. "
        "Pass file_id or path to scope; otherwise aggregates across indexed files."
    ),
    responses={404: {"model": ApiResponse}},
)
def list_symbols(
    container: ContainerDep,
    repo_root: RepoRootDep,
    file_id: str | None = Query(None),
    path: str | None = Query(None),
    limit: int = Query(5000, ge=1, le=50000),
):
    repo = resolve_repository_record(container)
    if repo is None:
        return not_found("Not found", "Repository not found in persistence DB")

    scoped_id = _resolve_file_id(container, repo["id"], file_id=file_id, path=path)
    if file_id or path:
        if scoped_id is None:
            return not_found("Not found", "File not found")
        symbols = container.query_service.get_symbols(scoped_id)
        return ok(symbols[:limit], meta={"repo_root": str(repo_root), "count": len(symbols[:limit])})

    symbols: list = []
    for file_row in container.query_service.get_files(repo["id"], limit=10000):
        symbols.extend(container.query_service.get_symbols(file_row["id"]))
        if len(symbols) >= limit:
            break
    return ok(symbols[:limit], meta={"repo_root": str(repo_root), "count": len(symbols[:limit])})


@router.get(
    "/imports",
    response_model=ApiResponse,
    summary="List imports (optionally for one file)",
    description=(
        "Thin read over RepositoryQueryService.get_imports. "
        "Pass file_id or path to scope; otherwise aggregates across indexed files."
    ),
    responses={404: {"model": ApiResponse}},
)
def list_imports(
    container: ContainerDep,
    repo_root: RepoRootDep,
    file_id: str | None = Query(None),
    path: str | None = Query(None),
    limit: int = Query(5000, ge=1, le=50000),
):
    repo = resolve_repository_record(container)
    if repo is None:
        return not_found("Not found", "Repository not found in persistence DB")

    scoped_id = _resolve_file_id(container, repo["id"], file_id=file_id, path=path)
    if file_id or path:
        if scoped_id is None:
            return not_found("Not found", "File not found")
        imports = container.query_service.get_imports(scoped_id)
        return ok(imports[:limit], meta={"repo_root": str(repo_root), "count": len(imports[:limit])})

    imports: list = []
    for file_row in container.query_service.get_files(repo["id"], limit=10000):
        imports.extend(container.query_service.get_imports(file_row["id"]))
        if len(imports) >= limit:
            break
    return ok(imports[:limit], meta={"repo_root": str(repo_root), "count": len(imports[:limit])})
