"""Apply-patch architecture: services, repositories, rollback, conflicts, org rules."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine

from refactory.ai.models import AIResponse
from refactory.db.base import Base
from refactory.db.models import RecommendationModel, RepositoryModel
from refactory.db.persistence import PersistenceService
from refactory.db.query_service import RepositoryQueryService
from refactory.db.session import SessionFactory
from refactory.db.uow import UnitOfWork
from refactory.organization.defaults import DEFAULT_ORGANIZATION_RULES
from refactory.organization.service import OrganizationRuleService
from refactory.prompts import PromptTemplateService
from refactory.recommendation.models import RecommendationStatus
from refactory.recommendation.patch_apply_service import PatchService
from refactory.recommendation.patch_models import PatchConflictError
from refactory.recommendation.patch_service import RecommendationPatchService
from refactory.recommendation.recommendation_service import RecommendationService
from refactory.rules.engine import RuleContext, RuleEngine
from refactory.rules.models import Rule, RuleCategory, RuleCondition, RuleSeverity


@pytest.fixture()
def env(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'apply_arch.db'}")
    Base.metadata.create_all(engine)
    factory = SessionFactory(engine)
    persistence = PersistenceService(factory)
    query = RepositoryQueryService(factory)
    root = tmp_path.resolve()
    (root / "app.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    session = factory()
    try:
        session.add(RepositoryModel(id="repo1", name="demo", root_path=str(root)))
        session.add(
            RecommendationModel(
                id="rec1",
                repository_id="repo1",
                type="technical_debt",
                priority="high",
                status="pending",
                title="Simplify hello",
                description="Refactor app.py",
            )
        )
        session.commit()
    finally:
        session.close()

    git = MagicMock()
    git.get_root_path.return_value = root / ".other"
    git.get_head_sha.return_value = "deadbeef"
    git.has_unmerged_paths.return_value = False

    patch_service = PatchService(
        logger=MagicMock(),
        git_service=git,
        query_service=query,
        persistence_service=persistence,
    )
    rec_service = RecommendationService(
        logger=MagicMock(),
        git_service=git,
        query_service=query,
        persistence_service=persistence,
        patch_service=patch_service,
    )
    return {
        "root": root,
        "factory": factory,
        "persistence": persistence,
        "query": query,
        "git": git,
        "patch_service": patch_service,
        "rec_service": rec_service,
    }


def _seed_patch(env, *, modified: str | None = None) -> str:
    body = modified or 'def hello():\n    """doc."""\n    return 1\n'
    ai = MagicMock()
    ai.generate.return_value = AIResponse(
        text=json.dumps(
            {
                "explanation": "doc",
                "confidence": 0.9,
                "patches": [{"file_path": "app.py", "modified": body}],
            }
        ),
        provider="mock",
        model="m",
    )
    gen = RecommendationPatchService(
        logger=MagicMock(),
        ai_gateway=ai,
        prompt_service=PromptTemplateService(),
        query_service=env["query"],
        persistence_service=env["persistence"],
        recommendation_service=env["rec_service"],
    )
    return gen.generate_for_recommendation("rec1", env["root"]).id


def test_architecture_layer_evaluator_no_false_positive_on_empty_imports():
    engine = RuleEngine(logger=MagicMock())
    engine.add_rule(
        Rule(
            name="Controllers cannot call repositories",
            category=RuleCategory.ARCHITECTURE_LAYER,
            severity=RuleSeverity.ERROR,
            blocking=True,
            message="Controllers must not import repositories",
            conditions=[
                RuleCondition(
                    field="imports",
                    operator="matches",
                    pattern=r"controllers?.+repositories?",
                )
            ],
        )
    )
    # Empty context — must pass (not violate)
    result = engine.evaluate(RuleContext({"imports": [], "file_contents": {}}))
    assert result.passed is True
    assert result.blocking_violations == 0

    # Real violation
    result2 = engine.evaluate(
        RuleContext(
            {
                "imports": [],
                "file_contents": {
                    "api/controllers/user.py": (
                        "from app.repositories.user import UserRepo\n"
                    )
                },
            }
        )
    )
    assert result2.passed is False
    assert result2.blocking_violations >= 1


def test_org_defaults_do_not_block_clean_patch_apply(env):
    """Seeded architecture rule must not false-positive during apply."""
    org = OrganizationRuleService(
        logger=MagicMock(),
        session_factory=env["factory"],
        rule_engine=RuleEngine(logger=MagicMock()),
    )
    org.ensure_defaults()
    assert any(r["name"] == "Controllers cannot call repositories" for r in org.list_rules())

    from refactory.company.checker import CompanyRulesChecker

    checker = CompanyRulesChecker(
        logger=MagicMock(),
        rule_engine=RuleEngine(logger=MagicMock()),
        organization_rule_service=org,
    )
    env["patch_service"]._company_rules = checker

    patch_id = _seed_patch(env)
    result = env["rec_service"].apply_patch("rec1", patch_id=patch_id, repo_root=env["root"])
    assert result.applied is True
    assert result.recommendation_status == RecommendationStatus.APPLIED.value


def test_recommendation_service_apply_marks_status(env):
    patch_id = _seed_patch(env)
    result = env["rec_service"].apply_patch("rec1", patch_id=patch_id, repo_root=env["root"])
    assert result.applied is True
    assert result.git_commit == "deadbeef"
    rec = env["query"].get_recommendation("rec1")
    assert rec["status"] == "applied"
    patch = env["persistence"].get_recommendation_patch(patch_id)
    assert patch["status"] == "applied"
    assert patch["applied_by"] == "local"
    assert patch["git_commit"] == "deadbeef"


def test_patch_repository_mark_applied(env):
    patch_id = _seed_patch(env)
    from datetime import datetime, timezone

    with UnitOfWork(env["factory"]) as uow:
        row = uow.patches.mark_applied(
            patch_id,
            applied_by="tester",
            git_commit="abc",
            applied_at=datetime.now(timezone.utc),
        )
        assert row is not None
        assert row.status == "applied"
        assert row.applied_by == "tester"


def test_dry_run_does_not_write(env):
    patch_id = _seed_patch(env)
    original = (env["root"] / "app.py").read_text(encoding="utf-8")
    result = env["rec_service"].apply_patch(
        "rec1", patch_id=patch_id, dry_run=True, repo_root=env["root"]
    )
    assert result.status == "dry_run"
    assert result.applied is False
    assert (env["root"] / "app.py").read_text(encoding="utf-8") == original
    rec = env["query"].get_recommendation("rec1")
    assert rec["status"] == "pending"


def test_conflict_detection(env):
    patch_id = _seed_patch(env)
    (env["root"] / "app.py").write_text("def hello():\n    return 9\n", encoding="utf-8")
    with pytest.raises(PatchConflictError):
        env["rec_service"].apply_patch("rec1", patch_id=patch_id, repo_root=env["root"])


def test_rollback_restores_originals(env):
    patch_id = _seed_patch(env)
    original = "def hello():\n    return 1\n"
    env["rec_service"].apply_patch("rec1", patch_id=patch_id, repo_root=env["root"])
    assert '"""doc."""' in (env["root"] / "app.py").read_text(encoding="utf-8")

    result = env["rec_service"].rollback_patch(
        "rec1", patch_id=patch_id, repo_root=env["root"]
    )
    assert result.status == "rolled_back"
    assert (env["root"] / "app.py").read_text(encoding="utf-8") == original
    rec = env["query"].get_recommendation("rec1")
    assert rec["status"] == "rolled_back"
    patch = env["persistence"].get_recommendation_patch(patch_id)
    assert patch["status"] == "rolled_back"
    assert patch["rollback_metadata"]


def test_org_policy_blocks_real_architecture_violation(env):
    from refactory.company.checker import CompanyRulesChecker

    org = OrganizationRuleService(
        logger=MagicMock(),
        session_factory=env["factory"],
        rule_engine=RuleEngine(logger=MagicMock()),
    )
    # Only seed the architecture rule
    arch = next(
        r for r in DEFAULT_ORGANIZATION_RULES if r["name"] == "Controllers cannot call repositories"
    )
    org.create_rule(arch)

    checker = CompanyRulesChecker(
        logger=MagicMock(),
        rule_engine=RuleEngine(logger=MagicMock()),
        organization_rule_service=org,
    )
    env["patch_service"]._company_rules = checker

    ctrl = env["root"] / "api" / "controllers"
    ctrl.mkdir(parents=True)
    original = "x = 1\n"
    (ctrl / "user.py").write_text(original, encoding="utf-8")
    bad = "from app.repositories.user import UserRepo\nx = 1\n"
    patch_id = env["persistence"].persist_recommendation_patch(
        repository_id="repo1",
        recommendation_id="rec1",
        payload={
            "explanation": "bad arch",
            "confidence": 0.5,
            "changed_files": ["api/controllers/user.py"],
            "unified_diff": "",
            "patches": [
                {
                    "file_path": "api/controllers/user.py",
                    "original": original,
                    "modified": bad,
                }
            ],
        },
    )
    from refactory.recommendation.patch_models import PatchApplyError

    with pytest.raises(PatchApplyError) as exc:
        env["rec_service"].apply_patch("rec1", patch_id=patch_id, repo_root=env["root"])
    assert "organization policy" in exc.value.message.lower()
    assert "Controllers" in exc.value.message
