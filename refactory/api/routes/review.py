"""POST /review, GET /reviews, GET /review/{id}, PATCH suggestion status."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from refactory.api.deps import ContainerDep, RepoRootDep
from refactory.api.routes._activity import persist_repo_activity
from refactory.api.routes._helpers import not_found, resolve_repository_record
from refactory.api.schemas import ApiResponse, ReviewRequest, fail, ok
from refactory.api.serialize import to_data
from refactory.review.suggestion_status import ALLOWED_STATUSES

router = APIRouter(tags=["review"])


class SuggestionStatusUpdateRequest(BaseModel):
    status: str = Field(..., description="pending | resolved | ignored")
    updated_by: str = "local"


@router.post(
    "/review",
    response_model=ApiResponse,
    summary="Run an AI-assisted review",
    description=(
        "Delegates to ReviewEngine.review. Company rules gate runs first; "
        "BLOCK outcomes skip AI and return blocking findings."
    ),
)
def create_review(
    body: ReviewRequest,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse:
    result = container.review_engine.review(
        body.pr_number,
        base_branch=body.base_branch,
        head_ref=body.head_ref,
    )
    return ok(
        to_data(result),
        message=(
            "No changes to review"
            if (result.metadata or {}).get("empty_pr")
            else f"Review complete for #{body.pr_number}"
        ),
        meta={
            "repo_root": str(repo_root),
            "pr_number": body.pr_number,
            "scope": "pr",
            "changed_file_count": (result.metadata or {}).get("changed_file_count"),
        },
    )


@router.get(
    "/reviews",
    response_model=ApiResponse,
    summary="List persisted reviews for the repository",
    description="Thin read over RepositoryQueryService.get_reviews.",
    responses={404: {"model": ApiResponse}},
)
def list_reviews(
    container: ContainerDep,
    repo_root: RepoRootDep,
    limit: int = Query(50, ge=1, le=500),
):
    repo = resolve_repository_record(container)
    if repo is None:
        return not_found("Not found", "Repository not found in persistence DB")
    reviews = container.query_service.get_reviews(repo["id"], limit=limit)
    return ok(reviews, meta={"repo_root": str(repo_root), "count": len(reviews)})


@router.get(
    "/review/{review_id}",
    response_model=ApiResponse,
    summary="Fetch a persisted review by id",
    description=(
        "Reads review plus suggestions from RepositoryQueryService. "
        "Also accepts PR number as a convenience lookup."
    ),
    responses={404: {"model": ApiResponse}},
)
def get_review(
    review_id: str,
    container: ContainerDep,
    repo_root: RepoRootDep,
):
    repo = resolve_repository_record(container)
    if repo is None:
        return not_found("Not found", "Repository not found in persistence DB")

    match = container.query_service.get_review(review_id)
    if match is None:
        reviews = container.query_service.get_reviews(repo["id"], limit=100)
        match = next(
            (r for r in reviews if str(r.get("pr_number")) == review_id),
            None,
        )
    elif match.get("repository_id") != repo["id"]:
        match = None

    if match is None:
        return not_found("Not found", f"Review '{review_id}' not found")

    suggestions = container.query_service.get_review_suggestions(match["id"])
    # Recompute stats from the same suggestion payload detail returns
    # so History metrics and Detail metrics never diverge.
    stats = container.query_service.suggestion_stats(suggestions)
    return ok(
        {**match, **stats, "suggestions": suggestions},
        meta={"repo_root": str(repo_root)},
    )


@router.patch(
    "/reviews/{review_id}/suggestions/{suggestion_id}",
    response_model=ApiResponse,
    summary="Update review suggestion status",
    description=(
        "Sets suggestion status to pending, resolved, or ignored. "
        "Synchronizes matching recommendations and refreshes stats."
    ),
    responses={404: {"model": ApiResponse}, 422: {"model": ApiResponse}},
)
def update_review_suggestion_status(
    review_id: str,
    suggestion_id: str,
    body: SuggestionStatusUpdateRequest,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse | JSONResponse:
    repo = resolve_repository_record(container)
    if repo is None:
        return not_found("Not found", "Repository not found in persistence DB")

    status = (body.status or "").strip().lower()
    if status not in ALLOWED_STATUSES:
        return JSONResponse(
            status_code=422,
            content=fail(
                f"Unsupported status '{body.status}'",
                message="Invalid suggestion status",
                meta={"allowed": sorted(ALLOWED_STATUSES)},
            ).model_dump(),
        )

    try:
        outcome = container.review_suggestion_status_service.update_status(
            review_id=review_id,
            suggestion_id=suggestion_id,
            status=status,
            repository_id=str(repo["id"]),
            updated_by=body.updated_by or "local",
        )
    except LookupError as exc:
        return not_found("Not found", str(exc))
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content=fail(str(exc), message="Invalid suggestion status").model_dump(),
        )

    suggestion = outcome["suggestion"]
    canonical_review_id = str(outcome.get("review_id") or review_id)
    old_status = str(outcome.get("old_status") or "pending")
    updated_by = body.updated_by or "local"
    root = Path(container.git_service.get_root_path()).resolve()

    # Full repository statistics refresh — no stale cache.
    summary = container.recommendation_stats_service.refresh(
        repo_root=root,
        repository_id=str(repo["id"]),
    )

    # Refresh Branch Surgeon cached workspace (totals / critical / pending / health).
    branch_surgeon_refreshed = False
    try:
        container.branch_surgeon_service.compose_workspace()
        branch_surgeon_refreshed = True
    except Exception:  # noqa: BLE001
        branch_surgeon_refreshed = False

    label = {
        "resolved": "Resolved review suggestion",
        "ignored": "Ignored review suggestion",
        "pending": "Reopened review suggestion",
    }.get(status, "Updated review suggestion")

    lifecycle_payload = {
        "summary": label,
        "review_id": canonical_review_id,
        "suggestion_id": suggestion_id,
        "file": suggestion.get("file"),
        "rule": suggestion.get("category") or suggestion.get("title"),
        "title": suggestion.get("title"),
        "status": status,
        "old_status": old_status,
        "new_status": status,
        "updated_by": updated_by,
        "user": updated_by,
        "synced_recommendation_ids": outcome.get("synced_recommendation_ids") or [],
        "timestamp": suggestion.get("updated_at")
        or suggestion.get("resolved_at")
        or suggestion.get("ignored_at"),
        "branch_surgeon_refreshed": branch_surgeon_refreshed,
        "resolved_at": suggestion.get("resolved_at"),
        "ignored_at": suggestion.get("ignored_at"),
        "updated_at": suggestion.get("updated_at"),
    }

    persist_repo_activity(
        container,
        command="review-suggestion",
        result_type="review_suggestion",
        summary=label,
        result_data=lifecycle_payload,
    )

    # Explicit History write with lifecycle fields (Activity mirror may also write).
    try:
        history = getattr(container, "analysis_history_service", None)
        if history is not None:
            history.record(
                repository_id=str(repo["id"]),
                analysis_type="review",
                command="review-suggestion",
                result_type="review_suggestion",
                repository_name=str(repo.get("name") or ""),
                status="completed",
                summary=label,
                created_by=updated_by,
                created_by_user=updated_by,
                result_data=lifecycle_payload,
                metadata={
                    "review_id": canonical_review_id,
                    "suggestion_id": suggestion_id,
                    "old_status": old_status,
                    "new_status": status,
                    "updated_by": updated_by,
                },
            )
    except Exception:  # noqa: BLE001
        pass

    return ok(
        suggestion,
        message=label,
        meta={
            "repo_root": str(repo_root),
            "review_id": canonical_review_id,
            "synced_recommendation_ids": outcome.get("synced_recommendation_ids") or [],
            "summary": to_data(summary),
            "branch_surgeon_refreshed": branch_surgeon_refreshed,
            "old_status": old_status,
            "new_status": status,
        },
    )
