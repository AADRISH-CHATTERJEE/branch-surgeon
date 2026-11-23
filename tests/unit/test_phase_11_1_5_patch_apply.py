"""Phase 11.1.5 — Apply stored AI patches with conflict / validation / reindex."""

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
from refactory.prompts import PromptTemplateService
from refactory.recommendation.patch_apply_service import PatchService
from refactory.recommendation.patch_models import PatchConflictError
from refactory.recommendation.patch_service import RecommendationPatchService
from refactory.recommendation.recommendation_service import RecommendationService


@pytest.fixture()
def db_env(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'apply.db'}")
    Base.metadata.create_all(engine)
    factory = SessionFactory(engine)
    persistence = PersistenceService(factory)
    query = RepositoryQueryService(factory)
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


def _generate_service(db_env, response_payload: dict) -> RecommendationPatchService:
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


def _apply_service(
    db_env,
    *,
    parser=None,
    indexer=None,
    graph=None,
    company_rules=None,
) -> RecommendationPatchService:
    git = MagicMock()
    # Distinct from test root so PatchService uses Path IO (not live git)
    git.get_root_path.return_value = db_env["tmp_path"] / ".not-git-root"
    git.get_head_sha.return_value = "abc123"
    git.has_unmerged_paths.return_value = False

    patch_service = PatchService(
        logger=MagicMock(),
        git_service=git,
        query_service=db_env["query"],
        persistence_service=db_env["persistence"],
        parser_service=parser,
        indexer_service=indexer,
        graph_service=graph,
        company_rules_checker=company_rules,
    )
    rec_service = RecommendationService(
        logger=MagicMock(),
        git_service=git,
        query_service=db_env["query"],
        persistence_service=db_env["persistence"],
        patch_service=patch_service,
    )
    return RecommendationPatchService(
        logger=MagicMock(),
        ai_gateway=MagicMock(),
        prompt_service=PromptTemplateService(),
        query_service=db_env["query"],
        persistence_service=db_env["persistence"],
        parser_service=parser,
        indexer_service=indexer,
        graph_service=graph,
        company_rules_checker=company_rules,
        recommendation_service=rec_service,
    )


def _seed_patch(db_env, *, modified: str | None = None) -> str:
    new_body = modified or (
        'def hello():\n    """Return one."""\n    return 1\n'
    )
    svc = _generate_service(
        db_env,
        {
            "explanation": "Add a docstring.",
            "confidence": 0.9,
            "patches": [{"file_path": "app.py", "modified": new_body}],
        },
    )
    result = svc.generate_for_recommendation("rec1", db_env["tmp_path"])
    assert result.id
    return result.id


def test_apply_patch_writes_file_successfully(db_env):
    patch_id = _seed_patch(db_env)
    indexer = MagicMock()
    indexer.build_index.return_value = MagicMock(name="index")
    graph = MagicMock()
    svc = _apply_service(db_env, indexer=indexer, graph=graph)

    result = svc.apply_patch(patch_id, db_env["tmp_path"])

    assert result.status == "applied"
    assert result.applied is True
    assert result.changed_files == ["app.py"]
    assert result.repository_updated is True
    assert result.index_updated is True
    assert result.graph_updated is True
    assert '"""Return one."""' in (db_env["tmp_path"] / "app.py").read_text(
        encoding="utf-8"
    )
    indexer.build_index.assert_called_once()
    graph.build_graph.assert_called_once()


def test_apply_patch_conflict_when_file_changed(db_env):
    patch_id = _seed_patch(db_env)
    # Simulate newer local edits after patch generation
    (db_env["tmp_path"] / "app.py").write_text(
        "def hello():\n    return 99\n", encoding="utf-8"
    )
    svc = _apply_service(db_env)

    with pytest.raises(PatchConflictError) as exc:
        svc.apply_patch(patch_id, db_env["tmp_path"])
    assert "app.py" in exc.value.files
    # Original newer content must remain
    assert "return 99" in (db_env["tmp_path"] / "app.py").read_text(encoding="utf-8")


def test_apply_patch_validation_rollback(db_env):
    # Seed a patch that would introduce syntax errors
    original = "def hello():\n    return 1\n"
    (db_env["tmp_path"] / "app.py").write_text(original, encoding="utf-8")
    bad_modified = "def hello(\n"
    patch_id = db_env["persistence"].persist_recommendation_patch(
        repository_id="repo1",
        recommendation_id="rec1",
        payload={
            "explanation": "broken",
            "confidence": 0.1,
            "changed_files": ["app.py"],
            "unified_diff": "--- a/app.py\n+++ b/app.py\n",
            "patches": [
                {
                    "file_path": "app.py",
                    "original": original,
                    "modified": bad_modified,
                }
            ],
            "prompt_version": "1.0.0",
            "model": "test",
            "provider": "mock",
        },
    )

    parser = MagicMock()
    parser.supported_extensions.return_value = {".py"}
    parsed = MagicMock()
    parsed.has_syntax_errors = True
    parsed.error_message = "syntax errors detected"
    parser.parse_file.return_value = parsed
    indexer = MagicMock()
    svc = _apply_service(db_env, parser=parser, indexer=indexer)

    result = svc.apply_patch(patch_id, db_env["tmp_path"])

    assert result.status == "failed"
    assert result.applied is False
    assert result.validation.ok is False
    assert result.validation.rolled_back is True
    assert (db_env["tmp_path"] / "app.py").read_text(encoding="utf-8") == original
    indexer.build_index.assert_not_called()


def test_apply_patch_refreshes_repository_index(db_env):
    patch_id = _seed_patch(db_env)
    indexer = MagicMock()
    fake_index = MagicMock(name="repo-index")
    indexer.build_index.return_value = fake_index
    graph = MagicMock()
    svc = _apply_service(db_env, indexer=indexer, graph=graph)

    result = svc.apply_patch(patch_id, db_env["tmp_path"])

    assert result.index_updated is True
    assert result.graph_updated is True
    indexer.build_index.assert_called_once()
    args, kwargs = indexer.build_index.call_args
    assert Path(args[0]).resolve() == db_env["tmp_path"]
    assert kwargs.get("repository_name") == "demo"
    graph.build_graph.assert_called_once_with(fake_index, force=True)
