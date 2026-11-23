"""Additional transformation engine tests — edge cases and CLI coverage."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from refactory.transformation.models import (
    TransformationError,
    TransformationRequest,
    TransformationResult,
    TransformationStatus,
    TransformationType,
)
from refactory.transformation.service import TransformationService


def _logger():
    from loguru import logger
    return logger


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
    resp.content = "code"
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
def repo(tmp_path: Path) -> Path:
    d = tmp_path / "repo"
    d.mkdir()
    (d / "app.py").write_text("class App:\n    def run(self):\n        pass\n")
    return d


class TestTransformationEdgeCases:
    def test_ai_failure_graceful(self, service: TransformationService, repo: Path):
        service._ai.generate.side_effect = RuntimeError("AI down")
        request = TransformationRequest(
            transformation_type=TransformationType.GENERATE_DOCSTRINGS,
            target_file="app.py",
            ai_assisted=True,
        )
        preview = service.transform(request, repo)
        assert preview.plan_id != ""

    def test_storage_failure_graceful(self, service: TransformationService, repo: Path):
        service._storage.store_analysis.side_effect = RuntimeError("DB down")
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="app.py",
            parameters={"old_name": "App", "new_name": "Application"},
        )
        try:
            service.apply(request, repo)
        except Exception:
            pass

    def test_unicode_file(self, service: TransformationService, tmp_path: Path):
        repo = tmp_path / "r"
        repo.mkdir()
        (repo / "uni.py").write_text("# café = 'ñ'\nx = 1\n", encoding="utf-8")
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="uni.py",
            parameters={"old_name": "x", "new_name": "y"},
        )
        result = service.apply(request, repo)
        assert result.status == TransformationStatus.APPLIED
        assert "y = 1" in (repo / "uni.py").read_text(encoding="utf-8")

    def test_empty_file(self, service: TransformationService, tmp_path: Path):
        repo = tmp_path / "r"
        repo.mkdir()
        (repo / "empty.py").write_text("")
        request = TransformationRequest(
            transformation_type=TransformationType.GENERATE_DOCSTRINGS,
            target_file="empty.py",
        )
        with pytest.raises(TransformationError):
            service.transform(request, repo)

    def test_large_rename(self, service: TransformationService, tmp_path: Path):
        repo = tmp_path / "r"
        repo.mkdir()
        content = "\n".join(f"var_{i} = {i}" for i in range(100))
        (repo / "large.py").write_text(content)
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="large.py",
            parameters={"old_name": "var_50", "new_name": "renamed_50"},
        )
        result = service.apply(request, repo)
        assert result.status == TransformationStatus.APPLIED
        assert "renamed_50" in (repo / "large.py").read_text()
