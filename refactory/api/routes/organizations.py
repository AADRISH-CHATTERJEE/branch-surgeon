"""Phase 11.5 — Organization / team / multi-repo Local API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from refactory.api.deps import ContainerDep, RepoRootDep
from refactory.api.routes._helpers import not_found
from refactory.api.schemas import ApiResponse, fail, ok
from refactory.organization.admin_audit import record_admin_audit
from refactory.organization.roles import Permission

router = APIRouter(prefix="/organizations", tags=["organizations"])


class CreateOrganizationBody(BaseModel):
    name: str
    description: str = ""
    slug: str | None = None
    settings: dict[str, Any] | None = None


class UpdateOrganizationBody(BaseModel):
    name: str | None = None
    description: str | None = None
    settings: dict[str, Any] | None = None
    branding: dict[str, Any] | None = None


class CreateTeamBody(BaseModel):
    name: str
    description: str = ""
    slug: str | None = None


class UpdateTeamBody(BaseModel):
    name: str | None = None
    description: str | None = None


class InviteMemberBody(BaseModel):
    email: str
    role: str = "developer"
    display_name: str | None = None
    team_ids: list[str] = Field(default_factory=list)


class UpdateMemberBody(BaseModel):
    role: str | None = None
    display_name: str | None = None
    is_active: bool | None = None
    status: str | None = None


class AddRepositoryBody(BaseModel):
    root_path: str
    name: str | None = None
    nickname: str | None = None
    team_ids: list[str] = Field(default_factory=list)


class TeamMemberBody(BaseModel):
    member_id: str
    team_role: str = "member"


class TeamRepoBody(BaseModel):
    organization_repository_id: str


def _svc(container: ContainerDep):
    return container.organization_management_service


def _seed(container: ContainerDep, repo_root: Path) -> None:
    _svc(container).ensure_defaults(local_repo_root=repo_root)


def _actor(x_member_email: str | None) -> str:
    return (x_member_email or "").strip() or "local@refactory.dev"


def _audit(
    container: ContainerDep,
    *,
    command: str,
    organization_id: str | None,
    summary: str,
    result_data: dict[str, Any] | None = None,
    x_member_email: str | None = None,
) -> None:
    record_admin_audit(
        container,
        command=command,
        organization_id=organization_id,
        summary=summary,
        result_data=result_data,
        actor_email=_actor(x_member_email),
    )


@router.get("/roles", response_model=ApiResponse, summary="RBAC roles catalog")
def roles_catalog(container: ContainerDep) -> ApiResponse:
    return ok(_svc(container).get_roles_catalog())


@router.get("", response_model=ApiResponse, summary="List organizations")
def list_organizations(
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse:
    _seed(container, repo_root)
    rows = _svc(container).list_organizations()
    return ok(rows, meta={"count": len(rows), "repo_root": str(repo_root)})


@router.post("", response_model=ApiResponse, summary="Create organization")
def create_organization(
    body: CreateOrganizationBody,
    container: ContainerDep,
    repo_root: RepoRootDep,
    x_member_email: str | None = Header(default=None, alias="X-Member-Email"),
) -> ApiResponse | JSONResponse:
    _seed(container, repo_root)
    try:
        created = _svc(container).create_organization(
            name=body.name,
            description=body.description,
            slug=body.slug,
            settings=body.settings,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content=fail(str(exc), message="Unable to create organization").model_dump(),
        )
    _audit(
        container,
        command="organization-created",
        organization_id=created.get("id"),
        summary=f"Created organization '{created.get('name') or body.name}'",
        result_data={"entity": "organization", "organization": created},
        x_member_email=x_member_email,
    )
    return ok(created, message="Organization created")


@router.get("/{organization_id}", response_model=ApiResponse)
def get_organization(
    organization_id: str,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse | JSONResponse:
    _seed(container, repo_root)
    row = _svc(container).get_organization(organization_id)
    if row is None:
        return not_found("Organization", organization_id)
    return ok(row)


@router.patch("/{organization_id}", response_model=ApiResponse)
def update_organization(
    organization_id: str,
    body: UpdateOrganizationBody,
    container: ContainerDep,
    x_member_email: str | None = Header(default=None, alias="X-Member-Email"),
) -> ApiResponse | JSONResponse:
    row = _svc(container).update_organization(
        organization_id,
        name=body.name,
        description=body.description,
        settings=body.settings,
        branding=body.branding,
    )
    if row is None:
        return not_found("Organization", organization_id)
    _audit(
        container,
        command="organization-updated",
        organization_id=organization_id,
        summary=f"Updated organization '{row.get('name') or organization_id}'",
        result_data={"entity": "organization", "organization": row},
        x_member_email=x_member_email,
    )
    return ok(row, message="Organization updated")


@router.delete("/{organization_id}", response_model=ApiResponse)
def delete_organization(
    organization_id: str,
    container: ContainerDep,
    x_member_email: str | None = Header(default=None, alias="X-Member-Email"),
) -> ApiResponse | JSONResponse:
    existing = _svc(container).get_organization(organization_id)
    try:
        deleted = _svc(container).delete_organization(organization_id)
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content=fail(str(exc), message="Unable to delete organization").model_dump(),
        )
    if not deleted:
        return not_found("Organization", organization_id)
    _audit(
        container,
        command="organization-deleted",
        organization_id=organization_id,
        summary=f"Deleted organization '{(existing or {}).get('name') or organization_id}'",
        result_data={
            "entity": "organization",
            "organization_id": organization_id,
            "name": (existing or {}).get("name"),
        },
        x_member_email=x_member_email,
    )
    return ok({"deleted": True}, message="Organization deleted")


@router.get("/{organization_id}/dashboard", response_model=ApiResponse)
def organization_dashboard(
    organization_id: str,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse | JSONResponse:
    _seed(container, repo_root)

    def _metrics(root_path: str) -> dict[str, Any]:
        # Soft metrics from the active container when paths match; else zeros.
        empty = {
            "open_reviews": 0,
            "open_recommendations": 0,
            "rule_violations": 0,
        }
        try:
            active = str(Path(container.git_service.get_root_path()).resolve())
            if Path(root_path).resolve() != Path(active).resolve():
                return empty
            repo = container.query_service.get_repository_by_root(active)
            if not repo:
                return empty
            rid = repo["id"]
            reviews = container.query_service.get_reviews(rid, limit=200) or []
            recs = container.query_service.get_recommendations(rid, limit=200) or []
            open_reviews = sum(
                1
                for r in reviews
                if str(r.get("status") or "").lower()
                not in ("completed", "closed", "dismissed")
            )
            open_recs = sum(
                1
                for r in recs
                if str(r.get("status") or "").lower()
                not in ("applied", "dismissed", "rejected")
            )
            return {
                "open_reviews": open_reviews,
                "open_recommendations": open_recs,
                "rule_violations": 0,
            }
        except Exception:  # noqa: BLE001
            return empty

    try:
        data = _svc(container).get_dashboard(
            organization_id, metrics_provider=_metrics
        )
    except ValueError:
        return not_found("Organization", organization_id)
    return ok(data, meta={"repo_root": str(repo_root)})


@router.get("/{organization_id}/teams", response_model=ApiResponse)
def list_teams(organization_id: str, container: ContainerDep) -> ApiResponse:
    return ok(_svc(container).list_teams(organization_id))


@router.post("/{organization_id}/teams", response_model=ApiResponse)
def create_team(
    organization_id: str,
    body: CreateTeamBody,
    container: ContainerDep,
    x_member_email: str | None = Header(default=None, alias="X-Member-Email"),
) -> ApiResponse | JSONResponse:
    try:
        team = _svc(container).create_team(
            organization_id,
            name=body.name,
            description=body.description,
            slug=body.slug,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content=fail(str(exc), message="Unable to create team").model_dump(),
        )
    _audit(
        container,
        command="team-created",
        organization_id=organization_id,
        summary=f"Created team '{team.get('name') or body.name}'",
        result_data={"entity": "team", "team": team},
        x_member_email=x_member_email,
    )
    return ok(team, message="Team created")


@router.get("/{organization_id}/teams/{team_id}", response_model=ApiResponse)
def get_team(
    organization_id: str,
    team_id: str,
    container: ContainerDep,
) -> ApiResponse | JSONResponse:
    team = _svc(container).get_team(team_id)
    if team is None or team.get("organization_id") != organization_id:
        return not_found("Team", team_id)
    return ok(team)


@router.patch("/{organization_id}/teams/{team_id}", response_model=ApiResponse)
def update_team(
    organization_id: str,
    team_id: str,
    body: UpdateTeamBody,
    container: ContainerDep,
    x_member_email: str | None = Header(default=None, alias="X-Member-Email"),
) -> ApiResponse | JSONResponse:
    existing = _svc(container).get_team(team_id)
    if existing is None or existing.get("organization_id") != organization_id:
        return not_found("Team", team_id)
    team = _svc(container).update_team(
        team_id, name=body.name, description=body.description
    )
    _audit(
        container,
        command="team-updated",
        organization_id=organization_id,
        summary=f"Updated team '{(team or existing).get('name') or team_id}'",
        result_data={"entity": "team", "team": team},
        x_member_email=x_member_email,
    )
    return ok(team, message="Team updated")


@router.delete("/{organization_id}/teams/{team_id}", response_model=ApiResponse)
def delete_team(
    organization_id: str,
    team_id: str,
    container: ContainerDep,
    x_member_email: str | None = Header(default=None, alias="X-Member-Email"),
) -> ApiResponse | JSONResponse:
    existing = _svc(container).get_team(team_id)
    if existing is None or existing.get("organization_id") != organization_id:
        return not_found("Team", team_id)
    _svc(container).delete_team(team_id)
    _audit(
        container,
        command="team-deleted",
        organization_id=organization_id,
        summary=f"Deleted team '{existing.get('name') or team_id}'",
        result_data={"entity": "team", "team_id": team_id, "name": existing.get("name")},
        x_member_email=x_member_email,
    )
    return ok({"deleted": True}, message="Team deleted")


@router.post(
    "/{organization_id}/teams/{team_id}/members",
    response_model=ApiResponse,
)
def add_team_member(
    organization_id: str,
    team_id: str,
    body: TeamMemberBody,
    container: ContainerDep,
    x_member_email: str | None = Header(default=None, alias="X-Member-Email"),
) -> ApiResponse | JSONResponse:
    existing = _svc(container).get_team(team_id)
    if existing is None or existing.get("organization_id") != organization_id:
        return not_found("Team", team_id)
    try:
        link = _svc(container).add_team_member(
            team_id, body.member_id, team_role=body.team_role
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content=fail(str(exc), message="Unable to add team member").model_dump(),
        )
    _audit(
        container,
        command="team-member-added",
        organization_id=organization_id,
        summary=f"Added member to team '{existing.get('name') or team_id}'",
        result_data={
            "entity": "team_member",
            "team_id": team_id,
            "member_id": body.member_id,
            "link": link,
        },
        x_member_email=x_member_email,
    )
    return ok(link, message="Team member added")


@router.delete(
    "/{organization_id}/teams/{team_id}/members/{member_id}",
    response_model=ApiResponse,
)
def remove_team_member(
    organization_id: str,
    team_id: str,
    member_id: str,
    container: ContainerDep,
    x_member_email: str | None = Header(default=None, alias="X-Member-Email"),
) -> ApiResponse | JSONResponse:
    existing = _svc(container).get_team(team_id)
    if existing is None or existing.get("organization_id") != organization_id:
        return not_found("Team", team_id)
    removed = _svc(container).remove_team_member(team_id, member_id)
    if not removed:
        return not_found("Team member", member_id)
    _audit(
        container,
        command="team-member-removed",
        organization_id=organization_id,
        summary=f"Removed member from team '{existing.get('name') or team_id}'",
        result_data={
            "entity": "team_member",
            "team_id": team_id,
            "member_id": member_id,
        },
        x_member_email=x_member_email,
    )
    return ok({"deleted": True}, message="Team member removed")


@router.post(
    "/{organization_id}/teams/{team_id}/repositories",
    response_model=ApiResponse,
)
def assign_team_repo(
    organization_id: str,
    team_id: str,
    body: TeamRepoBody,
    container: ContainerDep,
    x_member_email: str | None = Header(default=None, alias="X-Member-Email"),
) -> ApiResponse | JSONResponse:
    existing = _svc(container).get_team(team_id)
    if existing is None or existing.get("organization_id") != organization_id:
        return not_found("Team", team_id)
    try:
        link = _svc(container).assign_repository_to_team(
            team_id, body.organization_repository_id
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content=fail(str(exc), message="Unable to assign repository").model_dump(),
        )
    _audit(
        container,
        command="team-repository-assigned",
        organization_id=organization_id,
        summary=f"Assigned repository to team '{existing.get('name') or team_id}'",
        result_data={
            "entity": "team_repository",
            "team_id": team_id,
            "repository": link,
        },
        x_member_email=x_member_email,
    )
    return ok(link, message="Repository assigned to team")


@router.delete(
    "/{organization_id}/teams/{team_id}/repositories/{repository_id}",
    response_model=ApiResponse,
)
def unassign_team_repo(
    organization_id: str,
    team_id: str,
    repository_id: str,
    container: ContainerDep,
    x_member_email: str | None = Header(default=None, alias="X-Member-Email"),
) -> ApiResponse | JSONResponse:
    existing = _svc(container).get_team(team_id)
    if existing is None or existing.get("organization_id") != organization_id:
        return not_found("Team", team_id)
    removed = _svc(container).unassign_repository_from_team(team_id, repository_id)
    if not removed:
        return not_found("Team repository", repository_id)
    _audit(
        container,
        command="team-repository-unassigned",
        organization_id=organization_id,
        summary=f"Unassigned repository from team '{existing.get('name') or team_id}'",
        result_data={
            "entity": "team_repository",
            "team_id": team_id,
            "repository_id": repository_id,
        },
        x_member_email=x_member_email,
    )
    return ok({"deleted": True}, message="Repository unassigned")

@router.get("/{organization_id}/members", response_model=ApiResponse)
def list_members(organization_id: str, container: ContainerDep) -> ApiResponse:
    return ok(_svc(container).list_members(organization_id))


@router.post("/{organization_id}/members", response_model=ApiResponse)
def invite_member(
    organization_id: str,
    body: InviteMemberBody,
    container: ContainerDep,
    x_member_email: str | None = Header(default=None, alias="X-Member-Email"),
) -> ApiResponse | JSONResponse:
    try:
        member = _svc(container).invite_member(
            organization_id,
            email=body.email,
            role=body.role,
            display_name=body.display_name,
            team_ids=body.team_ids,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content=fail(str(exc), message="Unable to invite member").model_dump(),
        )
    _audit(
        container,
        command="member-invited",
        organization_id=organization_id,
        summary=f"Invited member '{body.email}' as {body.role}",
        result_data={"entity": "member", "member": member, "role": body.role},
        x_member_email=x_member_email,
    )
    return ok(
        member,
        message="Member invited (local profile — no email sent)",
    )


@router.patch("/{organization_id}/members/{member_id}", response_model=ApiResponse)
def update_member(
    organization_id: str,
    member_id: str,
    body: UpdateMemberBody,
    container: ContainerDep,
    x_member_email: str | None = Header(default=None, alias="X-Member-Email"),
) -> ApiResponse | JSONResponse:
    members = _svc(container).list_members(organization_id)
    if not any(m["id"] == member_id for m in members):
        return not_found("Member", member_id)
    row = _svc(container).update_member(
        member_id,
        role=body.role,
        display_name=body.display_name,
        is_active=body.is_active,
        status=body.status,
    )
    if row is None:
        return not_found("Member", member_id)
    role_note = f" role→{body.role}" if body.role else ""
    _audit(
        container,
        command="member-updated",
        organization_id=organization_id,
        summary=f"Updated member '{row.get('email') or member_id}'{role_note}",
        result_data={"entity": "member", "member": row},
        x_member_email=x_member_email,
    )
    return ok(row, message="Member updated")


@router.delete("/{organization_id}/members/{member_id}", response_model=ApiResponse)
def remove_member(
    organization_id: str,
    member_id: str,
    container: ContainerDep,
    x_member_email: str | None = Header(default=None, alias="X-Member-Email"),
) -> ApiResponse | JSONResponse:
    members = _svc(container).list_members(organization_id)
    prior = next((m for m in members if m["id"] == member_id), None)
    if prior is None:
        return not_found("Member", member_id)
    try:
        removed = _svc(container).remove_member(member_id)
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content=fail(str(exc), message="Unable to remove member").model_dump(),
        )
    if not removed:
        return not_found("Member", member_id)
    _audit(
        container,
        command="member-removed",
        organization_id=organization_id,
        summary=f"Removed member '{prior.get('email') or member_id}'",
        result_data={"entity": "member", "member_id": member_id, "email": prior.get("email")},
        x_member_email=x_member_email,
    )
    return ok({"deleted": True}, message="Member removed")


@router.get("/{organization_id}/repositories", response_model=ApiResponse)
def list_repositories(organization_id: str, container: ContainerDep) -> ApiResponse:
    return ok(_svc(container).list_repositories(organization_id))


@router.post("/{organization_id}/repositories", response_model=ApiResponse)
def add_repository(
    organization_id: str,
    body: AddRepositoryBody,
    container: ContainerDep,
    x_member_email: str | None = Header(default=None, alias="X-Member-Email"),
) -> ApiResponse | JSONResponse:
    try:
        link = _svc(container).add_repository(
            organization_id,
            root_path=body.root_path,
            name=body.name,
            nickname=body.nickname,
            team_ids=body.team_ids,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content=fail(str(exc), message="Unable to add repository").model_dump(),
        )
    label = link.get("nickname") or link.get("name") or body.root_path
    _audit(
        container,
        command="organization-repository-linked",
        organization_id=organization_id,
        summary=f"Assigned repository '{label}'",
        result_data={"entity": "repository", "repository": link},
        x_member_email=x_member_email,
    )
    return ok(link, message="Repository linked")


@router.delete(
    "/{organization_id}/repositories/{repository_id}",
    response_model=ApiResponse,
)
def remove_repository(
    organization_id: str,
    repository_id: str,
    container: ContainerDep,
    x_member_email: str | None = Header(default=None, alias="X-Member-Email"),
) -> ApiResponse | JSONResponse:
    prior = next(
        (
            r
            for r in _svc(container).list_repositories(organization_id)
            if r.get("id") == repository_id or r.get("repository_id") == repository_id
        ),
        None,
    )
    removed = _svc(container).remove_repository(organization_id, repository_id)
    if not removed:
        return not_found("Repository link", repository_id)
    label = (prior or {}).get("nickname") or (prior or {}).get("name") or repository_id
    _audit(
        container,
        command="organization-repository-unlinked",
        organization_id=organization_id,
        summary=f"Removed repository '{label}'",
        result_data={
            "entity": "repository",
            "repository_id": repository_id,
            "repository": prior,
        },
        x_member_email=x_member_email,
    )
    return ok({"deleted": True}, message="Repository unlinked")


@router.get("/{organization_id}/me", response_model=ApiResponse)
def acting_member(
    organization_id: str,
    container: ContainerDep,
    x_member_email: str | None = Header(default=None, alias="X-Member-Email"),
) -> ApiResponse | JSONResponse:
    member = _svc(container).resolve_acting_member(
        organization_id, email=x_member_email
    )
    if member is None:
        return not_found("Member", x_member_email or "default")
    return ok(member)


@router.get("/{organization_id}/permissions/check", response_model=ApiResponse)
def check_permission(
    organization_id: str,
    container: ContainerDep,
    permission: str = Query(...),
    x_member_email: str | None = Header(default=None, alias="X-Member-Email"),
) -> ApiResponse | JSONResponse:
    email = x_member_email or "local@refactory.dev"
    try:
        Permission(permission)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content=fail(
                f"'{permission}' is not a supported permission",
                message="Invalid permission",
            ).model_dump(),
        )
    allowed = _svc(container).check_permission(
        organization_id, member_email=email, permission=permission
    )
    return ok({"allowed": allowed, "permission": permission, "email": email})
