"""Tests for Phase 4: CT-6 (Validation) + CT-5 (History persistence)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from refactory.transformation.models import (
    TransformationError,
    TransformationRequest,
    TransformationStatus,
    TransformationType,
)
from refactory.transformation.service import TransformationService


def _logger():
    from loguru import logger
    return logger


def _make_service(storage=None):
    if storage is None:
        storage = MagicMock()
    storage.get_analyses.return_value = []
    storage.store_analysis.return_value = "id"
    storage.store_metric.return_value = None
    parser = MagicMock()
    parser.parse_file.return_value = None
    ai = MagicMock()
    resp = MagicMock()
    resp.content = "code"
    ai.generate.return_value = resp
    return TransformationService(
        logger=_logger(), parser_service=parser, indexer_service=MagicMock(),
        graph_service=MagicMock(), rule_engine=MagicMock(), policy_service=MagicMock(),
        storage_service=storage, ai_gateway=ai, prompt_service=MagicMock(),
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    d = tmp_path / "repo"
    d.mkdir()
    (d / "app.py").write_text("def greet(name):\n    return f'Hello {name}'\n")
    return d


# ===========================================================================
# CT-6: Validate transformation types and reject invalid values
# ===========================================================================

class TestTransformationTypeValidation:
    def test_unsupported_type_preview_rejected(self, repo: Path):
        svc = _make_service()
        req = TransformationRequest(
            transformation_type=TransformationType.CREATE_INTERFACE,
            target_file="app.py",
        )
        with pytest.raises(TransformationError) as exc_info:
            svc.transform(req, repo)
        assert "not yet supported" in (exc_info.value.reason or "")

    def test_unsupported_type_apply_rejected(self, repo: Path):
        svc = _make_service()
        req = TransformationRequest(
            transformation_type=TransformationType.FIX_RULE_VIOLATIONS,
            target_file="app.py",
        )
        with pytest.raises(TransformationError) as exc_info:
            svc.apply(req, repo)
        assert "not yet supported" in (exc_info.value.reason or "")

    def test_supported_type_passes(self, repo: Path):
        svc = _make_service()
        req = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="app.py",
            parameters={"old_name": "greet", "new_name": "hello"},
        )
        preview = svc.transform(req, repo)
        assert preview.confidence > 0

    def test_rename_function_supported(self, repo: Path):
        svc = _make_service()
        req = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="app.py",
            parameters={"old_name": "greet", "new_name": "hello"},
        )
        result = svc.apply(req, repo)
        assert result.status == TransformationStatus.APPLIED

    def test_generate_docstrings_supported(self, repo: Path):
        svc = _make_service()
        req = TransformationRequest(
            transformation_type=TransformationType.GENERATE_DOCSTRINGS,
            target_file="app.py",
        )
        result = svc.apply(req, repo)
        assert result.status == TransformationStatus.APPLIED

    def test_remove_dead_code_supported(self, repo: Path):
        svc = _make_service()
        req = TransformationRequest(
            transformation_type=TransformationType.REMOVE_DEAD_CODE,
            target_file="app.py",
            target_symbol="greet",
        )
        result = svc.apply(req, repo)
        assert result.status == TransformationStatus.APPLIED


# ===========================================================================
# CT-5: Persist transformation history so rollback works
# ===========================================================================

class TestHistoryPersistence:
    def test_apply_stores_rollback_data(self, repo: Path):
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _make_service(storage)
        req = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="app.py",
            parameters={"old_name": "greet", "new_name": "hello"},
        )
        svc.apply(req, repo)
        apply_calls = [
            c for c in storage.store_analysis.call_args_list
            if c[1].get("command") == "apply"
        ]
        assert len(apply_calls) >= 1
        data = apply_calls[0][1]["result_data"]
        assert "rollback_patch" in data
        assert "steps" in data
        assert data["status"] == "applied"

    def test_history_survives_service_restart(self, repo: Path):
        stored_analyses = []

        def mock_store_analysis(**kwargs):
            stored_analyses.append(kwargs)
            return "id"

        def mock_get_analyses(path, *, command=None, limit=10):
            return [
                {"result_data": a["result_data"]}
                for a in stored_analyses
                if a.get("command") == command
            ]

        storage1 = MagicMock()
        storage1.get_analyses.return_value = []
        storage1.store_analysis.side_effect = mock_store_analysis
        storage1.store_metric.return_value = None
        svc1 = _make_service(storage1)
        req = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="app.py",
            parameters={"old_name": "greet", "new_name": "hello"},
        )
        svc1.apply(req, repo)
        assert len(svc1.get_history()) == 1

        storage2 = MagicMock()
        storage2.get_analyses.side_effect = mock_get_analyses
        storage2.store_analysis.return_value = "id"
        storage2.store_metric.return_value = None
        svc2 = _make_service(storage2)
        assert len(svc2.get_history()) >= 1

    def test_rollback_works_after_apply(self, repo: Path):
        svc = _make_service()
        req = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="app.py",
            parameters={"old_name": "greet", "new_name": "hello"},
        )
        svc.apply(req, repo)
        assert len(svc.get_history()) == 1
        result = svc.rollback(repo)
        assert result.status == TransformationStatus.ROLLED_BACK

    def test_history_stores_transformation_type(self, repo: Path):
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _make_service(storage)
        req = TransformationRequest(
            transformation_type=TransformationType.GENERATE_DOCSTRINGS,
            target_file="app.py",
        )
        svc.apply(req, repo)
        apply_calls = [
            c for c in storage.store_analysis.call_args_list
            if c[1].get("command") == "apply"
        ]
        data = apply_calls[0][1]["result_data"]
        assert data["transformation_type"] == "generate_docstrings"

    def test_empty_history_rollback_rejected(self, repo: Path):
        svc = _make_service()
        with pytest.raises(TransformationError) as exc_info:
            svc.rollback(repo)
        assert exc_info.value.status_code == 404
        assert "Nothing to rollback" in (exc_info.value.reason or "")
