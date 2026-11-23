"""Organization admin actions write a single Activity→History audit entry."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from refactory.api.app import create_app
from refactory.api.deps import clear_container_cache, get_container
from refactory.core.container import build_container
from refactory.history.types import resolve_analysis_type
from refactory.organization.admin_audit import record_admin_audit
from refactory.organization.roles import OrgRole


def test_admin_commands_map_to_organization_admin():
    for command in (
        "organization-created",
        "organization-updated",
        "organization-deleted",
        "team-created",
        "team-updated",
        "team-deleted",
        "member-invited",
        "member-updated",
        "member-removed",
        "organization-repository-linked",
        "organization-repository-unlinked",
        "team-repository-assigned",
        "team-repository-unassigned",
    ):
        assert resolve_analysis_type(command=command) == "organization_admin"
    assert (
        resolve_analysis_type(result_type="organization_admin") == "organization_admin"
    )
    assert resolve_analysis_type(command="organization-rule-created") == "organization_rule"


def test_record_admin_audit_single_persist_call():
    persistence = MagicMock()
    persistence.persist_analysis_run.return_value = {"id": "run-1"}
    git = MagicMock()
    git.get_root_path.return_value = "C:/repo"
    query = MagicMock()
    query.get_repository_by_root.return_value = {"id": "repo-1"}
    container = MagicMock(
        persistence_service=persistence,
        git_service=git,
        query_service=query,
    )

    record_admin_audit(
        container,
        command="team-created",
        organization_id="org-1",
        summary="Created team 'Platform'",
        result_data={"entity": "team", "team": {"id": "t1", "name": "Platform"}},
        actor_email="owner@acme.local",
    )

    persistence.persist_analysis_run.assert_called_once()
    kwargs = persistence.persist_analysis_run.call_args.kwargs
    assert kwargs["command"] == "team-created"
    assert kwargs["result_type"] == "organization_admin"
    assert kwargs["organization_id"] == "org-1"
    assert kwargs["created_by_user"] == "owner@acme.local"
    assert kwargs["repository_id"] == "repo-1"
    assert "Platform" in kwargs["summary"]


@pytest.fixture()
def org_api_client(tmp_path: Path):
    """Real container against an isolated git repo for admin audit E2E."""
    import os
    import subprocess

    clear_container_cache()
    repo = tmp_path / "demo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@refactory.dev",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@refactory.dev",
        }
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )

    container = build_container(repo_root=repo)
    # Ensure analysis DB has a repository row for the active root.
    container.persistence_service.get_or_create_repository(
        name=repo.name, root_path=str(repo.resolve())
    )
    app = create_app()
    app.dependency_overrides[get_container] = lambda: container
    headers = {"X-Repo-Root": str(repo.resolve())}
    with TestClient(app) as client:
        yield client, container, headers
    app.dependency_overrides.clear()
    clear_container_cache()


def test_create_team_writes_history(org_api_client):
    client, container, headers = org_api_client
    orgs = client.get("/organizations", headers=headers).json()["data"]
    assert orgs, "expected default organization from ensure_defaults"
    org_id = orgs[0]["id"]

    before = container.analysis_history_service.list_history(limit=200)
    before_ids = {r["id"] for r in before}

    resp = client.post(
        f"/organizations/{org_id}/teams",
        json={"name": "Platform Audit", "slug": "platform-audit"},
        headers={**headers, "X-Member-Email": "owner@acme.local"},
    )
    assert resp.status_code == 200, resp.text

    after = container.analysis_history_service.list_history(limit=200)
    new_rows = [r for r in after if r["id"] not in before_ids]
    admin_rows = [r for r in new_rows if r["analysis_type"] == "organization_admin"]
    assert len(admin_rows) == 1
    assert "Platform Audit" in (admin_rows[0].get("summary") or "")
    assert admin_rows[0].get("organization_id") == org_id
    assert admin_rows[0].get("deep_link", {}).get("href", "").startswith("/organization")


def test_invite_and_role_update_write_history(org_api_client):
    import uuid

    client, container, headers = org_api_client
    suffix = uuid.uuid4().hex[:8]
    created = client.post(
        "/organizations",
        json={"name": f"Audit Org {suffix}", "slug": f"audit-org-{suffix}"},
        headers={**headers, "X-Member-Email": "owner@acme.local"},
    )
    assert created.status_code == 200, created.text
    org_id = created.json()["data"]["id"]
    email = f"reviewer-{suffix}@acme.local"

    invite = client.post(
        f"/organizations/{org_id}/members",
        json={
            "email": email,
            "role": OrgRole.REVIEWER.value,
            "display_name": "Reviewer",
        },
        headers={**headers, "X-Member-Email": "owner@acme.local"},
    )
    assert invite.status_code == 200, invite.text
    member_id = invite.json()["data"]["id"]

    update = client.patch(
        f"/organizations/{org_id}/members/{member_id}",
        json={"role": OrgRole.ADMIN.value},
        headers={**headers, "X-Member-Email": "owner@acme.local"},
    )
    assert update.status_code == 200, update.text

    actions = {
        (r.get("result_data") or {}).get("action")
        for r in container.analysis_history_service.list_history(limit=200)
        if r.get("analysis_type") == "organization_admin"
        and r.get("organization_id") == org_id
    }
    assert "organization-created" in actions
    assert "member-invited" in actions
    assert "member-updated" in actions
