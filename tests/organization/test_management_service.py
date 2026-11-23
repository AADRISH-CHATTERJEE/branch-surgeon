"""Phase 11.5 — organization management service (local, no auth)."""

from __future__ import annotations

from pathlib import Path

import pytest

from refactory.db.database import DatabaseManager
from refactory.db.session import SessionFactory
from refactory.organization.management_service import OrganizationManagementService
from refactory.organization.roles import OrgRole, Permission, has_permission


@pytest.fixture()
def org_service(tmp_path: Path) -> OrganizationManagementService:
    db_url = f"sqlite:///{tmp_path / 'catalog.db'}"
    manager = DatabaseManager(database_url=db_url)
    manager.create_all()
    return OrganizationManagementService(SessionFactory(manager.engine))


def test_ensure_defaults_seeds_org_teams_and_repo(
    org_service: OrganizationManagementService, tmp_path: Path
) -> None:
    repo = tmp_path / "demo-repo"
    repo.mkdir()
    org = org_service.ensure_defaults(local_repo_root=repo)
    assert org["slug"] == "default"
    assert org["is_default"] is True
    teams = org_service.list_teams(org["id"])
    assert len(teams) >= 3
    repos = org_service.list_repositories(org["id"])
    assert any(Path(r["repository_root_path"]).resolve() == repo.resolve() for r in repos)


def test_invite_member_and_rbac(org_service: OrganizationManagementService) -> None:
    org = org_service.ensure_defaults()
    member = org_service.invite_member(
        org["id"],
        email="reviewer@acme.local",
        role=OrgRole.REVIEWER.value,
    )
    assert member["status"] == "invited"
    assert has_permission(OrgRole.REVIEWER, Permission.APPROVE_PATCH)
    assert org_service.check_permission(
        org["id"],
        member_email="local@refactory.dev",
        permission=Permission.MANAGE_ORGANIZATION,
    )


def test_create_team_and_link_repo(
    org_service: OrganizationManagementService, tmp_path: Path
) -> None:
    org = org_service.ensure_defaults()
    team = org_service.create_team(org["id"], name="DevOps Team", slug="devops")
    link = org_service.add_repository(
        org["id"],
        root_path=str(tmp_path / "infra"),
        name="infra",
        team_ids=[team["id"]],
    )
    (tmp_path / "infra").mkdir(exist_ok=True)
    refreshed = org_service.get_team(team["id"])
    assert refreshed is not None
    assert link["id"] in (refreshed.get("repository_ids") or [])


def test_rule_precedence_helpers() -> None:
    assert has_permission(OrgRole.VIEWER, Permission.VIEW_ANALYTICS)
    assert not has_permission(OrgRole.VIEWER, Permission.APPLY_PATCH)
    assert has_permission(OrgRole.OWNER, Permission.MANAGE_ORGANIZATION)
