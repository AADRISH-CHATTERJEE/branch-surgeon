"""Phase 11.5 — Organization / team / multi-repo management (local, no auth)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from refactory.db.models import (
    OrganizationMemberModel,
    OrganizationModel,
    OrganizationRepositoryModel,
    TeamMemberModel,
    TeamModel,
    TeamRepositoryModel,
)
from refactory.db.uow import UnitOfWork
from refactory.organization.roles import (
    OrgRole,
    Permission,
    TeamRole,
    has_permission,
    permissions_for,
)

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or "org"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OrganizationManagementService:
    """CRUD for organizations, teams, members, and repository links.

    Uses a dedicated SessionFactory (typically the global catalog DB at
    ``~/.refactory/db/``). Does not rewrite analysis / review / patch pipelines.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def ensure_defaults(self, *, local_repo_root: Path | None = None) -> dict[str, Any]:
        """Create a default organization + local actor if the catalog is empty."""
        with UnitOfWork(self._session_factory) as uow:
            existing = uow.organizations.list_all(limit=1)
            if existing:
                org = existing[0]
                if local_repo_root is not None:
                    self._ensure_repo_linked(uow, org.id, local_repo_root)
                    uow.commit()
                return self._org_to_dict(org, include_counts=True, uow=uow)

            now = _utcnow()
            org = OrganizationModel(
                id=str(uuid4()),
                name="Default Organization",
                slug="default",
                description="Local default organization for multi-repo Refactory.",
                branding={
                    "primary_color": "#0f766e",
                    "permissions": {},
                    "integrations": {},
                    "api_keys": [],
                },
                is_default=True,
                created_at=now,
                updated_at=now,
            )
            uow.organizations.create(
                id=org.id,
                name=org.name,
                slug=org.slug,
                description=org.description,
                branding=org.branding,
                is_default=True,
                created_at=now,
                updated_at=now,
            )

            owner = uow.organization_members.create(
                id=str(uuid4()),
                organization_id=org.id,
                email="local@refactory.dev",
                display_name="Local User",
                role=OrgRole.OWNER.value,
                is_active=True,
                created_at=now,
                updated_at=now,
            )

            for team_name, team_slug in (
                ("Backend Team", "backend"),
                ("Frontend Team", "frontend"),
                ("Platform Team", "platform"),
            ):
                team = uow.teams.create(
                    id=str(uuid4()),
                    organization_id=org.id,
                    name=team_name,
                    slug=team_slug,
                    description=f"{team_name} for {org.name}",
                    created_at=now,
                    updated_at=now,
                )
                uow.team_members.create(
                    id=str(uuid4()),
                    team_id=team.id,
                    member_id=owner.id,
                    role=TeamRole.LEAD.value,
                    created_at=now,
                )

            if local_repo_root is not None:
                self._ensure_repo_linked(uow, org.id, local_repo_root)

            uow.commit()
            logger.info("Seeded default organization %s", org.id)
            refreshed = uow.organizations.get_by_id(org.id)
            assert refreshed is not None
            return self._org_to_dict(refreshed, include_counts=True, uow=uow)

    # ── Organizations ─────────────────────────────────────────────────────

    def list_organizations(self) -> list[dict[str, Any]]:
        with UnitOfWork(self._session_factory) as uow:
            orgs = uow.organizations.list_all()
            return [self._org_to_dict(o, include_counts=True, uow=uow) for o in orgs]

    def get_organization(self, organization_id: str) -> dict[str, Any] | None:
        with UnitOfWork(self._session_factory) as uow:
            org = uow.organizations.get_by_id(organization_id)
            if org is None:
                return None
            return self._org_to_dict(org, include_counts=True, uow=uow)

    def create_organization(
        self,
        *,
        name: str,
        description: str = "",
        slug: str | None = None,
        settings: dict[str, Any] | None = None,
        created_by_email: str = "local@refactory.dev",
    ) -> dict[str, Any]:
        with UnitOfWork(self._session_factory) as uow:
            base_slug = _slugify(slug or name)
            candidate = base_slug
            n = 1
            while uow.organizations.get_by_slug(candidate) is not None:
                n += 1
                candidate = f"{base_slug}-{n}"

            now = _utcnow()
            branding = {
                "primary_color": "#0f766e",
                "permissions": {},
                "integrations": {},
                "api_keys": [],
            }
            if settings:
                branding.update(settings)

            org = uow.organizations.create(
                id=str(uuid4()),
                name=name.strip(),
                slug=candidate,
                description=description.strip(),
                branding=branding,
                is_default=False,
                created_at=now,
                updated_at=now,
            )
            uow.organization_members.create(
                id=str(uuid4()),
                organization_id=org.id,
                email=created_by_email.strip().lower(),
                display_name=created_by_email.split("@")[0],
                role=OrgRole.OWNER.value,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            uow.commit()
            return self._org_to_dict(org, include_counts=True, uow=uow)

    def update_organization(
        self,
        organization_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        settings: dict[str, Any] | None = None,
        branding: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with UnitOfWork(self._session_factory) as uow:
            org = uow.organizations.get_by_id(organization_id)
            if org is None:
                return None
            if name is not None:
                org.name = name.strip()
            if description is not None:
                org.description = description.strip()
            if branding is not None or settings is not None:
                merged = dict(org.branding or {})
                if branding:
                    merged.update(branding)
                if settings:
                    merged.update(settings)
                org.branding = merged
            org.updated_at = _utcnow()
            uow.commit()
            return self._org_to_dict(org, include_counts=True, uow=uow)

    def delete_organization(self, organization_id: str) -> bool:
        with UnitOfWork(self._session_factory) as uow:
            org = uow.organizations.get_by_id(organization_id)
            if org is None:
                return False
            if org.is_default:
                raise ValueError("Cannot delete the default organization")
            for team in list(uow.teams.list_by_organization(organization_id)):
                for tm in list(uow.team_members.list_by_team(team.id)):
                    uow.team_members.delete(tm.id)
                for tr in list(uow.team_repositories.list_by_team(team.id)):
                    uow.team_repositories.delete(tr.id)
                uow.teams.delete(team.id)
            for member in list(
                uow.organization_members.list_by_organization(organization_id)
            ):
                uow.organization_members.delete(member.id)
            for link in list(
                uow.organization_repositories.list_by_organization(organization_id)
            ):
                uow.organization_repositories.delete(link.id)
            uow.organizations.delete(org.id)
            uow.commit()
            return True

    # ── Teams ─────────────────────────────────────────────────────────────

    def list_teams(self, organization_id: str) -> list[dict[str, Any]]:
        with UnitOfWork(self._session_factory) as uow:
            teams = uow.teams.list_by_organization(organization_id)
            return [self._team_to_dict(t, uow=uow) for t in teams]

    def get_team(self, team_id: str) -> dict[str, Any] | None:
        with UnitOfWork(self._session_factory) as uow:
            team = uow.teams.get_by_id(team_id)
            if team is None:
                return None
            return self._team_to_dict(team, uow=uow)

    def create_team(
        self,
        organization_id: str,
        *,
        name: str,
        description: str = "",
        slug: str | None = None,
    ) -> dict[str, Any]:
        with UnitOfWork(self._session_factory) as uow:
            if uow.organizations.get_by_id(organization_id) is None:
                raise ValueError(f"Organization not found: {organization_id}")
            base_slug = _slugify(slug or name)
            candidate = base_slug
            n = 1
            while uow.teams.get_by_slug(organization_id, candidate) is not None:
                n += 1
                candidate = f"{base_slug}-{n}"
            now = _utcnow()
            team = uow.teams.create(
                id=str(uuid4()),
                organization_id=organization_id,
                name=name.strip(),
                slug=candidate,
                description=description.strip(),
                created_at=now,
                updated_at=now,
            )
            uow.commit()
            return self._team_to_dict(team, uow=uow)

    def update_team(
        self,
        team_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any] | None:
        with UnitOfWork(self._session_factory) as uow:
            team = uow.teams.get_by_id(team_id)
            if team is None:
                return None
            if name is not None:
                team.name = name.strip()
            if description is not None:
                team.description = description.strip()
            team.updated_at = _utcnow()
            uow.commit()
            return self._team_to_dict(team, uow=uow)

    def delete_team(self, team_id: str) -> bool:
        with UnitOfWork(self._session_factory) as uow:
            team = uow.teams.get_by_id(team_id)
            if team is None:
                return False
            for tm in list(uow.team_members.list_by_team(team_id)):
                uow.team_members.delete(tm.id)
            for tr in list(uow.team_repositories.list_by_team(team_id)):
                uow.team_repositories.delete(tr.id)
            uow.teams.delete(team.id)
            uow.commit()
            return True

    # ── Members ───────────────────────────────────────────────────────────

    def list_members(self, organization_id: str) -> list[dict[str, Any]]:
        with UnitOfWork(self._session_factory) as uow:
            members = uow.organization_members.list_by_organization(organization_id)
            return [self._member_to_dict(m) for m in members]

    def invite_member(
        self,
        organization_id: str,
        *,
        email: str,
        role: str = OrgRole.DEVELOPER.value,
        display_name: str | None = None,
        team_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        role_enum = OrgRole(role)
        with UnitOfWork(self._session_factory) as uow:
            if uow.organizations.get_by_id(organization_id) is None:
                raise ValueError(f"Organization not found: {organization_id}")
            email_n = email.strip().lower()
            existing = next(
                (
                    m
                    for m in uow.organization_members.list_by_organization(
                        organization_id
                    )
                    if (m.email or "").lower() == email_n
                ),
                None,
            )
            if existing is not None:
                raise ValueError(f"Member already exists: {email_n}")

            now = _utcnow()
            member = uow.organization_members.create(
                id=str(uuid4()),
                organization_id=organization_id,
                email=email_n,
                display_name=(display_name or email_n.split("@")[0]).strip(),
                role=role_enum.value,
                is_active=False,  # invited (no email send — local profile only)
                created_at=now,
                updated_at=now,
            )

            for team_id in team_ids or []:
                team = uow.teams.get_by_id(team_id)
                if team is None or team.organization_id != organization_id:
                    continue
                uow.team_members.create(
                    id=str(uuid4()),
                    team_id=team_id,
                    member_id=member.id,
                    role=TeamRole.MEMBER.value,
                    created_at=now,
                )

            uow.commit()
            return self._member_to_dict(member)

    def update_member(
        self,
        member_id: str,
        *,
        role: str | None = None,
        display_name: str | None = None,
        is_active: bool | None = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        with UnitOfWork(self._session_factory) as uow:
            member = uow.organization_members.get_by_id(member_id)
            if member is None:
                return None
            if role is not None:
                member.role = OrgRole(role).value
            if display_name is not None:
                member.display_name = display_name.strip()
            if is_active is not None:
                member.is_active = bool(is_active)
            if status is not None:
                member.is_active = status.lower() in ("active", "accepted")
            member.updated_at = _utcnow()
            uow.commit()
            return self._member_to_dict(member)

    def remove_member(self, member_id: str) -> bool:
        with UnitOfWork(self._session_factory) as uow:
            member = uow.organization_members.get_by_id(member_id)
            if member is None:
                return False
            if member.role == OrgRole.OWNER.value:
                owners = [
                    m
                    for m in uow.organization_members.list_by_organization(
                        member.organization_id
                    )
                    if m.role == OrgRole.OWNER.value
                ]
                if len(owners) <= 1:
                    raise ValueError("Cannot remove the last organization owner")
            for team in uow.teams.list_by_organization(member.organization_id):
                for tm in list(uow.team_members.list_by_team(team.id)):
                    if tm.member_id == member_id:
                        uow.team_members.delete(tm.id)
            uow.organization_members.delete(member.id)
            uow.commit()
            return True

    def add_team_member(
        self,
        team_id: str,
        member_id: str,
        *,
        team_role: str = TeamRole.MEMBER.value,
    ) -> dict[str, Any]:
        with UnitOfWork(self._session_factory) as uow:
            team = uow.teams.get_by_id(team_id)
            if team is None:
                raise ValueError(f"Team not found: {team_id}")
            member = uow.organization_members.get_by_id(member_id)
            if member is None or member.organization_id != team.organization_id:
                raise ValueError("Member not in organization")
            for existing in uow.team_members.list_by_team(team_id):
                if existing.member_id == member_id:
                    existing.role = TeamRole(team_role).value
                    uow.commit()
                    return {
                        "id": existing.id,
                        "team_id": team_id,
                        "member_id": member_id,
                        "team_role": existing.role,
                    }
            link = uow.team_members.create(
                id=str(uuid4()),
                team_id=team_id,
                member_id=member_id,
                role=TeamRole(team_role).value,
                created_at=_utcnow(),
            )
            uow.commit()
            return {
                "id": link.id,
                "team_id": team_id,
                "member_id": member_id,
                "team_role": link.role,
            }

    def remove_team_member(self, team_id: str, member_id: str) -> bool:
        with UnitOfWork(self._session_factory) as uow:
            for tm in uow.team_members.list_by_team(team_id):
                if tm.member_id == member_id:
                    uow.team_members.delete(tm.id)
                    uow.commit()
                    return True
            return False

    # ── Repositories ──────────────────────────────────────────────────────

    def list_repositories(self, organization_id: str) -> list[dict[str, Any]]:
        with UnitOfWork(self._session_factory) as uow:
            links = uow.organization_repositories.list_by_organization(organization_id)
            return [self._repo_link_to_dict(r) for r in links]

    def add_repository(
        self,
        organization_id: str,
        *,
        root_path: str,
        name: str | None = None,
        nickname: str | None = None,
        team_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        from refactory.api.repo_root import validate_repository_root

        try:
            validated = validate_repository_root(Path(root_path))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(str(exc)) from exc
        root = str(validated)
        with UnitOfWork(self._session_factory) as uow:
            if uow.organizations.get_by_id(organization_id) is None:
                raise ValueError(f"Organization not found: {organization_id}")
            existing = uow.organization_repositories.get_by_root(organization_id, root)
            if existing is not None:
                return self._repo_link_to_dict(existing)

            link = uow.organization_repositories.create(
                id=str(uuid4()),
                organization_id=organization_id,
                repository_root_path=root,
                repository_name=name or Path(root).name,
                nickname=nickname,
                created_at=_utcnow(),
            )

            for team_id in team_ids or []:
                team = uow.teams.get_by_id(team_id)
                if team is None or team.organization_id != organization_id:
                    continue
                uow.team_repositories.create(
                    id=str(uuid4()),
                    team_id=team_id,
                    organization_repository_id=link.id,
                    created_at=_utcnow(),
                )

            uow.commit()
            return self._repo_link_to_dict(link)

    def remove_repository(self, organization_id: str, repository_link_id: str) -> bool:
        with UnitOfWork(self._session_factory) as uow:
            link = uow.organization_repositories.get_by_id(repository_link_id)
            if link is None or link.organization_id != organization_id:
                return False
            for team in uow.teams.list_by_organization(organization_id):
                for tr in list(uow.team_repositories.list_by_team(team.id)):
                    if tr.organization_repository_id == repository_link_id:
                        uow.team_repositories.delete(tr.id)
            uow.organization_repositories.delete(link.id)
            uow.commit()
            return True

    def assign_repository_to_team(
        self, team_id: str, organization_repository_id: str
    ) -> dict[str, Any]:
        with UnitOfWork(self._session_factory) as uow:
            team = uow.teams.get_by_id(team_id)
            if team is None:
                raise ValueError(f"Team not found: {team_id}")
            link = uow.organization_repositories.get_by_id(organization_repository_id)
            if link is None or link.organization_id != team.organization_id:
                raise ValueError("Repository not in organization")
            for existing in uow.team_repositories.list_by_team(team_id):
                if existing.organization_repository_id == organization_repository_id:
                    return {
                        "id": existing.id,
                        "team_id": team_id,
                        "organization_repository_id": organization_repository_id,
                    }
            row = uow.team_repositories.create(
                id=str(uuid4()),
                team_id=team_id,
                organization_repository_id=organization_repository_id,
                created_at=_utcnow(),
            )
            uow.commit()
            return {
                "id": row.id,
                "team_id": team_id,
                "organization_repository_id": organization_repository_id,
            }

    def unassign_repository_from_team(
        self, team_id: str, organization_repository_id: str
    ) -> bool:
        with UnitOfWork(self._session_factory) as uow:
            for tr in uow.team_repositories.list_by_team(team_id):
                if tr.organization_repository_id == organization_repository_id:
                    uow.team_repositories.delete(tr.id)
                    uow.commit()
                    return True
            return False

    # ── Dashboard / RBAC helpers ──────────────────────────────────────────

    def get_dashboard(
        self,
        organization_id: str,
        *,
        metrics_provider: Any | None = None,
    ) -> dict[str, Any]:
        with UnitOfWork(self._session_factory) as uow:
            org = uow.organizations.get_by_id(organization_id)
            if org is None:
                raise ValueError(f"Organization not found: {organization_id}")
            teams = uow.teams.list_by_organization(organization_id)
            members = uow.organization_members.list_by_organization(organization_id)
            repos = uow.organization_repositories.list_by_organization(organization_id)

            repo_metrics: list[dict[str, Any]] = []
            totals = {
                "open_reviews": 0,
                "open_recommendations": 0,
                "rule_violations": 0,
            }
            if metrics_provider is not None:
                for link in repos:
                    try:
                        m = metrics_provider(link.repository_root_path)
                        if isinstance(m, dict):
                            repo_metrics.append(
                                {
                                    "repository_id": link.id,
                                    "repository_name": link.repository_name,
                                    **m,
                                }
                            )
                            totals["open_reviews"] += int(m.get("open_reviews") or 0)
                            totals["open_recommendations"] += int(
                                m.get("open_recommendations") or 0
                            )
                            totals["rule_violations"] += int(
                                m.get("rule_violations") or 0
                            )
                    except Exception as exc:  # noqa: BLE001
                        logger.debug(
                            "Dashboard metrics skipped for %s: %s",
                            link.repository_root_path,
                            exc,
                        )

            return {
                "organization": self._org_to_dict(org, include_counts=False, uow=uow),
                "counts": {
                    "repositories": len(repos),
                    "developers": len(members),
                    "teams": len(teams),
                },
                "open_reviews": totals["open_reviews"],
                "open_recommendations": totals["open_recommendations"],
                "branch_health": None,
                "rule_violations": totals["rule_violations"],
                "patch_success_pct": None,
                "review_success_pct": None,
                "repositories": [self._repo_link_to_dict(r) for r in repos],
                "teams": [self._team_to_dict(t, uow=uow) for t in teams],
                "members": [self._member_to_dict(m) for m in members],
                "repository_metrics": repo_metrics,
                "recent_activity": [],
            }

    def get_roles_catalog(self) -> dict[str, Any]:
        return {
            "roles": [
                {
                    "id": role.value,
                    "name": role.value.replace("_", " ").title(),
                    "permissions": sorted(p.value for p in permissions_for(role)),
                }
                for role in OrgRole
            ],
            "permissions": [p.value for p in Permission],
            "team_roles": [r.value for r in TeamRole],
        }

    def check_permission(
        self,
        organization_id: str,
        *,
        member_email: str,
        permission: str | Permission,
    ) -> bool:
        with UnitOfWork(self._session_factory) as uow:
            members = uow.organization_members.list_by_organization(organization_id)
            member = next(
                (
                    m
                    for m in members
                    if (m.email or "").lower() == member_email.strip().lower()
                ),
                None,
            )
            if member is None:
                return False
            try:
                role = OrgRole(member.role)
            except ValueError:
                return False
            return has_permission(role, permission)

    def resolve_acting_member(
        self, organization_id: str, *, email: str | None = None
    ) -> dict[str, Any] | None:
        with UnitOfWork(self._session_factory) as uow:
            members = uow.organization_members.list_by_organization(organization_id)
            if not members:
                return None
            if email:
                hit = next(
                    (
                        m
                        for m in members
                        if (m.email or "").lower() == email.strip().lower()
                    ),
                    None,
                )
                if hit is not None:
                    return self._member_to_dict(hit)
            owner = next(
                (m for m in members if m.role == OrgRole.OWNER.value), members[0]
            )
            return self._member_to_dict(owner)

    # ── Internal ──────────────────────────────────────────────────────────

    def _ensure_repo_linked(
        self, uow: UnitOfWork, organization_id: str, root: Path
    ) -> OrganizationRepositoryModel:
        resolved = str(root.resolve())
        existing = uow.organization_repositories.get_by_root(organization_id, resolved)
        if existing is not None:
            return existing
        return uow.organization_repositories.create(
            id=str(uuid4()),
            organization_id=organization_id,
            repository_root_path=resolved,
            repository_name=root.name,
            nickname=None,
            created_at=_utcnow(),
        )

    def _org_to_dict(
        self,
        org: OrganizationModel,
        *,
        include_counts: bool,
        uow: UnitOfWork,
    ) -> dict[str, Any]:
        branding = dict(org.branding or {})
        data: dict[str, Any] = {
            "id": org.id,
            "name": org.name,
            "slug": org.slug,
            "description": org.description or "",
            "is_default": bool(org.is_default),
            "branding": branding,
            "settings": branding,
            "metadata": {
                "slug": org.slug,
                "is_default": bool(org.is_default),
            },
            "created_at": org.created_at.isoformat() if org.created_at else None,
            "updated_at": org.updated_at.isoformat() if org.updated_at else None,
        }
        if include_counts:
            data["counts"] = {
                "teams": len(uow.teams.list_by_organization(org.id)),
                "members": len(
                    uow.organization_members.list_by_organization(org.id)
                ),
                "repositories": len(
                    uow.organization_repositories.list_by_organization(org.id)
                ),
            }
        return data

    def _team_to_dict(self, team: TeamModel, *, uow: UnitOfWork) -> dict[str, Any]:
        members = uow.team_members.list_by_team(team.id)
        repos = uow.team_repositories.list_by_team(team.id)
        admins = [
            m.member_id for m in members if m.role in (TeamRole.LEAD.value, "admin")
        ]
        return {
            "id": team.id,
            "organization_id": team.organization_id,
            "name": team.name,
            "slug": team.slug,
            "description": team.description or "",
            "member_ids": [m.member_id for m in members],
            "members": [
                {"member_id": m.member_id, "team_role": m.role} for m in members
            ],
            "admins": admins,
            "repository_ids": [r.organization_repository_id for r in repos],
            "created_at": team.created_at.isoformat() if team.created_at else None,
            "updated_at": team.updated_at.isoformat() if team.updated_at else None,
        }

    @staticmethod
    def _member_to_dict(member: OrganizationMemberModel) -> dict[str, Any]:
        try:
            role = OrgRole(member.role)
            perms = sorted(p.value for p in permissions_for(role))
        except ValueError:
            perms = []
        status = "active" if member.is_active else "invited"
        return {
            "id": member.id,
            "organization_id": member.organization_id,
            "email": member.email or "",
            "display_name": member.display_name,
            "role": member.role,
            "status": status,
            "is_active": bool(member.is_active),
            "permissions": perms,
            "created_at": member.created_at.isoformat() if member.created_at else None,
            "updated_at": member.updated_at.isoformat() if member.updated_at else None,
        }

    @staticmethod
    def _repo_link_to_dict(link: OrganizationRepositoryModel) -> dict[str, Any]:
        return {
            "id": link.id,
            "organization_id": link.organization_id,
            "repository_root_path": link.repository_root_path,
            "repository_name": link.repository_name or Path(link.repository_root_path).name,
            "nickname": link.nickname,
            "description": link.nickname or "",
            "is_active": True,
            "created_at": link.created_at.isoformat() if link.created_at else None,
            "updated_at": None,
        }
