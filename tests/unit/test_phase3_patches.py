"""Tests for Phase 3: CT-4 (Docstrings), CT-1 (Patches), CT-7 (Diffs)."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from refactory.transformation.models import TransformationRequest, TransformationType
from refactory.transformation.patch import PatchGenerator
from refactory.transformation.planner import TransformationPlanner
from refactory.transformation.service import TransformationService


def _logger():
    from loguru import logger
    return logger


@pytest.fixture
def planner():
    return TransformationPlanner(_logger())


@pytest.fixture
def patch_gen():
    return PatchGenerator()


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
        logger=_logger(), parser_service=parser, indexer_service=MagicMock(),
        graph_service=MagicMock(), rule_engine=MagicMock(), policy_service=MagicMock(),
        storage_service=storage, ai_gateway=ai, prompt_service=MagicMock(),
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    d = tmp_path / "repo"
    d.mkdir()
    (d / "app.py").write_text(
        "def greet(name):\n"
        "    return f'Hello {name}'\n"
        "\n"
        "class Service:\n"
        "    def process(self, data):\n"
        "        return data\n"
        "\n"
        "    def internal(self):\n"
        "        pass\n"
    )
    (d / "simple.py").write_text("def add(a, b):\n    return a + b\n")
    return d


# ===========================================================================
# CT-4: Fix Generate Docstrings
# ===========================================================================

class TestGenerateDocstrings:
    def test_docstring_valid_python(self, planner: TransformationPlanner, repo: Path):
        req = TransformationRequest(
            transformation_type=TransformationType.GENERATE_DOCSTRINGS,
            target_file="app.py",
        )
        plan = planner.create_plan(req, repo)
        assert len(plan.steps) == 1
        ast.parse(plan.steps[0].new_content)

    def test_module_level_indent(self, planner: TransformationPlanner, repo: Path):
        req = TransformationRequest(
            transformation_type=TransformationType.GENERATE_DOCSTRINGS,
            target_file="simple.py",
        )
        plan = planner.create_plan(req, repo)
        new_content = plan.steps[0].new_content
        assert '    """TODO: Document add."""' in new_content
        ast.parse(new_content)

    def test_method_indent(self, planner: TransformationPlanner, repo: Path):
        req = TransformationRequest(
            transformation_type=TransformationType.GENERATE_DOCSTRINGS,
            target_file="app.py",
        )
        plan = planner.create_plan(req, repo)
        new_content = plan.steps[0].new_content
        assert '        """TODO: Document process."""' in new_content
        ast.parse(new_content)

    def test_skips_already_documented(self, planner: TransformationPlanner, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "documented.py").write_text('def foo():\n    """Already documented."""\n    pass\n')
        req = TransformationRequest(
            transformation_type=TransformationType.GENERATE_DOCSTRINGS,
            target_file="documented.py",
        )
        plan = planner.create_plan(req, repo)
        assert plan.steps == []

    def test_nested_class_method(self, planner: TransformationPlanner, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "nested.py").write_text(
            "class Outer:\n"
            "    class Inner:\n"
            "        def deep_method(self):\n"
            "            pass\n"
        )
        req = TransformationRequest(
            transformation_type=TransformationType.GENERATE_DOCSTRINGS,
            target_file="nested.py",
        )
        plan = planner.create_plan(req, repo)
        if plan.steps:
            ast.parse(plan.steps[0].new_content)


# ===========================================================================
# CT-1 + CT-7: PatchGenerator produces real diffs
# ===========================================================================

class TestRealPatches:
    def test_rename_produces_patch(self, service: TransformationService, repo: Path):
        req = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="simple.py",
            parameters={"old_name": "add", "new_name": "sum_values"},
        )
        preview = service.transform(req, repo)
        assert preview.diff_preview != ""
        assert preview.additions > 0

    def test_docstring_produces_patch(self, service: TransformationService, repo: Path):
        req = TransformationRequest(
            transformation_type=TransformationType.GENERATE_DOCSTRINGS,
            target_file="app.py",
        )
        preview = service.transform(req, repo)
        assert preview.diff_preview != ""
        assert preview.additions > 0

    def test_remove_dead_code_patch(self, service: TransformationService, repo: Path):
        req = TransformationRequest(
            transformation_type=TransformationType.REMOVE_DEAD_CODE,
            target_file="app.py",
            target_symbol="greet",
        )
        preview = service.transform(req, repo)
        assert preview.diff_preview != ""

    def test_patch_has_unified_format(self, service: TransformationService, repo: Path):
        req = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="simple.py",
            parameters={"old_name": "add", "new_name": "sum_values"},
        )
        preview = service.transform(req, repo)
        assert "--- a/" in preview.diff_preview
        assert "+++ b/" in preview.diff_preview

    def test_patch_from_disk_content(self, patch_gen: PatchGenerator, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "target.py").write_text("old_code = True\n")
        from refactory.transformation.models import TransformationPlan, TransformationStep
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="target.py", new_content="new_code = True\n"),
        ])
        patch = patch_gen.generate(plan, repo)
        assert patch.additions >= 1
        assert patch.deletions >= 1
        assert "target.py" in patch.files_modified

    def test_preview_file_count(self, service: TransformationService, repo: Path):
        req = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="simple.py",
            parameters={"old_name": "add", "new_name": "sum_values"},
        )
        preview = service.transform(req, repo)
        assert len(preview.files_modified) >= 1

    def test_preview_confidence_set(self, service: TransformationService, repo: Path):
        req = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="simple.py",
            parameters={"old_name": "add", "new_name": "sum_values"},
        )
        preview = service.transform(req, repo)
        assert preview.confidence > 0

    def test_apply_produces_real_change(self, service: TransformationService, repo: Path):
        req = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="simple.py",
            parameters={"old_name": "add", "new_name": "sum_values"},
        )
        result = service.apply(req, repo)
        content = (repo / "simple.py").read_text()
        assert "sum_values" in content
        assert "add" not in content

    def test_docstring_apply_valid(self, service: TransformationService, repo: Path):
        req = TransformationRequest(
            transformation_type=TransformationType.GENERATE_DOCSTRINGS,
            target_file="app.py",
        )
        result = service.apply(req, repo)
        if result.files_modified:
            content = (repo / "app.py").read_text()
            ast.parse(content)
            assert "TODO: Document" in content

    def test_multiple_hunks(self, patch_gen: PatchGenerator):
        from refactory.transformation.models import TransformationPlan, TransformationStep
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="a.py", original_content="x=1\n", new_content="x=2\n"),
            TransformationStep(file_path="b.py", original_content="y=1\n", new_content="y=2\n"),
        ])
        patch = patch_gen.generate(plan, Path("."))
        assert len(patch.hunks) == 2
        assert patch.diff_content != ""
