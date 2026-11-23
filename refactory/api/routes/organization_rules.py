"""CRUD + preview + import/export for organization (company) rules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from refactory.api.deps import ContainerDep, RepoRootDep
from refactory.api.routes._helpers import not_found
from refactory.api.schemas import ApiResponse, fail, ok
from refactory.api.serialize import to_data
from refactory.organization.models import OrganizationRulePayload

router = APIRouter(prefix="/organization-rules", tags=["organization-rules"])


class OrgRulePreviewRequest(BaseModel):
    rule: dict[str, Any] | None = None
    rule_id: str | None = None
    branch: str | None = None
    commit: str | None = None
    changed_files: list[str] | None = None


class OrgRuleImportRequest(BaseModel):
    rules: list[dict[str, Any]] = Field(default_factory=list)
    replace: bool = False
    version: str | None = None
    type: str | None = None


def _repo_id(container: ContainerDep) -> str | None:
    root = Path(container.git_service.get_root_path()).resolve()
    repo = container.query_service.get_repository_by_root(str(root))
    return repo["id"] if repo else None


def _activity(container: ContainerDep, command: str, payload: dict[str, Any]) -> None:
    rid = _repo_id(container)
    if rid:
        container.organization_rule_service.log_activity_for_repo(rid, command, payload)


@router.get("", response_model=ApiResponse, summary="List organization rules")
def list_organization_rules(
    container: ContainerDep,
    repo_root: RepoRootDep,
    enabled: bool | None = Query(None),
    search: str | None = Query(None),
    organization_id: str | None = Query(None),
    team_id: str | None = Query(None),
    scope: str | None = Query(
        None,
        description="all | organization | team | effective",
    ),
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_team_id: str | None = Header(default=None, alias="X-Team-Id"),
) -> ApiResponse:
    org = organization_id or x_org_id
    team = team_id or x_team_id
    rows = container.organization_rule_service.list_rules(
        enabled=enabled,
        search=search,
        organization_id=org,
        team_id=team,
        scope=scope,
    )
    if org or team:
        container.company_rules_checker.set_rule_scope(
            organization_id=org, team_id=team
        )
    return ok(
        rows,
        meta={
            "repo_root": str(repo_root),
            "count": len(rows),
            "source": "organization",
            "organization_id": org,
            "team_id": team,
            "scope": scope or "all",
        },
    )


@router.post("", response_model=ApiResponse, summary="Create organization rule")
def create_organization_rule(
    body: OrganizationRulePayload,
    container: ContainerDep,
    repo_root: RepoRootDep,
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    x_team_id: str | None = Header(default=None, alias="X-Team-Id"),
) -> ApiResponse | JSONResponse:
    payload = body.model_copy(
        update={
            "organization_id": body.organization_id or x_org_id,
            "team_id": body.team_id or x_team_id,
        }
    )
    try:
        created = container.organization_rule_service.create_rule(payload)
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content=fail(str(exc), message="Unable to create rule").model_dump(),
        )
    _activity(container, "organization-rule-created", created)
    return ok(created, message="Organization rule created", meta={"repo_root": str(repo_root)})


@router.get("/export", response_model=ApiResponse, summary="Export organization rules JSON")
def export_organization_rules(container: ContainerDep, repo_root: RepoRootDep) -> ApiResponse:
    payload = container.organization_rule_service.export_rules()
    return ok(payload, meta={"repo_root": str(repo_root)})


@router.post("/import", response_model=ApiResponse, summary="Import organization rules JSON")
def import_organization_rules(
    body: OrgRuleImportRequest,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse | JSONResponse:
    try:
        result = container.organization_rule_service.import_rules(
            body.model_dump(), replace=body.replace
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content=fail(str(exc), message="Unable to import rules").model_dump(),
        )
    _activity(
        container,
        "organization-rules-imported",
        {"created": result["created"], "updated": result["updated"]},
    )
    return ok(result, message="Organization rules imported", meta={"repo_root": str(repo_root)})


@router.post("/preview", response_model=ApiResponse, summary="Preview rule against repository")
def preview_organization_rule(
    body: OrgRulePreviewRequest,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse | JSONResponse:
    root = Path(container.git_service.get_root_path()).resolve()
    try:
        result = container.organization_rule_service.preview(
            root,
            rule=body.rule,
            rule_id=body.rule_id,
            branch_name=body.branch or "",
            commit_message=body.commit or "",
            changed_files=body.changed_files,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content=fail(str(exc), message="Unable to preview rule").model_dump(),
        )
    return ok(to_data(result), message="Preview complete", meta={"repo_root": str(repo_root)})


@router.get("/audit", response_model=ApiResponse, summary="List organization rule audit entries")
def list_organization_rule_audits(
    container: ContainerDep,
    repo_root: RepoRootDep,
    rule_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> ApiResponse:
    rows = container.organization_rule_service.list_audit(rule_id, limit=limit)
    return ok(rows, meta={"repo_root": str(repo_root), "count": len(rows)})


@router.get("/{rule_id}", response_model=ApiResponse, summary="Get organization rule")
def get_organization_rule(
    rule_id: str, container: ContainerDep, repo_root: RepoRootDep
) -> ApiResponse | JSONResponse:
    row = container.organization_rule_service.get_rule(rule_id)
    if row is None:
        return not_found("Not found", f"Organization rule '{rule_id}' not found")
    return ok(row, meta={"repo_root": str(repo_root)})


@router.put("/{rule_id}", response_model=ApiResponse, summary="Update organization rule")
def update_organization_rule(
    rule_id: str,
    body: OrganizationRulePayload,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse | JSONResponse:
    try:
        updated = container.organization_rule_service.update_rule(rule_id, body)
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content=fail(str(exc), message="Unable to update rule").model_dump(),
        )
    if updated is None:
        return not_found("Not found", f"Organization rule '{rule_id}' not found")
    _activity(container, "organization-rule-updated", updated)
    return ok(updated, message="Organization rule updated", meta={"repo_root": str(repo_root)})


@router.delete("/{rule_id}", response_model=ApiResponse, summary="Delete organization rule")
def delete_organization_rule(
    rule_id: str, container: ContainerDep, repo_root: RepoRootDep
) -> ApiResponse | JSONResponse:
    existing = container.organization_rule_service.get_rule(rule_id)
    if existing is None:
        return not_found("Not found", f"Organization rule '{rule_id}' not found")
    ok_del = container.organization_rule_service.delete_rule(rule_id)
    if not ok_del:
        return not_found("Not found", f"Organization rule '{rule_id}' not found")
    _activity(container, "organization-rule-deleted", existing)
    return ok(
        {"id": rule_id, "deleted": True},
        message="Organization rule deleted",
        meta={"repo_root": str(repo_root)},
    )


@router.post(
    "/{rule_id}/duplicate",
    response_model=ApiResponse,
    summary="Duplicate organization rule",
)
def duplicate_organization_rule(
    rule_id: str, container: ContainerDep, repo_root: RepoRootDep
) -> ApiResponse | JSONResponse:
    dup = container.organization_rule_service.duplicate_rule(rule_id)
    if dup is None:
        return not_found("Not found", f"Organization rule '{rule_id}' not found")
    _activity(container, "organization-rule-created", dup)
    return ok(dup, message="Organization rule duplicated", meta={"repo_root": str(repo_root)})


@router.post("/{rule_id}/enable", response_model=ApiResponse, summary="Enable organization rule")
def enable_organization_rule(
    rule_id: str, container: ContainerDep, repo_root: RepoRootDep
) -> ApiResponse | JSONResponse:
    row = container.organization_rule_service.set_enabled(rule_id, True)
    if row is None:
        return not_found("Not found", f"Organization rule '{rule_id}' not found")
    _activity(container, "organization-rule-enabled", row)
    return ok(row, message="Organization rule enabled", meta={"repo_root": str(repo_root)})


@router.post("/{rule_id}/disable", response_model=ApiResponse, summary="Disable organization rule")
def disable_organization_rule(
    rule_id: str, container: ContainerDep, repo_root: RepoRootDep
) -> ApiResponse | JSONResponse:
    row = container.organization_rule_service.set_enabled(rule_id, False)
    if row is None:
        return not_found("Not found", f"Organization rule '{rule_id}' not found")
    _activity(container, "organization-rule-disabled", row)
    return ok(row, message="Organization rule disabled", meta={"repo_root": str(repo_root)})
