"""Transformations: AST preview/apply/rollback + recent history."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from refactory.transformation.models import (
    TransformationError,
    TransformationRequest,
    TransformationType,
)
from refactory.transformation.planner import TransformationPlanner
from refactory.transformation.service import TransformationService


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "auth.py").write_text(
        "def login(user, password):\n"
        "    token = user + password\n"
        "    return token\n"
        "\n"
        "def caller():\n"
        "    return login('a', 'b')\n",
        encoding="utf-8",
    )
    (tmp_path / "dest.py").write_text("# destination\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def service(repo: Path) -> TransformationService:
    logger = MagicMock()
    storage = MagicMock()
    storage.get_analyses.return_value = []
    return TransformationService(
        logger=logger,
        parser_service=MagicMock(),
        indexer_service=MagicMock(),
        graph_service=MagicMock(),
        rule_engine=MagicMock(),
        policy_service=MagicMock(),
        storage_service=storage,
        ai_gateway=MagicMock(),
        prompt_service=MagicMock(),
        query_service=None,
        persistence_service=None,
    )


def test_rename_symbol_preview_has_diff(service: TransformationService, repo: Path):
    preview = service.preview(
        TransformationRequest(
            transformation_type=TransformationType.RENAME_SYMBOL,
            target_file="auth.py",
            target_symbol="login",
            parameters={"old_name": "login", "new_name": "authenticate"},
        ),
        repo,
    )
    assert preview.additions > 0 or preview.deletions > 0
    assert "authenticate" in preview.diff_preview
    assert preview.description


def test_empty_rename_raises(service: TransformationService, repo: Path):
    with pytest.raises(TransformationError):
        service.preview(
            TransformationRequest(
                transformation_type=TransformationType.RENAME_SYMBOL,
                target_file="auth.py",
                target_symbol="login",
                parameters={"old_name": "login", "new_name": ""},
            ),
            repo,
        )


def test_missing_symbol_raises_precise_error(service: TransformationService, repo: Path):
    with pytest.raises(TransformationError) as exc_info:
        service.preview(
            TransformationRequest(
                transformation_type=TransformationType.RENAME_SYMBOL,
                target_file="auth.py",
                target_symbol="missing_fn",
                parameters={"old_name": "missing_fn", "new_name": "renamed"},
            ),
            repo,
        )
    err = exc_info.value
    assert err.message == "Transformation failed"
    assert err.errors
    assert "Symbol 'missing_fn' not found in auth.py." in err.errors[0]


def test_missing_file_raises_precise_error(service: TransformationService, repo: Path):
    with pytest.raises(TransformationError) as exc_info:
        service.preview(
            TransformationRequest(
                transformation_type=TransformationType.RENAME_SYMBOL,
                target_file="login.py",
                target_symbol="login",
                parameters={"old_name": "login", "new_name": "authenticate"},
            ),
            repo,
        )
    assert "File 'login.py' not found." in exc_info.value.errors[0]


def test_transform_error_response_envelope():
    from refactory.api.routes.transform import _error_response

    exc = TransformationError(
        "Transformation failed",
        reason="Symbol 'login' not found in login.py.",
        errors=["Symbol 'login' not found in login.py."],
        meta={"target_file": "login.py"},
    )
    response = _error_response(exc)
    assert response.status_code == 422
    body = response.body
    import json

    payload = json.loads(body)
    assert payload["status"] == "error"
    assert payload["message"] == "Transformation failed"
    assert payload["errors"] == ["Symbol 'login' not found in login.py."]
    assert payload["meta"]["target_file"] == "login.py"


def test_extract_method_from_symbol_body(service: TransformationService, repo: Path):
    preview = service.preview(
        TransformationRequest(
            transformation_type=TransformationType.EXTRACT_METHOD,
            target_file="auth.py",
            target_symbol="login",
            parameters={"method_name": "build_token"},
        ),
        repo,
    )
    assert "build_token" in preview.diff_preview
    assert preview.additions > 0


def test_inline_method(service: TransformationService, repo: Path):
    (repo / "simple.py").write_text(
        "def add(a, b):\n"
        "    return a + b\n"
        "\n"
        "def run():\n"
        "    return add(1, 2)\n",
        encoding="utf-8",
    )
    preview = service.preview(
        TransformationRequest(
            transformation_type=TransformationType.INLINE_METHOD,
            target_file="simple.py",
            target_symbol="add",
        ),
        repo,
    )
    assert "def add" not in preview.diff_preview.split("\n+++")[-1] or preview.deletions > 0
    assert preview.diff_preview


def test_move_symbol(service: TransformationService, repo: Path):
    preview = service.preview(
        TransformationRequest(
            transformation_type=TransformationType.MOVE_SYMBOL,
            target_file="auth.py",
            target_symbol="login",
            parameters={"destination_file": "dest.py"},
        ),
        repo,
    )
    assert "dest.py" in preview.files_modified
    assert preview.diff_preview


def test_change_signature_rename(service: TransformationService, repo: Path):
    preview = service.preview(
        TransformationRequest(
            transformation_type=TransformationType.CHANGE_SIGNATURE,
            target_file="auth.py",
            target_symbol="login",
            parameters={"new_name": "authenticate"},
        ),
        repo,
    )
    assert "authenticate" in preview.diff_preview


def test_apply_and_rollback_restores_file(service: TransformationService, repo: Path):
    before = (repo / "auth.py").read_text(encoding="utf-8")
    result = service.apply(
        TransformationRequest(
            transformation_type=TransformationType.RENAME_SYMBOL,
            target_file="auth.py",
            target_symbol="login",
            parameters={"old_name": "login", "new_name": "authenticate"},
        ),
        repo,
    )
    assert result.status.value == "applied"
    assert "def authenticate" in (repo / "auth.py").read_text(encoding="utf-8")
    recent = service.list_recent(limit=5)
    assert recent and recent[0].id == result.id
    assert recent[0].can_rollback is True
    assert recent[0].rolled_back is False

    rolled = service.rollback(repo, history_id=result.id)
    assert rolled.status.value == "rolled_back"
    assert (repo / "auth.py").read_text(encoding="utf-8") == before

    recent_after = service.list_recent(limit=5)
    assert recent_after and recent_after[0].id == result.id
    assert recent_after[0].status.value == "rolled_back"
    assert recent_after[0].can_rollback is False
    assert recent_after[0].rolled_back is True
    assert recent_after[0].rolled_back_at is not None


def _rollback_command_writes(storage: MagicMock) -> int:
    return sum(
        1
        for c in storage.store_analysis.call_args_list
        if c.kwargs.get("command") == "rollback"
    )


def test_duplicate_rollback_rejected(service: TransformationService, repo: Path):
    result = service.apply(
        TransformationRequest(
            transformation_type=TransformationType.RENAME_SYMBOL,
            target_file="auth.py",
            target_symbol="login",
            parameters={"old_name": "login", "new_name": "authenticate"},
        ),
        repo,
    )
    service.rollback(repo, history_id=result.id)
    rollback_writes = _rollback_command_writes(service._storage)
    assert rollback_writes == 1

    with pytest.raises(TransformationError) as exc_info:
        service.rollback(repo, history_id=result.id)
    assert exc_info.value.status_code == 409
    assert "already rolled back" in exc_info.value.message.lower()
    # Second attempt must not restore again or append another history entry.
    assert _rollback_command_writes(service._storage) == rollback_writes


def test_recent_status_fields_after_reload(service: TransformationService, repo: Path):
    """Rolled-back state must survive ensure_history_loaded (page refresh)."""
    result = service.apply(
        TransformationRequest(
            transformation_type=TransformationType.RENAME_SYMBOL,
            target_file="auth.py",
            target_symbol="login",
            parameters={"old_name": "login", "new_name": "authenticate"},
        ),
        repo,
    )
    service.rollback(repo, history_id=result.id)

    # Simulate persisted analyses returned newest-first for GET /transform/recent.
    applied_payload = {
        "history_id": result.id,
        "status": "applied",
        "transformation_type": "rename_symbol",
        "description": "Rename login → authenticate",
        "target_file": "auth.py",
        "target_symbol": "login",
        "files_modified": ["auth.py"],
        "steps": [],
        "validation_status": "passed",
        "rollback_patch": "",
        "patch_content": "",
    }
    rolled_payload = {
        **applied_payload,
        "status": "rolled_back",
        "rolled_back_at": "2026-07-31T12:00:00+00:00",
    }
    service._storage.get_analyses.return_value = [
        {"result_data": rolled_payload, "created_at": "2026-07-31T12:00:00+00:00"},
        {"result_data": applied_payload, "created_at": "2026-07-31T11:00:00+00:00"},
    ]
    service._history.clear()
    service.ensure_history_loaded(repo)

    recent = service.list_recent(limit=5)
    assert len(recent) == 1
    assert recent[0].id == result.id
    assert recent[0].status.value == "rolled_back"
    assert recent[0].can_rollback is False
    assert recent[0].rolled_back is True
    assert recent[0].rolled_back_at is not None


def test_history_item_api_contract():
    from datetime import datetime, timezone

    from refactory.api.routes.transform import _history_item
    from refactory.transformation.models import (
        TransformationHistory,
        TransformationStatus,
    )

    applied = TransformationHistory(
        id="TH-TEST1",
        status=TransformationStatus.APPLIED,
        description="Rename login → authenticate",
    )
    item = _history_item(applied)
    assert item["status"] == "applied"
    assert item["canRollback"] is True
    assert item["can_rollback"] is True
    assert item["rolled_back"] is False

    rolled = TransformationHistory(
        id="TH-TEST2",
        status=TransformationStatus.ROLLED_BACK,
        description="Rename login → authenticate",
        rolled_back_at=datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
    )
    item2 = _history_item(rolled)
    assert item2["status"] == "rolled_back"
    assert item2["canRollback"] is False
    assert item2["rolled_back"] is True
    assert item2["rolled_back_at"]


def test_planner_ast_rename_positions():
    planner = TransformationPlanner(MagicMock())
    src = "def foo():\n    return foo\n"
    out = planner._ast_rename(src, "foo", "bar")
    assert "def bar" in out
    assert "return bar" in out
