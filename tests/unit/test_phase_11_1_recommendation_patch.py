"""Phase 11.1 — AI patch generation for recommendations."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine

from refactory.ai.models import AIResponse
from refactory.db.base import Base
from refactory.db.models import PatchModel, RecommendationModel, RepositoryModel
from refactory.db.persistence import PersistenceService
from refactory.db.query_service import RepositoryQueryService
from refactory.db.session import SessionFactory
from refactory.recommendation.patch_models import PatchGenerationError
from refactory.recommendation.patch_service import RecommendationPatchService
from refactory.prompts import PromptTemplateService


@pytest.fixture()
def db_env(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'patch.db'}")
    Base.metadata.create_all(engine)
    factory = SessionFactory(engine)
    persistence = PersistenceService(factory)
    query = RepositoryQueryService(factory)
    # seed repo + recommendation + source file
    root = tmp_path.resolve()
    src = root / "app.py"
    src.write_text("def hello():\n    return 1\n", encoding="utf-8")
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
                description="Refactor app.py to improve clarity",
            )
        )
        session.commit()
    finally:
        session.close()
    return {
        "tmp_path": root,
        "persistence": persistence,
        "query": query,
        "factory": factory,
    }


def _service(db_env, response_payload: dict) -> RecommendationPatchService:
    ai = MagicMock()
    ai.generate.return_value = AIResponse(
        text=json.dumps(response_payload),
        provider="mock",
        model="test-model",
    )
    return RecommendationPatchService(
        logger=MagicMock(),
        ai_gateway=ai,
        prompt_service=PromptTemplateService(),
        query_service=db_env["query"],
        persistence_service=db_env["persistence"],
    )


def test_generate_patch_persists_and_returns_unified_diff(db_env):
    modified = "def hello():\n    \"\"\"Return one.\"\"\"\n    return 1\n"
    svc = _service(
        db_env,
        {
            "explanation": "Add a docstring for clarity.",
            "confidence": 0.81,
            "patches": [{"file_path": "app.py", "modified": modified}],
        },
    )
    result = svc.generate_for_recommendation("rec1", db_env["tmp_path"])
    assert result.recommendation_id == "rec1"
    assert result.id
    assert result.apply_available is True
    assert "app.py" in result.changed_files
    assert result.unified_diff.strip()
    assert "+++" in result.unified_diff or "@@" in result.unified_diff
    assert result.patches[0].original.startswith("def hello")
    assert '"""Return one."""' in result.patches[0].modified
    assert result.model == "test-model"

    listed = svc.list_patches("rec1")
    assert len(listed) == 1
    assert listed[0]["id"] == result.id
    assert listed[0]["unified_diff"]


def test_generate_patch_missing_recommendation(db_env):
    svc = _service(
        db_env,
        {"explanation": "x", "confidence": 0.5, "patches": []},
    )
    with pytest.raises(PatchGenerationError, match="not found"):
        svc.generate_for_recommendation("missing", db_env["tmp_path"])


def test_generate_patch_empty_model_patches(db_env):
    svc = _service(
        db_env,
        {"explanation": "noop", "confidence": 0.5, "patches": []},
    )
    with pytest.raises(PatchGenerationError, match="Unable to generate patch"):
        svc.generate_for_recommendation("rec1", db_env["tmp_path"])


def test_patch_table_created():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    assert "db_patches" in Base.metadata.tables
    assert PatchModel.__tablename__ == "db_patches"


def test_resolve_no_eval_via_content_scan(db_env):
    """Rule violations without affected_files still resolve via content scan."""
    # Seed a file that contains eval()
    eval_file = db_env["tmp_path"] / "bad.py"
    eval_file.write_text("x = eval('1')\n", encoding="utf-8")
    svc = _service(
        db_env,
        {
            "explanation": "Remove eval",
            "confidence": 0.9,
            "patches": [
                {
                    "file_path": "bad.py",
                    "modified": "x = 1\n",
                }
            ],
        },
    )
    # Point recommendation at no-eval without path in description
    session = db_env["factory"]()
    try:
        from refactory.db.models import RecommendationModel

        session.add(
            RecommendationModel(
                id="rec-eval",
                repository_id="repo1",
                type="rule_violations",
                priority="medium",
                status="pending",
                title="Rule violation: no-eval",
                description="Do not use eval() — it allows arbitrary code execution.",
            )
        )
        session.commit()
    finally:
        session.close()

    result = svc.generate_for_recommendation("rec-eval", db_env["tmp_path"])
    assert result.changed_files == ["bad.py"]
    assert "eval" not in result.patches[0].modified


def test_security_policy_attaches_file_path():
    from refactory.rules.engine import RuleContext, RuleEngine
    from refactory.rules.models import Rule, RuleCategory, RuleCondition, RuleSeverity
    from refactory.core.logger import get_service_logger

    engine = RuleEngine(logger=get_service_logger("test.rules"))
    engine._rules = [
        Rule(
            name="no-eval",
            category=RuleCategory.SECURITY_POLICY,
            severity=RuleSeverity.ERROR,
            conditions=[
                RuleCondition(field="content", operator="matches", pattern=r"\beval\s*\(")
            ],
            message="Do not use eval()",
        )
    ]
    ctx = RuleContext(
        {
            "file_contents": {
                "ok.py": "print(1)\n",
                "bad.py": "eval('x')\n",
            }
        }
    )
    result = engine.evaluate(ctx)
    assert len(result.violations) == 1
    assert result.violations[0].file_path == "bad.py"
