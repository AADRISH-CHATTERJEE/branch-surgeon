"""Organization rules must execute in CompanyRulesChecker / POST /rules/check."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine

from refactory.company.checker import CompanyRulesChecker
from refactory.company.models import GateOutcome
from refactory.db.base import Base
from refactory.db.models import RepositoryModel
from refactory.db.session import SessionFactory
from refactory.organization.service import OrganizationRuleService
from refactory.rules.engine import RuleContext, RuleEngine
from refactory.rules.models import Rule, RuleCategory, RuleCondition, RuleSeverity


@pytest.fixture()
def org_db(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'org_exec.db'}")
    Base.metadata.create_all(engine)
    factory = SessionFactory(engine)
    root = tmp_path.resolve()
    (root / "auth.py").write_text("# TODO: remove before merge\n", encoding="utf-8")
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
    return {"tmp_path": root, "svc": svc}


def test_custom_content_todo_rule_warns(org_db):
    svc: OrganizationRuleService = org_db["svc"]
    svc.create_rule(
        {
            "name": "No TODO comments in production",
            "rule_type": "custom",
            "category": "custom",
            "severity": "warning",
            "blocking": False,
            "enabled": True,
            "conditions": [
                {"field": "content", "operator": "matches", "pattern": "TODO"},
            ],
            "message": "TODO comments are not allowed",
        }
    )
    checker = CompanyRulesChecker(
        logger=MagicMock(),
        rule_engine=RuleEngine(logger=MagicMock()),
        organization_rule_service=svc,
    )
    gate = checker.check(
        org_db["tmp_path"], branch_name="feature/login", commit_message="feat: x"
    )
    assert gate.outcome == GateOutcome.WARN
    assert any(v.source == "organization" for v in gate.violations)


def test_custom_content_todo_engine_direct():
    engine = RuleEngine(logger=MagicMock())
    engine.add_rule(
        Rule(
            name="No TODO",
            category=RuleCategory.CUSTOM,
            severity=RuleSeverity.WARNING,
            source="organization",
            conditions=[
                RuleCondition(field="content", operator="matches", pattern="TODO"),
            ],
            message="TODO found",
        )
    )
    hit = engine.evaluate(
        RuleContext(
            {
                "file_contents": {"auth.py": "# TODO remove\n"},
                "content": "# TODO remove\n",
            }
        )
    )
    assert hit.rules_failed == 1
    assert hit.violations[0].source == "organization"

    miss = engine.evaluate(
        RuleContext(
            {"file_contents": {"auth.py": "print('ok')\n"}, "content": "print('ok')\n"}
        )
    )
    assert miss.rules_failed == 0


def test_branch_naming_feature_pattern_pass_and_fail(org_db):
    svc: OrganizationRuleService = org_db["svc"]
    svc.create_rule(
        {
            "name": "Feature branches only",
            "rule_type": "branch_naming",
            "category": "branch_naming",
            "severity": "blocker",
            "blocking": True,
            "enabled": True,
            "conditions": [
                {
                    "field": "branch_name",
                    "operator": "matches",
                    "pattern": r"^feature/.+",
                }
            ],
            "message": "Branch must match feature/*",
        }
    )
    checker = CompanyRulesChecker(
        logger=MagicMock(),
        rule_engine=RuleEngine(logger=MagicMock()),
        organization_rule_service=svc,
    )
    ok = checker.check(
        org_db["tmp_path"], branch_name="feature/login", commit_message="feat: x"
    )
    assert not any(v.source == "organization" and v.blocking for v in ok.violations)

    bad = checker.check(org_db["tmp_path"], branch_name="login", commit_message="feat: x")
    assert any(v.source == "organization" and v.blocking for v in bad.violations)
    assert bad.outcome == GateOutcome.BLOCK


def test_disabled_org_rule_ignored(org_db):
    svc: OrganizationRuleService = org_db["svc"]
    created = svc.create_rule(
        {
            "name": "Disabled TODO",
            "rule_type": "custom",
            "category": "custom",
            "severity": "warning",
            "enabled": True,
            "conditions": [
                {"field": "content", "operator": "matches", "pattern": "TODO"},
            ],
            "message": "TODO",
        }
    )
    svc.set_enabled(created["id"], False)
    checker = CompanyRulesChecker(
        logger=MagicMock(),
        rule_engine=RuleEngine(logger=MagicMock()),
        organization_rule_service=svc,
    )
    gate = checker.check(
        org_db["tmp_path"], branch_name="feature/x", commit_message="feat: x"
    )
    assert not any(v.rule == "Disabled TODO" for v in gate.violations)


def test_rules_check_api_includes_org_content_rule(org_db):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from refactory.api.app import create_app
    from refactory.api.deps import clear_container_cache, get_container, resolve_repo_root

    svc: OrganizationRuleService = org_db["svc"]
    svc.create_rule(
        {
            "name": "No TODO comments in production",
            "rule_type": "custom",
            "enabled": True,
            "severity": "warning",
            "conditions": [
                {"field": "content", "operator": "matches", "pattern": "TODO"},
            ],
            "message": "TODO comments are not allowed",
        }
    )

    checker = CompanyRulesChecker(
        logger=MagicMock(),
        rule_engine=RuleEngine(logger=MagicMock()),
        organization_rule_service=svc,
    )

    container = MagicMock()
    container.git_service.get_root_path.return_value = str(org_db["tmp_path"])
    container.git_service.get_current_branch.return_value = "feature/login"
    container.git_service.get_default_branch.return_value = "main"
    container.git_service.get_head_sha.return_value = "abc"
    container.git_service.get_repository_metadata.return_value = MagicMock(
        name="demo",
        current_branch="feature/login",
        default_branch="main",
        head_sha="abc",
    )
    container.git_service.get_commits_since_ref.return_value = []
    container.git_service.get_changed_files_vs_ref.return_value = []
    container.git_service.get_changed_files_vs_default_branch.return_value = []
    container.company_rules_checker = checker
    container.query_service.get_repository_by_root.return_value = None
    container.persistence_service = MagicMock()

    clear_container_cache()
    app = create_app()
    app.dependency_overrides[get_container] = lambda: container
    app.dependency_overrides[resolve_repo_root] = lambda: org_db["tmp_path"].resolve()
    try:
        with TestClient(app) as client:
            resp = client.post("/rules/check", json={})
    finally:
        app.dependency_overrides.clear()
        clear_container_cache()

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert any(
        v.get("source") == "organization" for v in body.get("violations") or []
    ), body
    assert body["outcome"] == "warn"
