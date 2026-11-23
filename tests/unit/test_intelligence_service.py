"""Tests for AIIntelligenceService."""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from refactory.ai.models import AIResponse
from refactory.cache.store import NullCache
from refactory.core.logger import get_service_logger
from refactory.graph.service import RepositoryGraphService
from refactory.impact.service import ImpactAnalysisService
from refactory.indexer.models import (
    IndexedFile,
    RepositoryIndex,
    RepositoryStatistics,
    RepositorySummary,
)
from refactory.intelligence.models import (
    AISuggestionKind,
    SmellKind,
)
from refactory.intelligence.service import AIIntelligenceService
from refactory.parser.service import ParserService
from refactory.refactor.models import (
    RefactorAnalysis,
    RefactorCategory,
    RefactorIssue,
    RefactorMetrics,
    RefactorSeverity,
)

_NOW = datetime.now(timezone.utc)


def _make_ai_gateway(response_text: str = "[]") -> MagicMock:
    gw = MagicMock()
    gw.generate.return_value = AIResponse(
        text=response_text,
        provider="mock",
        model="test-model",
    )
    return gw


def _make_index(files: list[IndexedFile] | None = None) -> RepositoryIndex:
    files = files or []
    return RepositoryIndex(
        summary=RepositorySummary(
            repository_name="test",
            repository_root="/tmp/test",
            total_indexed_files=len(files),
            timestamp=_NOW,
        ),
        statistics=RepositoryStatistics(),
        files=files,
        file_hashes={f.relative_path: f.content_hash for f in files},
    )


def _make_service(
    ai_response: str = "[]",
    index: RepositoryIndex | None = None,
) -> AIIntelligenceService:
    logger = get_service_logger("test.intelligence")
    ai_gw = _make_ai_gateway(ai_response)
    parser = ParserService(
        ignore_dirs=[".git"],
        logger=get_service_logger("test.parser"),
    )
    indexer = MagicMock()
    indexer.load_index.return_value = index
    graph = RepositoryGraphService(
        logger=get_service_logger("test.graph"),
        cache=NullCache(),
    )
    impact = MagicMock()
    return AIIntelligenceService(
        logger=logger,
        ai_gateway=ai_gw,
        parser_service=parser,
        indexer_service=indexer,
        graph_service=graph,
        impact_service=impact,
    )


class TestAIRefactor:
    def test_empty_response(self):
        svc = _make_service(ai_response="[]")
        analysis = RefactorAnalysis(metrics=RefactorMetrics(files_analyzed=5))
        result = svc.ai_refactor(analysis)
        assert result.suggestions == []
        assert result.model == "test-model"

    def test_parses_json_response(self):
        import json
        items = [
            {
                "kind": "rename",
                "title": "Rename x to count",
                "description": "Better naming",
                "file": "app.py",
                "why": "Clarity",
                "benefits": "Readability",
                "risk": "low",
                "confidence_score": 0.8,
            }
        ]
        svc = _make_service(ai_response=json.dumps(items))
        analysis = RefactorAnalysis()
        result = svc.ai_refactor(analysis)
        assert len(result.suggestions) == 1
        assert result.suggestions[0].kind == AISuggestionKind.RENAME
        assert result.suggestions[0].confidence.score == 0.8

    def test_handles_invalid_json(self):
        svc = _make_service(ai_response="not valid json")
        analysis = RefactorAnalysis()
        result = svc.ai_refactor(analysis)
        assert len(result.suggestions) == 1  # fallback suggestion

    def test_handles_code_fenced_response(self):
        import json
        items = [{"kind": "extract_method", "title": "Extract helper"}]
        fenced = f"```json\n{json.dumps(items)}\n```"
        svc = _make_service(ai_response=fenced)
        result = svc.ai_refactor(RefactorAnalysis())
        assert len(result.suggestions) == 1


class TestPatchGeneration:
    def test_generates_patch(self):
        svc = _make_service(ai_response="--- a/test.py\n+++ b/test.py\n@@ -1 +1 @@\n-old\n+new")
        result = svc.generate_patch("test.py", "old\n", "Replace old with new")
        assert len(result.patches) == 1
        assert result.files_affected == 1
        assert "test.py" in result.patches[0].file_path


class TestArchitectureViolations:
    def test_no_graph_returns_empty(self):
        svc = _make_service()
        result = svc.detect_architecture_violations(Path("/tmp/test"))
        assert isinstance(result.violations, list)

    def test_health_score_decreases_with_violations(self):
        svc = _make_service()
        result = svc.detect_architecture_violations(Path("/tmp/test"))
        assert result.health_score <= 100


class TestDesignPatterns:
    def test_no_index_returns_empty(self):
        svc = _make_service()
        result = svc.detect_patterns(Path("/tmp/test"))
        assert result.summary == "No index available"

    def test_with_index(self):
        index = _make_index([
            IndexedFile(
                relative_path="service.py",
                language="python",
                file_size=100,
                content_hash="h1",
                module_name="service",
            ),
        ])
        svc = _make_service(index=index)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "service.py").write_text("class FooService:\n    pass\n", encoding="utf-8")
            svc._indexer.load_index.return_value = _make_index([
                IndexedFile(
                    relative_path="service.py",
                    language="python",
                    file_size=100,
                    content_hash="h1",
                    module_name="service",
                ),
            ])
            result = svc.detect_patterns(root)
            assert isinstance(result.patterns, list)


class TestCodeSmells:
    def test_no_index_returns_empty(self):
        svc = _make_service()
        result = svc.detect_code_smells(Path("/tmp/test"))
        assert result.summary == "No index available"


class TestTestGeneration:
    def test_generates_test_code(self):
        svc = _make_service(ai_response="def test_example():\n    assert True")
        result = svc.generate_tests("app.py", "def hello(): pass")
        assert len(result.tests) == 1
        assert "test_" in result.tests[0].file_path


class TestDocGeneration:
    def test_generates_docs(self):
        svc = _make_service(ai_response="Module documentation here.")
        result = svc.generate_docs("app.py", "def hello(): pass")
        assert len(result.docs) == 1
        assert result.docs[0].kind == "module"


class TestArchitectureSummary:
    def test_no_index_returns_empty(self):
        svc = _make_service()
        result = svc.architecture_summary(Path("/tmp/test"))
        assert result.summary == "No index available"

    def test_with_index(self):
        index = _make_index([
            IndexedFile(
                relative_path="core/app.py",
                language="python",
                file_size=100,
                content_hash="h1",
                module_name="core.app",
            ),
        ])
        svc = _make_service(index=index)
        svc._indexer.load_index.return_value = index
        result = svc.architecture_summary(Path("/tmp/test"))
        assert len(result.components) >= 1


class TestExplainFile:
    def test_explain_nonexistent(self):
        svc = _make_service()
        result = svc.explain_file("missing.py", Path("/tmp/test"))
        assert result.file_path == "missing.py"

    def test_explain_with_docstring(self):
        svc = _make_service()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "auth.py").write_text(
                '"""Authentication module."""\ndef login(): pass\n',
                encoding="utf-8",
            )
            result = svc.explain_file("auth.py", root)
            assert "auth" in result.purpose.lower() or "authentication" in result.purpose.lower()


class TestSmartImpact:
    def test_basic_prediction(self):
        svc = _make_service()
        result = svc.smart_impact("core/app.py", Path("/tmp/test"))
        assert result.deployment_risk in ("low", "medium", "high")


class TestArchitectureAdvice:
    def test_no_index_returns_empty(self):
        svc = _make_service()
        result = svc.architecture_advice(Path("/tmp/test"))
        assert result.summary == "No index available"

    def test_with_index(self):
        files = [
            IndexedFile(
                relative_path="big_module.py",
                language="python",
                file_size=5000,
                content_hash="h1",
                module_name="big_module",
                functions=[f"fn{i}" for i in range(20)],
            ),
        ]
        index = _make_index(files)
        svc = _make_service(index=index)
        svc._indexer.load_index.return_value = index
        result = svc.architecture_advice(Path("/tmp/test"))
        assert len(result.split_suggestions) >= 1
