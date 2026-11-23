"""API contract: organization rule list/get responses always include blocking."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine

from refactory.db.base import Base
from refactory.db.models import RepositoryModel
from refactory.db.session import SessionFactory
from refactory.organization.service import OrganizationRuleService
from refactory.rules.engine import RuleEngine


@pytest.fixture()
def org_api(tmp_path: Path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from refactory.api.app import create_app
    from refactory.api.deps import clear_container_cache, get_container, resolve_repo_root

    engine = create_engine(f"sqlite:///{tmp_path / 'org_rules_api.db'}")
    Base.metadata.create_all(engine)
    factory = SessionFactory(engine)
    root = tmp_path.resolve()
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    session = factory()
    try:
        session.add(RepositoryModel(id="repo1", name="demo", root_path=str(root)))
        session.commit()
    finally:
        session.close()

    svc = OrganizationRuleService(
        logger=MagicMock(),
        session_factory=factory,
        rule_engine=RuleEngine(logger=MagicMock()),
    )
    # Avoid seeding defaults so assertions stay tight.
    svc.ensure_defaults = lambda: 0  # type: ignore[method-assign]

    engine_mock = MagicMock()
    engine_mock.clear_rules = MagicMock()
    engine_mock.load_rules = MagicMock(return_value=0)
    engine_mock.rules = []

    container = MagicMock()
    container.git_service.get_root_path.return_value = str(root)
    container.organization_rule_service = svc
    container.rule_engine = engine_mock
    container.company_rules_checker = MagicMock()
    container.query_service.get_repository_by_root.return_value = {
        "id": "repo1",
        "name": "demo",
        "root_path": str(root),
    }
    container.persistence_service = MagicMock()

    clear_container_cache()
    app = create_app()
    app.dependency_overrides[get_container] = lambda: container
    app.dependency_overrides[resolve_repo_root] = lambda: root
    client = TestClient(app)
    try:
        yield {"client": client, "svc": svc, "root": root}
    finally:
        app.dependency_overrides.clear()
        clear_container_cache()


def test_organization_rules_list_returns_blocking_true_and_false(org_api):
    client = org_api["client"]
    svc: OrganizationRuleService = org_api["svc"]

    svc.create_rule(
        {
            "name": "Test Rule Verification",
            "rule_type": "custom",
            "severity": "error",
            "blocking": True,
            "enabled": True,
            "conditions": [
                {"field": "branch_name", "operator": "matches", "pattern": r"feature/.*"}
            ],
            "message": "updated verification rule",
        }
    )
    svc.create_rule(
        {
            "name": "Advisory Only",
            "rule_type": "custom",
            "severity": "warning",
            "blocking": False,
            "enabled": True,
            "conditions": [
                {"field": "branch_name", "operator": "matches", "pattern": r"^tmp/.+"}
            ],
            "message": "advisory",
        }
    )

    resp = client.get("/organization-rules")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    rows = {r["name"]: r for r in body["data"]}

    assert "blocking" in rows["Test Rule Verification"]
    assert rows["Test Rule Verification"]["blocking"] is True
    assert "blocking" in rows["Advisory Only"]
    assert rows["Advisory Only"]["blocking"] is False

    # Existing clients keep other familiar fields.
    sample = rows["Test Rule Verification"]
    for key in ("id", "name", "severity", "enabled", "rule_type", "conditions"):
        assert key in sample


def test_get_rules_catalog_includes_organization_blocking(org_api):
    client = org_api["client"]
    svc: OrganizationRuleService = org_api["svc"]
    svc.create_rule(
        {
            "name": "Catalog Blocking Rule",
            "rule_type": "custom",
            "severity": "error",
            "blocking": True,
            "conditions": [
                {"field": "branch_name", "operator": "matches", "pattern": r"^x$"}
            ],
        }
    )
    svc.create_rule(
        {
            "name": "Catalog Advisory Rule",
            "rule_type": "custom",
            "severity": "info",
            "blocking": False,
            "conditions": [
                {"field": "branch_name", "operator": "matches", "pattern": r"^y$"}
            ],
        }
    )

    resp = client.get("/rules")
    assert resp.status_code == 200
    data = resp.json()["data"]
    org_rows = {r["name"]: r for r in data.get("organization_rules") or []}
    assert org_rows["Catalog Blocking Rule"]["blocking"] is True
    assert org_rows["Catalog Advisory Rule"]["blocking"] is False


def test_create_and_update_persist_blocking(org_api):
    client = org_api["client"]

    created = client.post(
        "/organization-rules",
        json={
            "name": "Persist Blocking",
            "rule_type": "custom",
            "severity": "error",
            "blocking": True,
            "conditions": [
                {"field": "branch_name", "operator": "matches", "pattern": r"^z$"}
            ],
        },
    )
    assert created.status_code == 200
    created_body = created.json()["data"]
    assert created_body["blocking"] is True
    rule_id = created_body["id"]

    updated = client.put(
        f"/organization-rules/{rule_id}",
        json={
            "name": "Persist Blocking",
            "rule_type": "custom",
            "severity": "error",
            "blocking": False,
            "conditions": [
                {"field": "branch_name", "operator": "matches", "pattern": r"^z$"}
            ],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["blocking"] is False

    listed = client.get("/organization-rules").json()["data"]
    match = next(r for r in listed if r["id"] == rule_id)
    assert match["blocking"] is False
