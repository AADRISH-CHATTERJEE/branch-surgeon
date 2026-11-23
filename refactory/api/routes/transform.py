"""Transform preview / apply / rollback / history Local API."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from refactory.api.deps import ContainerDep, RepoRootDep
from refactory.api.routes._post_transform import (
    pipeline_meta,
    run_post_transformation_pipeline,
)
from refactory.api.schemas import ApiResponse, TransformRequest, fail, ok
from refactory.api.serialize import to_data
from refactory.transformation.models import (
    TransformationError,
    TransformationRequest,
    TransformationStatus,
    TransformationType,
)

router = APIRouter(tags=["transform"])


def _parse_type(raw: str) -> TransformationType:
    try:
        return TransformationType(raw)
    except ValueError:
        normalized = raw.lower().replace("-", "_")
        aliases = {
            "move": TransformationType.MOVE_SYMBOL,
            "rename": TransformationType.RENAME_SYMBOL,
            "extract": TransformationType.EXTRACT_METHOD,
            "inline": TransformationType.INLINE_METHOD,
            "signature": TransformationType.CHANGE_SIGNATURE,
        }
        if normalized in aliases:
            return aliases[normalized]
        for tt in TransformationType:
            if tt.value == normalized:
                return tt
        detail = f"Unknown transformation type: {raw}"
        raise TransformationError(
            "Invalid transformation request.",
            reason=detail,
            errors=[detail],
        )


def _to_request(body: TransformRequest) -> TransformationRequest:
    parameters = dict(body.parameters or {})
    if body.target_symbol and "old_name" not in parameters:
        parameters.setdefault("old_name", body.target_symbol)
    if body.new_name:
        parameters.setdefault("new_name", body.new_name)
    if body.method_name:
        parameters.setdefault("method_name", body.method_name)
    if body.start_line is not None:
        parameters.setdefault("start_line", body.start_line)
    if body.end_line is not None:
        parameters.setdefault("end_line", body.end_line)
    if body.destination_file:
        parameters.setdefault("destination_file", body.destination_file)
    if body.param_order is not None:
        parameters.setdefault("param_order", body.param_order)
    if body.rename_params is not None:
        parameters.setdefault("rename_params", body.rename_params)
    if body.scope:
        parameters.setdefault("scope", body.scope)

    ttype = _parse_type(body.transformation_type)
    nl = (body.natural_language or "").strip()
    if nl and ttype == TransformationType.RENAME_SYMBOL and not body.target_symbol:
        # Natural-language-only requests use the AI planner path.
        ttype = TransformationType.AI_PLAN

    return TransformationRequest(
        transformation_type=ttype,
        target_file=body.target_file or "",
        target_symbol=body.target_symbol or "",
        parameters=parameters,
        ai_assisted=bool(body.ai_assisted) or bool(nl),
        natural_language=nl,
        scope=(body.scope or "").strip(),
    )


def _error_response(exc: TransformationError) -> JSONResponse:
    errors = list(exc.errors) if getattr(exc, "errors", None) else []
    if not errors:
        detail = exc.reason or exc.message or "Invalid transformation request."
        errors = [detail]
    meta = dict(getattr(exc, "meta", None) or {})
    body = fail(
        *errors,
        message=exc.message or "Transformation failed",
        meta=meta,
    ).model_dump(mode="json")
    # Never return an empty/partial error payload.
    body.setdefault("status", "error")
    body["message"] = body.get("message") or "Transformation failed"
    body["errors"] = body.get("errors") or errors
    body.setdefault("data", None)
    body.setdefault("meta", meta)
    status_code = int(getattr(exc, "status_code", None) or 422)
    return JSONResponse(status_code=status_code, content=body)


def _history_item(row: object) -> dict:
    data = to_data(row)
    if isinstance(data, dict):
        # Keep payload lean for list endpoints
        data.pop("patch_content", None)
        data.pop("rollback_patch", None)
        steps = data.get("steps") or []
        data["steps"] = [
            {
                "file_path": s.get("file_path"),
                "description": s.get("description"),
                "start_line": s.get("start_line"),
                "end_line": s.get("end_line"),
            }
            for s in steps
            if isinstance(s, dict)
        ]
        status = str(data.get("status") or "").lower()
        rolled_back = status == "rolled_back" or bool(data.get("rolled_back"))
        data["rolled_back"] = rolled_back
        data["canRollback"] = (not rolled_back) and status == "applied"
        data["can_rollback"] = data["canRollback"]
        if rolled_back and not data.get("rolled_back_at"):
            data["rolled_back_at"] = data.get("updated_at") or data.get("created_at")
    return data  # type: ignore[return-value]


@router.get(
    "",
    response_model=ApiResponse,
    summary="List applied transformations",
)
def list_transformations(
    container: ContainerDep,
    repo_root: RepoRootDep,
    limit: int = Query(50, ge=1, le=200),
) -> ApiResponse:
    svc = container.transformation_service
    svc.ensure_history_loaded(Path(container.git_service.get_root_path()).resolve())
    rows = list(reversed(svc.get_history()))[:limit]
    return ok(
        [_history_item(r) for r in rows],
        message="Transformations",
        meta={"count": len(rows), "repo_root": str(repo_root)},
    )


@router.get(
    "/recent",
    response_model=ApiResponse,
    summary="Recent applied transformations (newest first)",
)
def recent_transformations(
    container: ContainerDep,
    repo_root: RepoRootDep,
    limit: int = Query(5, ge=1, le=50),
) -> ApiResponse:
    svc = container.transformation_service
    svc.ensure_history_loaded(Path(container.git_service.get_root_path()).resolve())
    rows = svc.list_recent(limit=limit)
    return ok(
        [_history_item(r) for r in rows],
        message="Recent transformations",
        meta={"count": len(rows), "repo_root": str(repo_root)},
    )


@router.get(
    "/{history_id}",
    response_model=ApiResponse,
    summary="Get a transformation record",
)
def get_transformation(
    history_id: str,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse | JSONResponse:
    svc = container.transformation_service
    svc.ensure_history_loaded(Path(container.git_service.get_root_path()).resolve())
    row = svc.get_record(history_id)
    if row is None:
        return JSONResponse(
            status_code=404,
            content=fail(f"Transformation not found: {history_id}", message="Not found").model_dump(),
        )
    return ok(to_data(row), meta={"repo_root": str(repo_root)})


@router.post(
    "/plan",
    response_model=ApiResponse,
    summary="Build a TransformationPlan without generating a patch",
    description="Uses the AI Refactoring Planner and/or deterministic planners.",
)
def plan_transform(
    body: TransformRequest,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse | JSONResponse:
    root = Path(container.git_service.get_root_path()).resolve()
    try:
        plan = container.transformation_service.plan_only(_to_request(body), root)
    except TransformationError as exc:
        return _error_response(exc)
    return ok(
        to_data(plan),
        message="Transformation plan",
        meta={"repo_root": str(repo_root)},
    )


@router.post(
    "",
    response_model=ApiResponse,
    summary="Preview a transformation (no file writes)",
    description="Delegates to TransformationService.preview.",
)
def preview_transform(
    body: TransformRequest,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse | JSONResponse:
    root = Path(container.git_service.get_root_path()).resolve()
    try:
        preview = container.transformation_service.preview(_to_request(body), root)
    except TransformationError as exc:
        return _error_response(exc)
    return ok(
        to_data(preview),
        message="Transformation preview",
        meta={"repo_root": str(repo_root)},
    )


@router.post(
    "/apply",
    response_model=ApiResponse,
    summary="Apply a transformation",
    description="Delegates to TransformationService.apply.",
)
def apply_transform(
    body: TransformRequest,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse | JSONResponse:
    root = Path(container.git_service.get_root_path()).resolve()
    try:
        result = container.transformation_service.apply(_to_request(body), root)
    except TransformationError as exc:
        return _error_response(exc)
    refresh = None
    status = getattr(result, "status", None)
    status_value = getattr(status, "value", status)
    if status_value == TransformationStatus.APPLIED.value:
        refresh = run_post_transformation_pipeline(
            container,
            root,
            trigger="transform-apply",
            transformation_id=getattr(result, "id", None),
        )
    else:
        container.recommendation_stats_service.invalidate(repo_root=root)
    return ok(
        to_data(result),
        message="Transformation applied",
        meta={"repo_root": str(repo_root), **pipeline_meta(refresh)},
    )


@router.post(
    "/rollback",
    response_model=ApiResponse,
    summary="Rollback the last transformation",
    description="Delegates to TransformationService.rollback.",
)
def rollback_transform(
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse | JSONResponse:
    root = Path(container.git_service.get_root_path()).resolve()
    container.transformation_service.ensure_history_loaded(root)
    try:
        result = container.transformation_service.rollback(root)
    except TransformationError as exc:
        return _error_response(exc)
    refresh = None
    status = getattr(result, "status", None)
    status_value = getattr(status, "value", status)
    if status_value == TransformationStatus.ROLLED_BACK.value:
        refresh = run_post_transformation_pipeline(
            container,
            root,
            trigger="transform-rollback",
            transformation_id=getattr(result, "id", None),
        )
    else:
        container.recommendation_stats_service.invalidate(repo_root=root)
    return ok(
        to_data(result),
        message="Rollback successful",
        meta={"repo_root": str(repo_root), **pipeline_meta(refresh)},
    )


@router.post(
    "/{history_id}/rollback",
    response_model=ApiResponse,
    summary="Rollback a specific transformation by id",
)
def rollback_transformation_by_id(
    history_id: str,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse | JSONResponse:
    root = Path(container.git_service.get_root_path()).resolve()
    container.transformation_service.ensure_history_loaded(root)
    try:
        result = container.transformation_service.rollback(root, history_id=history_id)
    except TransformationError as exc:
        return _error_response(exc)
    refresh = None
    status = getattr(result, "status", None)
    status_value = getattr(status, "value", status)
    if status_value == TransformationStatus.ROLLED_BACK.value:
        refresh = run_post_transformation_pipeline(
            container,
            root,
            trigger="transform-rollback",
            transformation_id=history_id,
        )
    else:
        container.recommendation_stats_service.invalidate(repo_root=root)
    return ok(
        to_data(result),
        message="Rollback successful",
        meta={"repo_root": str(repo_root), **pipeline_meta(refresh)},
    )
