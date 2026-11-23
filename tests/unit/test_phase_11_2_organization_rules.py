"""Phase 11.2 — Organization rules engine (CRUD, evaluation, merge)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine

from refactory.company.checker import CompanyRulesChecker
from refactory.db.base import Base
from refactory.db.models import OrganizationRuleModel, RepositoryModel
from refactory.db.session import SessionFactory
from refactory.organization.service import OrganizationRuleService
from refactory.rules.engine import RuleContext, RuleEngine
from refactory.rules.models import Rule, RuleCategory, RuleCondition, RuleSeverity


@pytest.fixture()
def db_env(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'org_rules.db'}")
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
    return {"tmp_path": root, "factory": factory, "svc": svc}


def test_ensure_defaults_seeds_examples(db_env):
    n = db_env["svc"].ensure_defaults()
    assert n >= 1
    rows = db_env["svc"].list_rules()
    assert len(rows) >= 1
    assert all(r["source"] == "organization" for r in rows)
    # Idempotent
    assert db_env["svc"].ensure_defaults() == 0


def test_crud_and_audit(db_env):
    svc: OrganizationRuleService = db_env["svc"]
    created = svc.create_rule(
        {
            "name": "No secrets",
            "rule_type": "security",
            "severity": "blocker",
            "message": "No keys",
            "conditions": [
                {"field": "content", "operator": "matches", "pattern": r"API_KEY\s*="}
            ],
        }
    )
    assert created["id"]
    assert created["blocking"] is True
    assert "blocking" in created

    updated = svc.update_rule(created["id"], {**created, "message": "Updated msg"})
    assert updated and updated["message"] == "Updated msg"
    assert "blocking" in updated
    assert updated["blocking"] is True

    disabled = svc.set_enabled(created["id"], False)
    assert disabled and disabled["enabled"] is False

    dup = svc.duplicate_rule(created["id"])
    assert dup and "(copy)" in dup["name"]

    audits = svc.list_audit(created["id"])
    assert any(a["action"] == "created" for a in audits)
    assert any(a["action"] == "updated" for a in audits)

    assert svc.delete_rule(created["id"]) is True
    assert svc.get_rule(created["id"]) is None


def test_list_rules_includes_blocking_true_and_false(db_env):
    """Rules page DTO must always expose persisted blocking for every row."""
    svc: OrganizationRuleService = db_env["svc"]
    blocking_rule = svc.create_rule(
        {
            "name": "Blocking list probe",
            "rule_type": "custom",
            "severity": "error",
            "blocking": True,
            "message": "block me",
            "conditions": [
                {"field": "branch_name", "operator": "matches", "pattern": r"^x$"}
            ],
        }
    )
    advisory_rule = svc.create_rule(
        {
            "name": "Advisory list probe",
            "rule_type": "custom",
            "severity": "warning",
            "blocking": False,
            "message": "warn me",
            "conditions": [
                {"field": "branch_name", "operator": "matches", "pattern": r"^y$"}
            ],
        }
    )
    assert blocking_rule["blocking"] is True
    assert advisory_rule["blocking"] is False

    rows = {r["name"]: r for r in svc.list_rules()}
    assert "blocking" in rows["Blocking list probe"]
    assert rows["Blocking list probe"]["blocking"] is True
    assert "blocking" in rows["Advisory list probe"]
    assert rows["Advisory list probe"]["blocking"] is False

    # Update flips must persist and round-trip through list/get.
    flipped = svc.update_rule(
        advisory_rule["id"], {**advisory_rule, "blocking": True}
    )
    assert flipped and flipped["blocking"] is True
    assert svc.get_rule(advisory_rule["id"])["blocking"] is True
    listed = {r["id"]: r for r in svc.list_rules()}
    assert listed[advisory_rule["id"]]["blocking"] is True


def test_import_export(db_env):
    svc: OrganizationRuleService = db_env["svc"]
    svc.create_rule({"name": "A", "rule_type": "custom", "severity": "info"})
    exported = svc.export_rules()
    assert exported["type"] == "refactory.organization_rules"
    assert exported["rules"]

    result = svc.import_rules(
        {
            "rules": [
                {
                    "name": "Imported",
                    "rule_type": "branch_naming",
                    "severity": "warning",
                    "conditions": [
                        {
                            "field": "branch_name",
                            "operator": "matches",
                            "pattern": r"^feature/.+",
                        }
                    ],
                }
            ]
        }
    )
    assert result["created"] >= 1
    names = {r["name"] for r in svc.list_rules()}
    assert "Imported" in names


def test_org_rules_merge_with_builtin_engine(db_env):
    svc: OrganizationRuleService = db_env["svc"]
    svc.create_rule(
        {
            "name": "Feature branches only",
            "rule_type": "branch_naming",
            "category": "branch_naming",
            "severity": "error",
            "blocking": True,
            "conditions": [
                {
                    "field": "branch_name",
                    "operator": "matches",
                    "pattern": r"^feature/.+",
                }
            ],
            "message": "Use feature/* branches",
        }
    )
    engine = RuleEngine(logger=MagicMock())
    engine.add_rules(svc.enabled_as_rules())
    engine.add_rule(
        Rule(
            name="builtin-commit",
            category=RuleCategory.COMMIT_MESSAGE,
            severity=RuleSeverity.WARNING,
            conditions=[
                RuleCondition(
                    field="commit_message",
                    operator="matches",
                    pattern=r"^feat:",
                )
            ],
            message="Prefer feat:",
            source="builtin",
        )
    )
    result = engine.evaluate(
        RuleContext(
            {
                "branch_name": "main",
                "commit_message": "stuff",
                "changed_files": [],
            }
        )
    )
    sources = {v.source for v in result.violations}
    assert "organization" in sources
    assert "builtin" in sources


def test_company_checker_includes_organization_rules(db_env):
    svc: OrganizationRuleService = db_env["svc"]
    svc.create_rule(
        {
            "name": "Branch policy",
            "rule_type": "branch_naming",
            "category": "branch_naming",
            "severity": "blocker",
            "blocking": True,
            "conditions": [
                {
                    "field": "branch_name",
                    "operator": "matches",
                    "pattern": r"^feature/.+",
                }
            ],
            "message": "Invalid branch",
        }
    )
    checker = CompanyRulesChecker(
        logger=MagicMock(),
        rule_engine=RuleEngine(logger=MagicMock()),
        organization_rule_service=svc,
    )
    gate = checker.check(db_env["tmp_path"], branch_name="main", commit_message="feat: x")
    assert any(v.source == "organization" and v.blocking for v in gate.violations)


def test_condition_operators(db_env):
    engine = RuleEngine(logger=MagicMock())
    engine.add_rule(
        Rule(
            name="starts",
            category=RuleCategory.CUSTOM,
            conditions=[
                RuleCondition(field="branch_name", operator="starts_with", value="feat")
            ],
            message="must start with feat",
        )
    )
    ok = engine.evaluate(RuleContext({"branch_name": "feature/x"}))
    assert ok.rules_failed == 0
    bad = engine.evaluate(RuleContext({"branch_name": "bugfix/x"}))
    assert bad.rules_failed == 1


def test_organization_rules_table_exists():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    assert "organization_rules" in Base.metadata.tables
    assert OrganizationRuleModel.__tablename__ == "organization_rules"
