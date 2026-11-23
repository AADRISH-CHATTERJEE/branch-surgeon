"""POST /recommend, GET /recommendations, recommendation patch endpoints.

Controllers only orchestrate — all apply/rollback logic lives in services.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from refactory.api.deps import ContainerDep, RepoRootDep
from refactory.api.routes._activity import persist_repo_activity
from refactory.api.routes._helpers import not_found
from refactory.api.routes._post_transform import (
    pipeline_meta,
    run_post_transformation_pipeline,
)
from refactory.api.schemas import ApiResponse, RecommendRequest, fail, ok
from refactory.api.serialize import to_data
from refactory.recommendation.patch_models import (
    PatchApplyError,
    PatchConflictError,
    PatchGenerationError,
)

_ALLOWED_REC_STATUSES = frozenset(
    {"pending", "applied", "resolved", "ignored", "rolled_back"}
)

router = APIRouter(tags=["recommend"])


class ApplyPatchRequest(BaseModel):
    """Optional body for recommendation apply / patch apply."""

    patch_id: str | None = Field(None, description="Specific patch id; default = latest")
    dry_run: bool = False
    applied_by: str = "local"


def _apply_error_response(exc: PatchApplyError | PatchConflictError, repo_root: Path):
    if isinstance(exc, PatchConflictError):
        return JSONResponse(
            status_code=409,
            content=fail(
                exc.message,
                message="Patch conflict",
                meta={
                    "files": exc.files,
                    "repo_root": str(repo_root),
                    "failure_code": "conflict",
                },
            ).model_dump(),
        )
    return JSONResponse(
        status_code=exc.status_code,
        content=fail(
            exc.message,
            message="Unable to apply patch",
            meta={"repo_root": str(repo_root)},
        ).model_dump(),
    )


@router.post(
    "/recommend",
    response_model=ApiResponse,
    summary="Generate engineering recommendations",
    description="Delegates to RecommendationEngine.generate_recommendations.",
)
def create_recommendations(
    body: RecommendRequest,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse:
    root = Path(container.git_service.get_root_path()).resolve()
    report = container.recommendation_engine.generate_recommendations(
        root,
        category=body.category or None,
        priority=body.priority or None,
        top=body.top,
        reconcile=True,
    )
    container.recommendation_stats_service.invalidate(repo_root=root)
    summary = container.recommendation_stats_service.get_repository_summary(
        repo_root=root, force_refresh=True
    )
    return ok(
        to_data(report),
        message=f"Generated {report.total_recommendations} recommendations",
        meta={"repo_root": str(repo_root), "summary": to_data(summary)},
    )


@router.get(
    "/recommendations/stats",
    response_model=ApiResponse,
    summary="Repository recommendation summary (single source of truth)",
    description=(
        "Returns RecommendationStatsService.get_repository_summary — "
        "the only aggregation used by Branch Surgeon and the Recommendations page."
    ),
)
def recommendation_stats(
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse:
    root = Path(container.git_service.get_root_path()).resolve()
    branch = ""
    try:
        branch = container.git_service.get_repository_info().current_branch or ""
    except Exception:  # noqa: BLE001
        branch = ""
    # Live totals — same service Branch Surgeon uses (no duplicate counters).
    summary = container.recommendation_stats_service.get_repository_summary(
        repo_root=root,
        branch=branch,
        force_refresh=True,
    )
    return ok(
        to_data(summary),
        message="Recommendation summary",
        meta={
            "repo_root": str(repo_root),
            "source": summary.source,
            "version": summary.version,
        },
    )


@router.get(
    "/recommendations",
    response_model=ApiResponse,
    summary="List persisted recommendations",
    description="Reads normalized recommendation rows from RepositoryQueryService.",
)
def list_recommendations(
    container: ContainerDep,
    repo_root: RepoRootDep,
    limit: int = Query(100, ge=1, le=500),
    rec_status: str | None = Query(
        None, alias="status", description="Optional recommendation status filter"
    ),
) -> ApiResponse:
    root = Path(container.git_service.get_root_path()).resolve()
    repo = container.query_service.get_repository_by_root(str(root))
    if repo is None:
        return ok([], message="No repository record yet — run index or recommend first")
    rows = container.query_service.get_recommendations(
        repo["id"],
        status=rec_status,
        limit=limit,
    )
    # Totals always come from RecommendationStatsService — never len(rows).
    summary = container.recommendation_stats_service.get_repository_summary(
        repo_root=root,
        repository_id=repo["id"],
    )
    return ok(
        rows,
        meta={
            "repo_root": str(repo_root),
            "count": len(rows),
            "summary": to_data(summary),
        },
    )


class RecommendationUpdateRequest(BaseModel):
    """Lifecycle / metadata update for a recommendation."""

    status: str | None = Field(
        None, description="pending | applied | resolved | ignored | rolled_back"
    )
    priority: str | None = None
    resolution_notes: str | None = None
    verification_status: str | None = None
    updated_by: str = "local"


@router.patch(
    "/recommendations/{recommendation_id}",
    response_model=ApiResponse,
    summary="Update recommendation lifecycle / metadata",
    description=(
        "Update status (pending → applied → resolved, or ignored), priority, "
        "resolution notes, and verification. Refreshes RecommendationStatsService "
        "and Branch Surgeon; writes Activity + History."
    ),
)
def update_recommendation(
    recommendation_id: str,
    body: RecommendationUpdateRequest,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse | JSONResponse:
    root = Path(container.git_service.get_root_path()).resolve()
    repo = container.query_service.get_repository_by_root(str(root))
    if repo is None:
        return not_found("Not found", "Repository not found in persistence DB")
    rec = container.query_service.get_recommendation(recommendation_id)
    if rec is None or rec.get("repository_id") != repo["id"]:
        return not_found("Not found", f"Recommendation '{recommendation_id}' not found")

    if (
        not body.status
        and not body.priority
        and body.resolution_notes is None
        and body.verification_status is None
    ):
        return JSONResponse(
            status_code=422,
            content=fail(
                "Provide status, priority, resolution_notes, and/or verification_status",
                message="Invalid update",
            ).model_dump(),
        )

    status_norm = (body.status or "").strip().lower() or None
    if status_norm and status_norm not in _ALLOWED_REC_STATUSES:
        return JSONResponse(
            status_code=422,
            content=fail(
                f"Unsupported status '{body.status}'",
                message="Invalid recommendation status",
                meta={"allowed": sorted(_ALLOWED_REC_STATUSES)},
            ).model_dump(),
        )

    old_status = str(rec.get("status") or "pending")
    stats = container.recommendation_stats_service
    updated = rec
    updated_by = body.updated_by or "local"

    if status_norm:
        updated = (
            stats.set_status(
                recommendation_id,
                status_norm,
                updated_by=updated_by,
                resolution_notes=body.resolution_notes,
                verification_status=body.verification_status,
            )
            or updated
        )
    elif body.resolution_notes is not None or body.verification_status is not None:
        fields: dict = {"updated_by": updated_by}
        if body.resolution_notes is not None:
            fields["resolution_notes"] = body.resolution_notes
        if body.verification_status is not None:
            fields["verification_status"] = body.verification_status
        updated = (
            container.persistence_service.update_recommendation_fields(
                recommendation_id, **fields
            )
            or updated
        )
        stats.invalidate(repository_id=str(repo["id"]), repo_root=root)

    if body.priority:
        updated = stats.set_priority(recommendation_id, body.priority) or updated

    summary = stats.refresh(repo_root=root, repository_id=str(repo["id"]))

    branch_surgeon_refreshed = False
    try:
        container.branch_surgeon_service.compose_workspace()
        branch_surgeon_refreshed = True
    except Exception:  # noqa: BLE001
        branch_surgeon_refreshed = False

    label = {
        "resolved": "Recommendation Resolved",
        "ignored": "Recommendation Ignored",
        "applied": "Recommendation Applied",
        "rolled_back": "Recommendation Rolled Back",
        "pending": "Recommendation Reopened",
    }.get(status_norm or "", "Recommendation updated")

    lifecycle_payload = {
        "summary": label,
        "recommendation_id": recommendation_id,
        "old_status": old_status,
        "new_status": status_norm or updated.get("status"),
        "updated_by": updated_by,
        "user": updated_by,
        "title": updated.get("title"),
        "priority": updated.get("priority"),
        "timestamp": updated.get("updated_at")
        or updated.get("resolved_at")
        or updated.get("ignored_at"),
        "branch_surgeon_refreshed": branch_surgeon_refreshed,
    }

    if status_norm:
        persist_repo_activity(
            container,
            command="recommend",
            result_type="recommendation_lifecycle",
            summary=label,
            result_data=lifecycle_payload,
        )
        try:
            history = getattr(container, "analysis_history_service", None)
            if history is not None:
                history.record(
                    repository_id=str(repo["id"]),
                    analysis_type="recommendation",
                    command="recommend",
                    result_type="recommendation_lifecycle",
                    repository_name=str(repo.get("name") or ""),
                    status="completed",
                    summary=label,
                    created_by=updated_by,
                    created_by_user=updated_by,
                    result_data=lifecycle_payload,
                    metadata={
                        "recommendation_id": recommendation_id,
                        "old_status": old_status,
                        "new_status": status_norm,
                        "updated_by": updated_by,
                    },
                )
        except Exception:  # noqa: BLE001
            pass

    return ok(
        updated,
        message=label,
        meta={
            "repo_root": str(repo_root),
            "summary": to_data(summary),
            "branch_surgeon_refreshed": branch_surgeon_refreshed,
            "old_status": old_status,
            "new_status": status_norm or updated.get("status"),
        },
    )


@router.post(
    "/recommendations/{recommendation_id}/resolve",
    response_model=ApiResponse,
    summary="Mark recommendation resolved",
)
def resolve_recommendation(
    recommendation_id: str,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse | JSONResponse:
    return update_recommendation(
        recommendation_id,
        RecommendationUpdateRequest(status="resolved"),
        container,
        repo_root,
    )


@router.post(
    "/recommendations/{recommendation_id}/ignore",
    response_model=ApiResponse,
    summary="Mark recommendation ignored",
)
def ignore_recommendation(
    recommendation_id: str,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse | JSONResponse:
    return update_recommendation(
        recommendation_id,
        RecommendationUpdateRequest(status="ignored"),
        container,
        repo_root,
    )


@router.delete(
    "/recommendations/{recommendation_id}",
    response_model=ApiResponse,
    summary="Delete a recommendation",
)
def delete_recommendation(
    recommendation_id: str,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse | JSONResponse:
    root = Path(container.git_service.get_root_path()).resolve()
    repo = container.query_service.get_repository_by_root(str(root))
    if repo is None:
        return not_found("Not found", "Repository not found in persistence DB")
    rec = container.query_service.get_recommendation(recommendation_id)
    if rec is None or rec.get("repository_id") != repo["id"]:
        return not_found("Not found", f"Recommendation '{recommendation_id}' not found")
    deleted = container.recommendation_stats_service.delete_recommendation(
        recommendation_id
    )
    if not deleted:
        return not_found("Not found", f"Recommendation '{recommendation_id}' not found")
    summary = container.recommendation_stats_service.get_repository_summary(
        repo_root=root, repository_id=repo["id"], force_refresh=True
    )
    return ok(
        {"id": recommendation_id, "deleted": True},
        message="Recommendation deleted",
        meta={"repo_root": str(repo_root), "summary": to_data(summary)},
    )


@router.post(
    "/recommendations/{recommendation_id}/patch",
    response_model=ApiResponse,
    summary="Generate an AI patch for a persisted recommendation",
    description=(
        "Uses RecommendationPatchService: loads an existing recommendation, "
        "resolves file context, calls the LLM, builds a unified diff, and persists "
        "the patch for reuse. Does not invent recommendations."
    ),
)
def generate_recommendation_patch(
    recommendation_id: str,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse | JSONResponse:
    root = Path(container.git_service.get_root_path()).resolve()
    try:
        result = container.recommendation_patch_service.generate_for_recommendation(
            recommendation_id,
            root,
        )
    except PatchGenerationError as exc:
        return JSONResponse(
            status_code=422,
            content=fail(
                exc.message,
                message="Unable to generate patch",
            ).model_dump(),
        )
    return ok(
        to_data(result),
        message="Patch generated",
        meta={
            "repo_root": str(repo_root),
            "apply_available": True,
            "patch_id": result.id,
        },
    )


@router.get(
    "/recommendations/{recommendation_id}/patches",
    response_model=ApiResponse,
    summary="List persisted patches for a recommendation",
    description="Returns previously generated patches (reusable) for the recommendation.",
)
def list_recommendation_patches(
    recommendation_id: str,
    container: ContainerDep,
    repo_root: RepoRootDep,
    limit: int = Query(20, ge=1, le=100),
) -> ApiResponse | JSONResponse:
    root = Path(container.git_service.get_root_path()).resolve()
    try:
        # Ensure recommendation belongs to configured repo via apply service path
        repo = container.query_service.get_repository_by_root(str(root))
        if repo is None:
            return not_found("Not found", "Repository not found in persistence DB")
        rec = container.query_service.get_recommendation(recommendation_id)
        if rec is None or rec.get("repository_id") != repo["id"]:
            return not_found(
                "Not found", f"Recommendation '{recommendation_id}' not found"
            )
        rows = container.recommendation_service.list_patches(
            recommendation_id, limit=limit
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=fail(str(exc), message="Unable to list patches").model_dump(),
        )
    return ok(
        rows,
        meta={"repo_root": str(repo_root), "count": len(rows), "apply_available": True},
    )


@router.post(
    "/recommendations/{recommendation_id}/apply",
    response_model=ApiResponse,
    summary="Apply a patch for a recommendation",
    description=(
        "Orchestrates RecommendationService.apply_patch → PatchService → GitService. "
        "Loads the recommendation, resolves the patch, validates, applies to the "
        "working tree, records apply metadata, and marks the recommendation Applied."
    ),
)
def apply_recommendation(
    recommendation_id: str,
    container: ContainerDep,
    repo_root: RepoRootDep,
    body: ApplyPatchRequest | None = None,
) -> ApiResponse | JSONResponse:
    payload = body or ApplyPatchRequest()
    root = Path(container.git_service.get_root_path()).resolve()
    try:
        result = container.recommendation_service.apply_patch(
            recommendation_id,
            patch_id=payload.patch_id,
            dry_run=payload.dry_run,
            applied_by=payload.applied_by or "local",
            repo_root=root,
        )
    except (PatchConflictError, PatchApplyError) as exc:
        return _apply_error_response(exc, root)

    if result.status == "failed":
        return JSONResponse(
            status_code=422,
            content=fail(
                result.message,
                *(result.validation.errors or []),
                message="Unable to apply patch",
                meta={
                    "repo_root": str(repo_root),
                    "rolled_back": result.validation.rolled_back,
                    "failure_code": result.failure_code or "validation_failed",
                },
            ).model_dump(),
        )

    refresh = None
    if result.status == "applied" and not payload.dry_run:
        refresh = run_post_transformation_pipeline(
            container,
            root,
            trigger="patch-apply",
            patch_id=result.patch_id,
            transformation_id=recommendation_id,
        )

    return ok(
        to_data(result),
        message=result.message,
        meta={
            "repo_root": str(repo_root),
            "index_updated": result.index_updated,
            "graph_updated": result.graph_updated,
            "recommendation_status": getattr(result, "recommendation_status", None),
            **pipeline_meta(refresh),
        },
    )


@router.post(
    "/recommendations/{recommendation_id}/rollback",
    response_model=ApiResponse,
    summary="Roll back an applied patch for a recommendation",
)
def rollback_recommendation(
    recommendation_id: str,
    container: ContainerDep,
    repo_root: RepoRootDep,
    body: ApplyPatchRequest | None = None,
) -> ApiResponse | JSONResponse:
    payload = body or ApplyPatchRequest()
    root = Path(container.git_service.get_root_path()).resolve()
    try:
        result = container.recommendation_service.rollback_patch(
            recommendation_id,
            patch_id=payload.patch_id,
            applied_by=payload.applied_by or "local",
            repo_root=root,
        )
    except (PatchConflictError, PatchApplyError) as exc:
        return _apply_error_response(exc, root)

    refresh = None
    if result.status == "rolled_back":
        refresh = run_post_transformation_pipeline(
            container,
            root,
            trigger="patch-rollback",
            patch_id=result.patch_id,
            transformation_id=recommendation_id,
        )

    return ok(
        to_data(result),
        message=result.message,
        meta={
            "repo_root": str(repo_root),
            "recommendation_status": getattr(result, "recommendation_status", None),
            **pipeline_meta(refresh),
        },
    )


@router.post(
    "/patches/{patch_id}/apply",
    response_model=ApiResponse,
    summary="Apply a stored AI patch to the local repository",
    description=(
        "Thin orchestration over RecommendationService.apply_patch_by_id. "
        "Prefer POST /recommendations/{id}/apply for recommendation-scoped apply."
    ),
)
def apply_stored_patch(
    patch_id: str,
    container: ContainerDep,
    repo_root: RepoRootDep,
    body: ApplyPatchRequest | None = None,
) -> ApiResponse | JSONResponse:
    payload = body or ApplyPatchRequest()
    root = Path(container.git_service.get_root_path()).resolve()
    try:
        result = container.recommendation_service.apply_patch_by_id(
            patch_id,
            dry_run=payload.dry_run,
            applied_by=payload.applied_by or "local",
            repo_root=root,
        )
    except (PatchConflictError, PatchApplyError) as exc:
        return _apply_error_response(exc, root)

    if result.status == "failed":
        return JSONResponse(
            status_code=422,
            content=fail(
                result.message,
                *(result.validation.errors or []),
                message="Unable to apply patch",
                meta={
                    "repo_root": str(repo_root),
                    "rolled_back": result.validation.rolled_back,
                    "failure_code": result.failure_code or "validation_failed",
                },
            ).model_dump(),
        )

    refresh = None
    if result.status == "applied" and not payload.dry_run:
        refresh = run_post_transformation_pipeline(
            container,
            root,
            trigger="patch-apply",
            patch_id=patch_id,
        )

    return ok(
        to_data(result),
        message=result.message,
        meta={
            "repo_root": str(repo_root),
            "index_updated": result.index_updated,
            "graph_updated": result.graph_updated,
            "recommendation_status": getattr(result, "recommendation_status", None),
            **pipeline_meta(refresh),
        },
    )
