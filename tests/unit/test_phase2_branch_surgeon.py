"""Phase 2 — multi-file refactoring + AI Refactoring Planner."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from refactory.transformation.ai_planner import AIRefactoringPlanner
from refactory.transformation.models import (
    TransformationRequest,
    TransformationStatus,
    TransformationType,
)
from refactory.transformation.planner import TransformationPlanner
from refactory.transformation.service import TransformationService
from refactory.transformation.symbol_index import RepositorySymbolIndex, SymbolType


def _logger():
    from loguru import logger

    return logger


@pytest.fixture
def planner():
    return TransformationPlanner(_logger())


@pytest.fixture
def service():
    storage = MagicMock()
    storage.get_analyses.return_value = []
    storage.store_analysis.return_value = "id"
    storage.store_metric.return_value = None
    parser = MagicMock()
    parser.parse_file.return_value = None
    ai = MagicMock()
    resp = MagicMock()
    resp.content = "{}"
    ai.generate.return_value = resp
    return TransformationService(
        logger=_logger(),
        parser_service=parser,
        indexer_service=MagicMock(),
        graph_service=MagicMock(),
        rule_engine=MagicMock(),
        policy_service=MagicMock(),
        storage_service=storage,
        ai_gateway=ai,
        prompt_service=MagicMock(),
    )


@pytest.fixture
def multi_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "auth.py").write_text(
        "def login(user):\n"
        "    return authenticate_user(user)\n"
        "\n"
        "def authenticate_user(user):\n"
        "    return user\n",
        encoding="utf-8",
    )
    (root / "app.py").write_text(
        "from auth import login\n"
        "\n"
        "def main():\n"
        "    return login('a')\n",
        encoding="utf-8",
    )
    (root / "tests_app.py").write_text(
        "from auth import login\n"
        "\n"
        "def test_login():\n"
        "    assert login('x') == 'x'\n",
        encoding="utf-8",
    )
    return root


def test_symbol_index_tree_sitter_or_ast(multi_repo: Path):
    index = RepositorySymbolIndex(multi_repo, logger=_logger()).build()
    files = index.files_referencing("login")
    assert "auth.py" in files
    assert "app.py" in files
    assert any(r.symbol_type == SymbolType.FUNCTION for r in index.find_by_name("login"))


def test_repository_wide_rename_updates_all_references(planner: TransformationPlanner, multi_repo: Path):
    plan = planner.create_plan(
        TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="auth.py",
            target_symbol="login",
            parameters={"old_name": "login", "new_name": "authenticate"},
            scope="repository",
        ),
        multi_repo,
    )
    assert len(plan.steps) >= 2
    assert len({s.file_path for s in plan.steps}) == len(plan.steps)  # no duplicate edits
    assert plan.operations
    assert plan.estimated_confidence > 0
    by_file = {s.file_path: s.new_content for s in plan.steps}
    assert "def authenticate(" in by_file["auth.py"]
    assert "def login(" not in by_file["auth.py"]
    assert "from auth import authenticate" in by_file["app.py"]
    assert "authenticate(" in by_file["app.py"]
    for content in by_file.values():
        ast.parse(content)


def test_file_scope_rename_stays_local(planner: TransformationPlanner, multi_repo: Path):
    plan = planner.create_plan(
        TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="auth.py",
            parameters={"old_name": "login", "new_name": "authenticate", "single_file": True},
            scope="file",
        ),
        multi_repo,
    )
    assert len(plan.steps) == 1
    assert plan.steps[0].file_path == "auth.py"


def test_no_broken_references_after_rename_apply(service: TransformationService, multi_repo: Path):
    req = TransformationRequest(
        transformation_type=TransformationType.RENAME_FUNCTION,
        target_file="auth.py",
        target_symbol="login",
        parameters={"old_name": "login", "new_name": "authenticate"},
        scope="repository",
    )
    preview = service.preview(req, multi_repo)
    assert preview.diff_preview
    assert preview.plan is not None
    assert preview.rollback_available is True
    assert preview.operations
    result = service.apply(req, multi_repo)
    assert result.status == TransformationStatus.APPLIED
    app_src = (multi_repo / "app.py").read_text(encoding="utf-8")
    auth_src = (multi_repo / "auth.py").read_text(encoding="utf-8")
    assert "login" not in app_src or "authenticate" in app_src
    assert "def authenticate" in auth_src
    assert "from auth import authenticate" in app_src
    # Import still resolves to a defined symbol name.
    assert "def login" not in auth_src


def test_planner_generation_from_natural_language(multi_repo: Path):
    ai = AIRefactoringPlanner(_logger(), TransformationPlanner(_logger()))
    plan = ai.plan_from_natural_language(
        "Rename login() to authenticate()", multi_repo
    )
    assert plan.goal
    assert plan.steps
    assert plan.estimated_confidence > 0.5
    assert any(op.op == "rename" for op in plan.operations)
    files = {s.file_path for s in plan.steps}
    assert "auth.py" in files
    assert "app.py" in files


def test_planner_split_file(multi_repo: Path):
    (multi_repo / "auth.py").write_text(
        "def login():\n"
        "    return 1\n"
        "\n"
        "def security_check():\n"
        "    return True\n",
        encoding="utf-8",
    )
    ai = AIRefactoringPlanner(_logger(), TransformationPlanner(_logger()))
    plan = ai.plan_from_natural_language(
        "Split auth.py into auth.py and security.py", multi_repo
    )
    assert plan.steps
    assert any(s.action == "create" and s.file_path == "security.py" for s in plan.steps)
    assert any(op.op == "create_file" for op in plan.operations)


def test_planner_preview_and_rollback(service: TransformationService, multi_repo: Path):
    req = TransformationRequest(
        transformation_type=TransformationType.AI_PLAN,
        natural_language="Rename login() to authenticate()",
        ai_assisted=True,
    )
    preview = service.preview(req, multi_repo)
    assert preview.goal
    assert preview.operations
    assert preview.files_modified
    assert "authenticate" in preview.diff_preview or any(
        "authenticate" in (s or "") for s in (preview.modified_symbols or [])
    )
    applied = service.apply(req, multi_repo)
    assert applied.status == TransformationStatus.APPLIED
    assert applied.rollback_available
    before_auth = (multi_repo / "auth.py").read_text(encoding="utf-8")
    assert "def authenticate" in before_auth
    rolled = service.rollback(multi_repo, history_id=applied.id)
    assert rolled.status == TransformationStatus.ROLLED_BACK
    restored = (multi_repo / "auth.py").read_text(encoding="utf-8")
    assert "def login" in restored


def test_preview_includes_plan_fields(service: TransformationService, multi_repo: Path):
    preview = service.preview(
        TransformationRequest(
            transformation_type=TransformationType.RENAME_SYMBOL,
            target_file="auth.py",
            parameters={"old_name": "login", "new_name": "authenticate"},
        ),
        multi_repo,
    )
    assert preview.plan is not None
    assert preview.plan.goal
    assert preview.confidence > 0
    assert preview.risk
    assert preview.rollback_available is True


def test_no_duplicate_file_steps(planner: TransformationPlanner, multi_repo: Path):
    plan = planner.create_plan(
        TransformationRequest(
            transformation_type=TransformationType.RENAME_SYMBOL,
            parameters={"old_name": "login", "new_name": "authenticate"},
        ),
        multi_repo,
    )
    paths = [s.file_path for s in plan.steps]
    assert len(paths) == len(set(paths))


def test_plan_only_endpoint_helper(service: TransformationService, multi_repo: Path):
    plan = service.plan_only(
        TransformationRequest(
            natural_language="Rename login() to authenticate()",
            transformation_type=TransformationType.AI_PLAN,
        ),
        multi_repo,
    )
    assert plan.steps
    assert plan.affected_files
