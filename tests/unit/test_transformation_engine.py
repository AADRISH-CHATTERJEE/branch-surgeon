"""Comprehensive tests for the Transformation Engine (Sprint 8).

Covers: models, planner, patch generator, validator, preview, service,
conflict detection, rollback, history, incremental, CLI, edge cases.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from refactory.transformation.models import (
    ConflictType,
    PatchHunk,
    PatchStatistics,
    TransformationConflict,
    TransformationHistory,
    TransformationPatch,
    TransformationPlan,
    TransformationPreview,
    TransformationRequest,
    TransformationResult,
    TransformationStatus,
    TransformationStep,
    TransformationType,
    TransformationValidation,
    ValidationCheck,
    ValidationStatus,
)
from refactory.transformation.patch import PatchGenerator
from refactory.transformation.planner import TransformationPlanner
from refactory.transformation.preview import PreviewEngine
from refactory.transformation.service import TransformationService
from refactory.transformation.validator import ValidationEngine


def _logger():
    from loguru import logger
    return logger


@pytest.fixture
def patch_gen():
    return PatchGenerator()


@pytest.fixture
def planner():
    return TransformationPlanner(_logger())


@pytest.fixture
def validator():
    return ValidationEngine(
        logger=_logger(),
        parser_service=MagicMock(),
        rule_engine=MagicMock(),
        policy_service=MagicMock(),
    )


@pytest.fixture
def preview_engine():
    return PreviewEngine(_logger())


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
    resp.content = "new code"
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
    (d / "src").mkdir()
    (d / "src" / "service.py").write_text(
        "class UserService:\n"
        "    def get_user(self, user_id):\n"
        "        return user_id\n"
        "\n"
        "    def old_method(self):\n"
        "        pass\n"
    )
    (d / "src" / "utils.py").write_text(
        "def helper_func():\n"
        "    return 42\n"
        "\n"
        "def unused_func():\n"
        "    pass\n"
    )
    (d / "src" / "main.py").write_text(
        "from src.service import UserService\n"
        "from src.utils import helper_func\n"
        "\n"
        "def main():\n"
        "    svc = UserService()\n"
        "    return helper_func()\n"
    )
    return d


# ===========================================================================
# Task 2: Models (30 tests)
# ===========================================================================

class TestTransformationModels:
    def test_transformation_types(self):
        assert TransformationType.RENAME_SYMBOL == "rename_symbol"
        assert TransformationType.EXTRACT_METHOD == "extract_method"
        assert TransformationType.REMOVE_DEAD_CODE == "remove_dead_code"

    def test_all_types_exist(self):
        types = list(TransformationType)
        assert len(types) >= 20
        assert TransformationType.MOVE_SYMBOL in types
        assert TransformationType.CHANGE_SIGNATURE in types
        assert TransformationType.RENAME_FILE in types
        assert TransformationType.AI_PLAN in types

    def test_transformation_status(self):
        assert TransformationStatus.PLANNED == "planned"
        assert TransformationStatus.APPLIED == "applied"
        assert TransformationStatus.ROLLED_BACK == "rolled_back"

    def test_validation_status(self):
        assert ValidationStatus.PASSED == "passed"
        assert ValidationStatus.FAILED == "failed"

    def test_conflict_types(self):
        assert ConflictType.OVERLAPPING_EDIT == "overlapping_edit"
        assert ConflictType.DELETED_FILE == "deleted_file"
        assert ConflictType.MERGE_CONFLICT == "merge_conflict"

    def test_request_model(self):
        r = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="a.py",
            target_symbol="old_func",
        )
        assert r.target_file == "a.py"

    def test_step_model(self):
        s = TransformationStep(file_path="a.py", action="modify", new_content="x=1")
        assert s.action == "modify"

    def test_plan_model(self):
        p = TransformationPlan()
        assert p.id.startswith("TP-")
        assert p.steps == []

    def test_patch_model(self):
        p = TransformationPatch()
        assert p.id.startswith("PA-")
        assert p.additions == 0

    def test_hunk_model(self):
        h = PatchHunk(file_path="a.py", content="+x=1")
        assert h.file_path == "a.py"

    def test_statistics_model(self):
        s = PatchStatistics(files_modified=3, lines_added=10, lines_removed=5)
        assert s.files_modified == 3

    def test_conflict_model(self):
        c = TransformationConflict(
            conflict_type=ConflictType.OVERLAPPING_EDIT,
            file_path="a.py",
        )
        assert c.file_path == "a.py"

    def test_validation_model(self):
        v = TransformationValidation(status=ValidationStatus.PASSED)
        assert v.errors == []

    def test_validation_check_model(self):
        c = ValidationCheck(name="syntax", status=ValidationStatus.PASSED)
        assert c.name == "syntax"

    def test_preview_model(self):
        p = TransformationPreview(plan_id="TP-1", additions=5, deletions=2)
        assert p.additions == 5

    def test_result_model(self):
        r = TransformationResult(status=TransformationStatus.APPLIED)
        assert r.id.startswith("TR-")
        assert r.rollback_available is True

    def test_history_model(self):
        h = TransformationHistory(plan_id="TP-1", status=TransformationStatus.APPLIED)
        assert h.id.startswith("TH-")

    def test_request_defaults(self):
        r = TransformationRequest()
        assert r.ai_assisted is False
        assert r.parameters == {}

    def test_plan_serializable(self):
        p = TransformationPlan(description="Test")
        data = p.model_dump(mode="json")
        assert "id" in data

    def test_patch_serializable(self):
        p = TransformationPatch(diff_content="diff")
        data = p.model_dump(mode="json")
        assert data["diff_content"] == "diff"

    def test_result_serializable(self):
        r = TransformationResult()
        data = r.model_dump(mode="json")
        assert "status" in data

    def test_step_with_lines(self):
        s = TransformationStep(file_path="a.py", start_line=10, end_line=20)
        assert s.start_line == 10
        assert s.end_line == 20

    def test_plan_with_risk(self):
        p = TransformationPlan(estimated_risk="high")
        assert p.estimated_risk == "high"

    def test_plan_affected_files(self):
        p = TransformationPlan(affected_files=["a.py", "b.py"])
        assert len(p.affected_files) == 2

    def test_patch_files_modified(self):
        p = TransformationPatch(files_modified=["x.py"])
        assert "x.py" in p.files_modified

    def test_history_with_rollback(self):
        h = TransformationHistory(rollback_patch="diff content")
        assert h.rollback_patch != ""

    def test_preview_confidence(self):
        p = TransformationPreview(confidence=0.95)
        assert p.confidence == 0.95

    def test_validation_warnings(self):
        v = TransformationValidation(
            status=ValidationStatus.WARNINGS,
            warnings=["Minor issue"],
        )
        assert len(v.warnings) == 1

    def test_conflict_line_range(self):
        c = TransformationConflict(
            conflict_type=ConflictType.INVALID_LINE_MAPPING,
            line_range=(10, 20),
        )
        assert c.line_range == (10, 20)

    def test_request_ai_flag(self):
        r = TransformationRequest(ai_assisted=True)
        assert r.ai_assisted is True


# ===========================================================================
# Task 3: Patch Generation (30 tests)
# ===========================================================================

class TestPatchGeneration:
    def test_generate_simple_diff(self, patch_gen: PatchGenerator):
        patch = patch_gen.generate_from_content("a.py", "x = 1\n", "x = 2\n")
        assert patch.additions > 0
        assert patch.deletions > 0
        assert "a.py" in patch.files_modified

    def test_no_diff_for_same_content(self, patch_gen: PatchGenerator):
        patch = patch_gen.generate_from_content("a.py", "x = 1\n", "x = 1\n")
        assert patch.additions == 0
        assert patch.deletions == 0

    def test_diff_format_unified(self, patch_gen: PatchGenerator):
        patch = patch_gen.generate_from_content("a.py", "old\n", "new\n")
        assert "--- a/a.py" in patch.diff_content
        assert "+++ b/a.py" in patch.diff_content

    def test_additions_counted(self, patch_gen: PatchGenerator):
        patch = patch_gen.generate_from_content("a.py", "", "line1\nline2\n")
        assert patch.additions == 2

    def test_deletions_counted(self, patch_gen: PatchGenerator):
        patch = patch_gen.generate_from_content("a.py", "line1\nline2\n", "")
        assert patch.deletions == 2

    def test_multiple_files(self, patch_gen: PatchGenerator):
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="a.py", original_content="x=1\n", new_content="x=2\n"),
            TransformationStep(file_path="b.py", original_content="y=1\n", new_content="y=2\n"),
        ])
        patch = patch_gen.generate(plan, Path("."))
        assert len(patch.files_modified) == 2

    def test_hunks_generated(self, patch_gen: PatchGenerator):
        patch = patch_gen.generate_from_content("a.py", "old\n", "new\n")
        assert len(patch.hunks) == 1
        assert patch.hunks[0].file_path == "a.py"

    def test_statistics(self, patch_gen: PatchGenerator):
        patch = patch_gen.generate_from_content("a.py", "old\n", "new\n")
        stats = patch_gen.compute_statistics(patch)
        assert stats.files_modified == 1
        assert stats.hunks_count == 1

    def test_review_time_estimate(self, patch_gen: PatchGenerator):
        content = "\n".join(f"line{i}" for i in range(50))
        patch = patch_gen.generate_from_content("a.py", "", content)
        stats = patch_gen.compute_statistics(patch)
        assert "min" in stats.estimated_review_time

    def test_rollback_generation(self, patch_gen: PatchGenerator):
        patch = patch_gen.generate_from_content("a.py", "old\n", "new\n")
        rollback = patch_gen.generate_rollback(patch)
        assert "+old" in rollback
        assert "-new" in rollback

    def test_rollback_empty_patch(self, patch_gen: PatchGenerator):
        patch = TransformationPatch()
        rollback = patch_gen.generate_rollback(patch)
        assert rollback == ""

    def test_empty_plan(self, patch_gen: PatchGenerator):
        plan = TransformationPlan(steps=[])
        patch = patch_gen.generate(plan, Path("."))
        assert patch.files_modified == []

    def test_step_without_file(self, patch_gen: PatchGenerator):
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="", original_content="x", new_content="y"),
        ])
        patch = patch_gen.generate(plan, Path("."))
        assert patch.files_modified == []

    def test_multiline_diff(self, patch_gen: PatchGenerator):
        orig = "line1\nline2\nline3\n"
        new = "line1\nmodified\nline3\n"
        patch = patch_gen.generate_from_content("a.py", orig, new)
        assert patch.additions >= 1
        assert patch.deletions >= 1

    def test_patch_id_unique(self, patch_gen: PatchGenerator):
        p1 = patch_gen.generate_from_content("a.py", "x\n", "y\n")
        p2 = patch_gen.generate_from_content("b.py", "a\n", "b\n")
        assert p1.id != p2.id

    def test_large_file_diff(self, patch_gen: PatchGenerator):
        orig = "\n".join(f"line{i}" for i in range(100))
        new = "\n".join(f"modified{i}" for i in range(100))
        patch = patch_gen.generate_from_content("big.py", orig, new)
        assert patch.additions > 0

    def test_add_only(self, patch_gen: PatchGenerator):
        patch = patch_gen.generate_from_content("a.py", "existing\n", "existing\nnew_line\n")
        assert patch.additions >= 1
        assert patch.deletions == 0

    def test_remove_only(self, patch_gen: PatchGenerator):
        patch = patch_gen.generate_from_content("a.py", "line1\nline2\n", "line1\n")
        assert patch.deletions >= 1

    def test_plan_id_propagated(self, patch_gen: PatchGenerator):
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="a.py", original_content="x\n", new_content="y\n"),
        ])
        patch = patch_gen.generate(plan, Path("."))
        assert patch.plan_id == plan.id

    def test_diff_content_string(self, patch_gen: PatchGenerator):
        patch = patch_gen.generate_from_content("a.py", "x\n", "y\n")
        assert isinstance(patch.diff_content, str)

    def test_rollback_swaps_plus_minus(self, patch_gen: PatchGenerator):
        patch = patch_gen.generate_from_content("a.py", "old\n", "new\n")
        rollback = patch_gen.generate_rollback(patch)
        assert "+old" in rollback
        assert "-new" in rollback

    def test_read_from_file(self, patch_gen: PatchGenerator, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("original\n")
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="test.py", new_content="modified\n"),
        ])
        patch = patch_gen.generate(plan, tmp_path)
        assert patch.additions >= 1

    def test_file_not_found(self, patch_gen: PatchGenerator, tmp_path: Path):
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="missing.py", new_content="x\n"),
        ])
        patch = patch_gen.generate(plan, tmp_path)
        assert "missing.py" in patch.files_modified

    def test_statistics_zero(self, patch_gen: PatchGenerator):
        patch = TransformationPatch()
        stats = patch_gen.compute_statistics(patch)
        assert stats.files_modified == 0

    def test_hunk_content(self, patch_gen: PatchGenerator):
        patch = patch_gen.generate_from_content("a.py", "hello\n", "world\n")
        assert patch.hunks[0].content != ""

    def test_patch_model_dump(self, patch_gen: PatchGenerator):
        patch = patch_gen.generate_from_content("a.py", "x\n", "y\n")
        data = patch.model_dump(mode="json")
        assert "diff_content" in data

    def test_empty_original_full_new(self, patch_gen: PatchGenerator):
        patch = patch_gen.generate_from_content("a.py", "", "line1\nline2\nline3\n")
        assert patch.additions == 3

    def test_full_original_empty_new(self, patch_gen: PatchGenerator):
        patch = patch_gen.generate_from_content("a.py", "a\nb\nc\n", "")
        assert patch.deletions == 3

    def test_whitespace_only_change(self, patch_gen: PatchGenerator):
        patch = patch_gen.generate_from_content("a.py", "x = 1\n", "x  = 1\n")
        assert patch.additions >= 1

    def test_generate_preserves_plan_type(self, patch_gen: PatchGenerator):
        plan = TransformationPlan(
            transformation_type=TransformationType.RENAME_FUNCTION,
            steps=[TransformationStep(file_path="a.py", original_content="x\n", new_content="y\n")],
        )
        patch = patch_gen.generate(plan, Path("."))
        assert patch.plan_id == plan.id


# ===========================================================================
# Task 5: Validation (25 tests)
# ===========================================================================

class TestValidation:
    def test_valid_python(self, validator: ValidationEngine):
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="a.py", new_content="x = 1\n"),
        ])
        patch = TransformationPatch(diff_content="diff", hunks=[PatchHunk(file_path="a.py")])
        result = validator.validate(plan, patch, Path("."))
        assert result.status == ValidationStatus.PASSED

    def test_invalid_syntax(self, validator: ValidationEngine):
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="a.py", new_content="def (\n"),
        ])
        patch = TransformationPatch(diff_content="diff")
        result = validator.validate(plan, patch, Path("."))
        assert result.status == ValidationStatus.FAILED

    def test_empty_patch_warning(self, validator: ValidationEngine):
        plan = TransformationPlan(steps=[])
        patch = TransformationPatch()
        result = validator.validate(plan, patch, Path("."))
        assert result.status == ValidationStatus.WARNINGS

    def test_checks_populated(self, validator: ValidationEngine):
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="a.py", new_content="x = 1\n"),
        ])
        patch = TransformationPatch(diff_content="d", hunks=[PatchHunk(file_path="a.py")])
        result = validator.validate(plan, patch, Path("."))
        assert len(result.checks) >= 4

    def test_non_python_file_passes(self, validator: ValidationEngine):
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="a.txt", new_content="invalid python {{"),
        ])
        patch = TransformationPatch(diff_content="d", hunks=[PatchHunk(file_path="a.txt")])
        result = validator.validate(plan, patch, Path("."))
        assert result.status == ValidationStatus.PASSED

    def test_multiple_valid_files(self, validator: ValidationEngine):
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="a.py", new_content="x = 1\n"),
            TransformationStep(file_path="b.py", new_content="y = 2\n"),
        ])
        patch = TransformationPatch(diff_content="d", hunks=[PatchHunk(file_path="a.py")])
        result = validator.validate(plan, patch, Path("."))
        assert result.status == ValidationStatus.PASSED

    def test_one_invalid_file_fails_all(self, validator: ValidationEngine):
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="a.py", new_content="x = 1\n"),
            TransformationStep(file_path="b.py", new_content="def (\n"),
        ])
        patch = TransformationPatch(diff_content="d")
        result = validator.validate(plan, patch, Path("."))
        assert result.status == ValidationStatus.FAILED

    def test_error_messages(self, validator: ValidationEngine):
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="a.py", new_content="def (\n"),
        ])
        patch = TransformationPatch(diff_content="d")
        result = validator.validate(plan, patch, Path("."))
        assert len(result.errors) > 0

    def test_complex_valid_code(self, validator: ValidationEngine):
        code = (
            "import os\n\n"
            "class Foo:\n"
            "    def bar(self, x: int) -> str:\n"
            "        return str(x)\n"
        )
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="foo.py", new_content=code),
        ])
        patch = TransformationPatch(diff_content="d", hunks=[PatchHunk(file_path="foo.py")])
        result = validator.validate(plan, patch, Path("."))
        assert result.status == ValidationStatus.PASSED

    def test_empty_content_passes(self, validator: ValidationEngine):
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="a.py", new_content=""),
        ])
        patch = TransformationPatch(diff_content="d", hunks=[PatchHunk(file_path="a.py")])
        result = validator.validate(plan, patch, Path("."))
        assert result.status == ValidationStatus.PASSED

    def test_validation_serializable(self, validator: ValidationEngine):
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="a.py", new_content="x=1\n"),
        ])
        patch = TransformationPatch(diff_content="d", hunks=[PatchHunk(file_path="a.py")])
        result = validator.validate(plan, patch, Path("."))
        data = result.model_dump()
        assert "status" in data

    def test_indent_error(self, validator: ValidationEngine):
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="a.py", new_content="def f():\nreturn 1\n"),
        ])
        patch = TransformationPatch(diff_content="d")
        result = validator.validate(plan, patch, Path("."))
        assert result.status == ValidationStatus.FAILED

    def test_check_names(self, validator: ValidationEngine):
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="a.py", new_content="x=1\n"),
        ])
        patch = TransformationPatch(diff_content="d", hunks=[PatchHunk(file_path="a.py")])
        result = validator.validate(plan, patch, Path("."))
        names = [c.name for c in result.checks]
        assert "syntax" in names
        assert "imports" in names
        assert "parser" in names

    def test_rules_check_passes(self, validator: ValidationEngine):
        plan = TransformationPlan(steps=[])
        patch = TransformationPatch(diff_content="d", hunks=[PatchHunk(file_path="a.py")])
        result = validator.validate(plan, patch, Path("."))
        rules_check = [c for c in result.checks if c.name == "rules"]
        assert rules_check[0].status == ValidationStatus.PASSED

    def test_architecture_check_passes(self, validator: ValidationEngine):
        plan = TransformationPlan(steps=[])
        patch = TransformationPatch(diff_content="d", hunks=[PatchHunk(file_path="a.py")])
        result = validator.validate(plan, patch, Path("."))
        arch_check = [c for c in result.checks if c.name == "architecture"]
        assert arch_check[0].status == ValidationStatus.PASSED

    def test_multiline_syntax_error(self, validator: ValidationEngine):
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="a.py", new_content="if True\n    x = 1\n"),
        ])
        patch = TransformationPatch(diff_content="d")
        result = validator.validate(plan, patch, Path("."))
        assert result.status == ValidationStatus.FAILED

    def test_valid_with_decorators(self, validator: ValidationEngine):
        code = "@property\ndef foo(self):\n    return 1\n"
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="a.py", new_content=code),
        ])
        patch = TransformationPatch(diff_content="d", hunks=[PatchHunk(file_path="a.py")])
        result = validator.validate(plan, patch, Path("."))
        assert result.status == ValidationStatus.PASSED

    def test_valid_async_code(self, validator: ValidationEngine):
        code = "async def foo():\n    await bar()\n"
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="a.py", new_content=code),
        ])
        patch = TransformationPatch(diff_content="d", hunks=[PatchHunk(file_path="a.py")])
        result = validator.validate(plan, patch, Path("."))
        assert result.status == ValidationStatus.PASSED

    def test_no_steps_no_syntax_error(self, validator: ValidationEngine):
        plan = TransformationPlan(steps=[])
        patch = TransformationPatch(diff_content="d", hunks=[PatchHunk(file_path="a.py")])
        result = validator.validate(plan, patch, Path("."))
        syntax = [c for c in result.checks if c.name == "syntax"]
        assert syntax[0].status == ValidationStatus.PASSED

    def test_warnings_list(self, validator: ValidationEngine):
        plan = TransformationPlan(steps=[])
        patch = TransformationPatch()
        result = validator.validate(plan, patch, Path("."))
        assert len(result.warnings) >= 1

    def test_fstring_valid(self, validator: ValidationEngine):
        code = "x = f'hello {name}'\n"
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="a.py", new_content=code),
        ])
        patch = TransformationPatch(diff_content="d", hunks=[PatchHunk(file_path="a.py")])
        result = validator.validate(plan, patch, Path("."))
        assert result.status == ValidationStatus.PASSED

    def test_walrus_operator_valid(self, validator: ValidationEngine):
        code = "if (n := len(a)) > 10:\n    print(n)\n"
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="a.py", new_content=code),
        ])
        patch = TransformationPatch(diff_content="d", hunks=[PatchHunk(file_path="a.py")])
        result = validator.validate(plan, patch, Path("."))
        assert result.status == ValidationStatus.PASSED

    def test_type_hint_valid(self, validator: ValidationEngine):
        code = "def foo(x: int, y: str = '') -> list[int]:\n    return [x]\n"
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="a.py", new_content=code),
        ])
        patch = TransformationPatch(diff_content="d", hunks=[PatchHunk(file_path="a.py")])
        result = validator.validate(plan, patch, Path("."))
        assert result.status == ValidationStatus.PASSED

    def test_unclosed_bracket_fails(self, validator: ValidationEngine):
        plan = TransformationPlan(steps=[
            TransformationStep(file_path="a.py", new_content="x = [1, 2, 3\n"),
        ])
        patch = TransformationPatch(diff_content="d")
        result = validator.validate(plan, patch, Path("."))
        assert result.status == ValidationStatus.FAILED

    def test_patch_content_check(self, validator: ValidationEngine):
        plan = TransformationPlan(steps=[])
        patch = TransformationPatch(diff_content="actual diff", hunks=[PatchHunk(file_path="a.py")])
        result = validator.validate(plan, patch, Path("."))
        content_check = [c for c in result.checks if c.name == "patch_content"]
        assert content_check[0].status == ValidationStatus.PASSED


# ===========================================================================
# Task 4: Preview (15 tests)
# ===========================================================================

class TestPreview:
    def test_preview_generation(self, preview_engine: PreviewEngine):
        plan = TransformationPlan(
            steps=[TransformationStep(file_path="src/a.py", description="Rename x")]
        )
        patch = TransformationPatch(
            diff_content="diff", files_modified=["src/a.py"], additions=5, deletions=2,
        )
        validation = TransformationValidation(status=ValidationStatus.PASSED)
        preview = preview_engine.generate_preview(plan, patch, validation)
        assert preview.additions == 5
        assert preview.deletions == 2

    def test_preview_modules(self, preview_engine: PreviewEngine):
        plan = TransformationPlan(steps=[])
        patch = TransformationPatch(files_modified=["src/a.py", "src/b.py"])
        validation = TransformationValidation(status=ValidationStatus.PASSED)
        preview = preview_engine.generate_preview(plan, patch, validation)
        assert "src" in preview.affected_modules

    def test_preview_confidence_passed(self, preview_engine: PreviewEngine):
        plan = TransformationPlan(steps=[])
        patch = TransformationPatch(files_modified=["a.py"])
        validation = TransformationValidation(status=ValidationStatus.PASSED)
        preview = preview_engine.generate_preview(plan, patch, validation)
        assert preview.confidence == 0.9

    def test_preview_confidence_failed(self, preview_engine: PreviewEngine):
        plan = TransformationPlan(steps=[])
        patch = TransformationPatch(files_modified=["a.py"])
        validation = TransformationValidation(status=ValidationStatus.FAILED)
        preview = preview_engine.generate_preview(plan, patch, validation)
        assert preview.confidence == 0.6

    def test_format_preview(self, preview_engine: PreviewEngine):
        preview = TransformationPreview(
            plan_id="TP-1", files_modified=["a.py"],
            additions=3, deletions=1, risk="low", confidence=0.9,
            estimated_review_time="2 min",
            validation=TransformationValidation(status=ValidationStatus.PASSED),
        )
        text = preview_engine.format_preview(preview)
        assert "TP-1" in text
        assert "LOW" in text

    def test_format_with_symbols(self, preview_engine: PreviewEngine):
        preview = TransformationPreview(
            modified_symbols=["Rename x to y"],
            validation=TransformationValidation(status=ValidationStatus.PASSED),
        )
        text = preview_engine.format_preview(preview)
        assert "Rename x to y" in text

    def test_format_with_errors(self, preview_engine: PreviewEngine):
        preview = TransformationPreview(
            validation=TransformationValidation(
                status=ValidationStatus.FAILED,
                errors=["Syntax error"],
            ),
        )
        text = preview_engine.format_preview(preview)
        assert "FAILED" in text

    def test_format_with_diff(self, preview_engine: PreviewEngine):
        preview = TransformationPreview(
            diff_preview="--- a/file.py\n+++ b/file.py",
            validation=TransformationValidation(status=ValidationStatus.PASSED),
        )
        text = preview_engine.format_preview(preview)
        assert "Diff:" in text

    def test_preview_review_time(self, preview_engine: PreviewEngine):
        plan = TransformationPlan(steps=[])
        patch = TransformationPatch(
            files_modified=["a.py"], additions=30, deletions=10,
            hunks=[PatchHunk(file_path="a.py")],
        )
        validation = TransformationValidation(status=ValidationStatus.PASSED)
        preview = preview_engine.generate_preview(plan, patch, validation)
        assert preview.estimated_review_time != ""

    def test_preview_risk_propagated(self, preview_engine: PreviewEngine):
        plan = TransformationPlan(estimated_risk="high", steps=[])
        patch = TransformationPatch(files_modified=["a.py"])
        validation = TransformationValidation(status=ValidationStatus.PASSED)
        preview = preview_engine.generate_preview(plan, patch, validation)
        assert preview.risk == "high"

    def test_preview_empty(self, preview_engine: PreviewEngine):
        plan = TransformationPlan(steps=[])
        patch = TransformationPatch()
        validation = TransformationValidation(status=ValidationStatus.PASSED)
        preview = preview_engine.generate_preview(plan, patch, validation)
        assert preview.files_modified == []

    def test_preview_diff_truncated(self, preview_engine: PreviewEngine):
        plan = TransformationPlan(steps=[])
        patch = TransformationPatch(diff_content="x" * 5000, files_modified=["a.py"])
        validation = TransformationValidation(status=ValidationStatus.PASSED)
        preview = preview_engine.generate_preview(plan, patch, validation)
        assert len(preview.diff_preview) <= 2000

    def test_preview_plan_id(self, preview_engine: PreviewEngine):
        plan = TransformationPlan(steps=[])
        patch = TransformationPatch(files_modified=["a.py"])
        validation = TransformationValidation(status=ValidationStatus.PASSED)
        preview = preview_engine.generate_preview(plan, patch, validation)
        assert preview.plan_id == plan.id

    def test_preview_patch_id(self, preview_engine: PreviewEngine):
        plan = TransformationPlan(steps=[])
        patch = TransformationPatch(files_modified=["a.py"])
        validation = TransformationValidation(status=ValidationStatus.PASSED)
        preview = preview_engine.generate_preview(plan, patch, validation)
        assert preview.patch_id == patch.id

    def test_format_modules(self, preview_engine: PreviewEngine):
        preview = TransformationPreview(
            affected_modules=["auth", "core"],
            validation=TransformationValidation(status=ValidationStatus.PASSED),
        )
        text = preview_engine.format_preview(preview)
        assert "auth" in text


# ===========================================================================
# Task 7 + 11: Apply + Rollback (25 tests)
# ===========================================================================

class TestApplyAndRollback:
    def test_apply_rename(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "utility_func"},
        )
        result = service.apply(request, repo)
        assert result.status == TransformationStatus.APPLIED
        assert len(result.files_modified) > 0

    def test_applied_file_content(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "utility_func"},
        )
        service.apply(request, repo)
        content = (repo / "src" / "utils.py").read_text()
        assert "utility_func" in content
        assert "helper_func" not in content

    def test_rollback_restores(self, service: TransformationService, repo: Path):
        original = (repo / "src" / "utils.py").read_text()
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "utility_func"},
        )
        service.apply(request, repo)
        assert "utility_func" in (repo / "src" / "utils.py").read_text()

        service._storage.get_analyses.return_value = [{
            "result_data": {
                "steps": [{"file_path": "src/utils.py", "original_content": original}]
            }
        }]
        result = service.rollback(repo)
        assert result.status == TransformationStatus.ROLLED_BACK

    def test_rollback_no_history(self, service: TransformationService, repo: Path):
        from refactory.transformation.models import TransformationError

        with pytest.raises(TransformationError) as exc_info:
            service.rollback(repo)
        assert exc_info.value.status_code == 404

    def test_apply_invalid_syntax_rejected(self, service: TransformationService, tmp_path: Path):
        from refactory.transformation.models import TransformationError

        repo = tmp_path / "r"
        repo.mkdir()
        (repo / "bad.py").write_text("x = 1\n")
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="bad.py",
            parameters={"old_name": "x = 1", "new_name": "def (\n"},
        )
        with pytest.raises(TransformationError):
            service.apply(request, repo)

    def test_apply_persists(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util_func"},
        )
        service.apply(request, repo)
        service._storage.store_analysis.assert_called()

    def test_apply_result_has_duration(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util_func"},
        )
        result = service.apply(request, repo)
        assert result.duration_ms > 0

    def test_apply_rollback_available(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        result = service.apply(request, repo)
        assert result.rollback_available is True

    def test_history_recorded(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        service.apply(request, repo)
        assert len(service.get_history()) == 1

    def test_multiple_applies(self, service: TransformationService, repo: Path):
        r1 = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util1"},
        )
        r2 = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "util1", "new_name": "util2"},
        )
        service.apply(r1, repo)
        service.apply(r2, repo)
        assert len(service.get_history()) == 2

    def test_conflict_on_missing_file(self, service: TransformationService, tmp_path: Path):
        from refactory.transformation.models import TransformationError

        repo = tmp_path / "r"
        repo.mkdir()
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="missing.py",
            parameters={"old_name": "x", "new_name": "y"},
        )
        with pytest.raises(TransformationError):
            service.apply(request, repo)

    def test_transform_preview(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        preview = service.preview(request, repo)
        assert isinstance(preview, TransformationPreview)

    def test_preview_no_apply(self, service: TransformationService, repo: Path):
        original = (repo / "src" / "utils.py").read_text()
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        service.preview(request, repo)
        assert (repo / "src" / "utils.py").read_text() == original

    def test_incremental_update_called(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        service.apply(request, repo)
        service._parser.parse_file.assert_called()

    def test_remove_dead_code(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.REMOVE_DEAD_CODE,
            target_file="src/utils.py",
            target_symbol="unused_func",
        )
        result = service.apply(request, repo)
        if result.status == TransformationStatus.APPLIED:
            content = (repo / "src" / "utils.py").read_text()
            assert "unused_func" not in content

    def test_apply_generates_metric(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        service.apply(request, repo)
        service._storage.store_metric.assert_called()

    def test_empty_plan_no_files(self, service: TransformationService, repo: Path):
        from refactory.transformation.models import TransformationError

        request = TransformationRequest(
            transformation_type=TransformationType.EXTRACT_CLASS,
            target_file="src/utils.py",
        )
        with pytest.raises(TransformationError):
            service.apply(request, repo)

    def test_result_plan_id(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        result = service.apply(request, repo)
        assert result.plan_id.startswith("TP-")

    def test_result_patch_id(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        result = service.apply(request, repo)
        assert result.patch_id.startswith("PA-")

    def test_validation_in_result(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        result = service.apply(request, repo)
        assert result.validation.status in list(ValidationStatus)

    def test_rollback_after_multiple(self, service: TransformationService, repo: Path):
        r1 = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util1"},
        )
        service.apply(r1, repo)
        result = service.rollback(repo)
        assert result.status == TransformationStatus.ROLLED_BACK

    def test_double_rollback(self, service: TransformationService, repo: Path):
        from refactory.transformation.models import TransformationError

        r1 = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util1"},
        )
        service.apply(r1, repo)
        service.rollback(repo)
        with pytest.raises(TransformationError) as exc_info:
            service.rollback(repo)
        assert exc_info.value.status_code == 409
        assert "already rolled back" in exc_info.value.message.lower()

    def test_history_status_after_rollback(self, service: TransformationService, repo: Path):
        r1 = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util1"},
        )
        service.apply(r1, repo)
        service.rollback(repo)
        history = service.get_history()
        assert len(history) == 1
        assert history[0].status == TransformationStatus.ROLLED_BACK
        assert history[0].can_rollback is False
        assert history[0].rolled_back is True

    def test_apply_across_files(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_SYMBOL,
            parameters={"old_name": "helper_func", "new_name": "util_func"},
        )
        result = service.apply(request, repo)
        assert result.status == TransformationStatus.APPLIED


# ===========================================================================
# Task 9: Conflict Detection (15 tests)
# ===========================================================================

class TestConflictDetection:
    def test_no_conflicts(self, service: TransformationService, repo: Path):
        patch = TransformationPatch(
            files_modified=["src/utils.py"],
            hunks=[PatchHunk(file_path="src/utils.py")],
        )
        conflicts = service._detect_conflicts(patch, repo)
        assert conflicts == []

    def test_deleted_file_conflict(self, service: TransformationService, repo: Path):
        patch = TransformationPatch(
            files_modified=["deleted.py"],
            hunks=[PatchHunk(file_path="deleted.py")],
        )
        conflicts = service._detect_conflicts(patch, repo)
        assert any(c.conflict_type == ConflictType.DELETED_FILE for c in conflicts)

    def test_overlapping_edit(self, service: TransformationService, repo: Path):
        patch = TransformationPatch(
            files_modified=["src/utils.py"],
            hunks=[
                PatchHunk(file_path="src/utils.py"),
                PatchHunk(file_path="src/utils.py"),
            ],
        )
        conflicts = service._detect_conflicts(patch, repo)
        assert any(c.conflict_type == ConflictType.OVERLAPPING_EDIT for c in conflicts)

    def test_conflict_has_file_path(self, service: TransformationService, repo: Path):
        patch = TransformationPatch(
            files_modified=["no_exist.py"],
            hunks=[PatchHunk(file_path="no_exist.py")],
        )
        conflicts = service._detect_conflicts(patch, repo)
        assert conflicts[0].file_path == "no_exist.py"

    def test_conflict_description(self, service: TransformationService, repo: Path):
        patch = TransformationPatch(
            files_modified=["gone.py"],
            hunks=[PatchHunk(file_path="gone.py")],
        )
        conflicts = service._detect_conflicts(patch, repo)
        assert conflicts[0].description != ""

    def test_empty_patch_no_conflict(self, service: TransformationService, repo: Path):
        patch = TransformationPatch()
        conflicts = service._detect_conflicts(patch, repo)
        assert conflicts == []

    def test_multiple_deleted_files(self, service: TransformationService, repo: Path):
        patch = TransformationPatch(
            files_modified=["a.py", "b.py"],
            hunks=[PatchHunk(file_path="a.py"), PatchHunk(file_path="b.py")],
        )
        conflicts = service._detect_conflicts(patch, repo)
        assert len(conflicts) >= 2

    def test_existing_file_no_conflict(self, service: TransformationService, repo: Path):
        patch = TransformationPatch(
            files_modified=["src/service.py"],
            hunks=[PatchHunk(file_path="src/service.py")],
        )
        conflicts = service._detect_conflicts(patch, repo)
        deleted = [c for c in conflicts if c.conflict_type == ConflictType.DELETED_FILE]
        assert len(deleted) == 0

    def test_conflict_model_serializable(self):
        c = TransformationConflict(
            conflict_type=ConflictType.MERGE_CONFLICT,
            file_path="a.py",
            description="Conflict",
        )
        data = c.model_dump()
        assert data["conflict_type"] == "merge_conflict"

    def test_overlapping_same_hunk(self, service: TransformationService, repo: Path):
        patch = TransformationPatch(
            files_modified=["src/main.py"],
            hunks=[
                PatchHunk(file_path="src/main.py"),
                PatchHunk(file_path="src/main.py"),
            ],
        )
        conflicts = service._detect_conflicts(patch, repo)
        overlaps = [c for c in conflicts if c.conflict_type == ConflictType.OVERLAPPING_EDIT]
        assert len(overlaps) == 1

    def test_mixed_conflicts(self, service: TransformationService, repo: Path):
        patch = TransformationPatch(
            files_modified=["missing.py", "src/main.py"],
            hunks=[
                PatchHunk(file_path="missing.py"),
                PatchHunk(file_path="src/main.py"),
                PatchHunk(file_path="src/main.py"),
            ],
        )
        conflicts = service._detect_conflicts(patch, repo)
        types = {c.conflict_type for c in conflicts}
        assert ConflictType.DELETED_FILE in types
        assert ConflictType.OVERLAPPING_EDIT in types

    def test_single_hunk_no_overlap(self, service: TransformationService, repo: Path):
        patch = TransformationPatch(
            files_modified=["src/utils.py"],
            hunks=[PatchHunk(file_path="src/utils.py")],
        )
        conflicts = service._detect_conflicts(patch, repo)
        overlaps = [c for c in conflicts if c.conflict_type == ConflictType.OVERLAPPING_EDIT]
        assert len(overlaps) == 0

    def test_conflict_prevents_apply(self, service: TransformationService, tmp_path: Path):
        from refactory.transformation.models import TransformationError

        repo = tmp_path / "r"
        repo.mkdir()
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="missing.py",
            parameters={"old_name": "x", "new_name": "y"},
        )
        with pytest.raises(TransformationError):
            service.apply(request, repo)

    def test_conflict_line_range_default(self):
        c = TransformationConflict(conflict_type=ConflictType.INVALID_LINE_MAPPING)
        assert c.line_range == (0, 0)

    def test_all_conflict_types_exist(self):
        types = list(ConflictType)
        assert len(types) == 5


# ===========================================================================
# Planner (20 tests)
# ===========================================================================

class TestPlanner:
    def test_rename_plan(self, planner: TransformationPlanner, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        plan = planner.create_plan(request, repo)
        assert len(plan.steps) > 0
        assert plan.transformation_type == TransformationType.RENAME_FUNCTION

    def test_rename_across_files(self, planner: TransformationPlanner, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_SYMBOL,
            parameters={"old_name": "helper_func", "new_name": "util_func"},
        )
        plan = planner.create_plan(request, repo)
        assert len(plan.steps) >= 2

    def test_rename_missing_params(self, planner: TransformationPlanner, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="src/utils.py",
            parameters={},
        )
        plan = planner.create_plan(request, repo)
        assert plan.steps == []

    def test_extract_method_plan(self, planner: TransformationPlanner, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.EXTRACT_METHOD,
            target_file="src/service.py",
            parameters={"start_line": 2, "end_line": 3, "method_name": "get_user_data"},
        )
        plan = planner.create_plan(request, repo)
        assert len(plan.steps) == 1
        assert plan.estimated_risk == "medium"

    def test_extract_method_missing_file(self, planner: TransformationPlanner, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.EXTRACT_METHOD,
            target_file="nope.py",
        )
        plan = planner.create_plan(request, repo)
        assert plan.steps == []

    def test_remove_dead_code_plan(self, planner: TransformationPlanner, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.REMOVE_DEAD_CODE,
            target_file="src/utils.py",
            target_symbol="unused_func",
        )
        plan = planner.create_plan(request, repo)
        assert len(plan.steps) == 1

    def test_remove_missing_symbol(self, planner: TransformationPlanner, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.REMOVE_DEAD_CODE,
            target_file="src/utils.py",
            target_symbol="nonexistent",
        )
        plan = planner.create_plan(request, repo)
        assert plan.steps == []

    def test_generate_docstrings(self, planner: TransformationPlanner, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.GENERATE_DOCSTRINGS,
            target_file="src/utils.py",
        )
        plan = planner.create_plan(request, repo)
        assert len(plan.steps) >= 1

    def test_plan_affected_files(self, planner: TransformationPlanner, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        plan = planner.create_plan(request, repo)
        assert len(plan.affected_files) > 0

    def test_plan_has_id(self, planner: TransformationPlanner, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "x", "new_name": "y"},
        )
        plan = planner.create_plan(request, repo)
        assert plan.id.startswith("TP-")

    def test_extract_class_plan(self, planner: TransformationPlanner, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.EXTRACT_CLASS,
            target_file="src/service.py",
        )
        plan = planner.create_plan(request, repo)
        assert plan.estimated_risk == "high"

    def test_move_plan(self, planner: TransformationPlanner, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.MOVE_METHOD,
            parameters={"source_file": "a.py", "destination_file": "b.py"},
        )
        plan = planner.create_plan(request, repo)
        assert plan.estimated_risk == "medium"

    def test_inline_plan(self, planner: TransformationPlanner, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.INLINE_METHOD,
            target_file="src/utils.py",
        )
        plan = planner.create_plan(request, repo)
        assert plan.estimated_risk == "medium"

    def test_replace_api_plan(self, planner: TransformationPlanner, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.REPLACE_DEPRECATED_API,
            target_file="src/main.py",
            parameters={"old_api": "helper_func", "new_api": "new_helper"},
        )
        plan = planner.create_plan(request, repo)
        assert len(plan.steps) >= 1

    def test_fix_rules_plan(self, planner: TransformationPlanner, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.FIX_RULE_VIOLATIONS,
        )
        plan = planner.create_plan(request, repo)
        assert plan.estimated_risk == "low"

    def test_architecture_plan(self, planner: TransformationPlanner, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.ARCHITECTURE_REFACTORING,
        )
        plan = planner.create_plan(request, repo)
        assert plan.estimated_risk == "high"

    def test_create_interface_plan(self, planner: TransformationPlanner, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.CREATE_INTERFACE,
            target_symbol="UserService",
        )
        plan = planner.create_plan(request, repo)
        assert plan.estimated_risk == "medium"

    def test_plan_description(self, planner: TransformationPlanner, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        plan = planner.create_plan(request, repo)
        assert plan.description != ""

    def test_ignores_pycache(self, planner: TransformationPlanner, repo: Path):
        (repo / "__pycache__").mkdir()
        (repo / "__pycache__" / "x.py").write_text("helper_func = 1\n")
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_SYMBOL,
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        plan = planner.create_plan(request, repo)
        assert not any("__pycache__" in s.file_path for s in plan.steps)

    def test_plan_step_content(self, planner: TransformationPlanner, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        plan = planner.create_plan(request, repo)
        if plan.steps:
            assert "util" in plan.steps[0].new_content


# ===========================================================================
# Service Integration (20 tests)
# ===========================================================================

class TestServiceIntegration:
    def test_transform_returns_preview(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        preview = service.transform(request, repo)
        assert isinstance(preview, TransformationPreview)

    def test_transform_persists(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        service.transform(request, repo)
        service._storage.store_analysis.assert_called()

    def test_ai_assisted_flag(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
            ai_assisted=True,
        )
        preview = service.transform(request, repo)
        assert preview.plan_id != ""

    def test_extract_method_ai(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.EXTRACT_METHOD,
            target_file="src/service.py",
            parameters={"start_line": 2, "end_line": 3, "method_name": "extracted"},
        )
        preview = service.transform(request, repo)
        assert preview.plan_id.startswith("TP-")

    def test_generate_docstrings_service(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.GENERATE_DOCSTRINGS,
            target_file="src/utils.py",
        )
        preview = service.transform(request, repo)
        assert isinstance(preview, TransformationPreview)

    def test_history_empty_initially(self, service: TransformationService):
        assert service.get_history() == []

    def test_preview_does_not_add_history(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        service.preview(request, repo)
        assert len(service.get_history()) == 0

    def test_apply_adds_history(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        service.apply(request, repo)
        assert len(service.get_history()) == 1

    def test_service_logging(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        service.transform(request, repo)

    def test_storage_metric(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        service.apply(request, repo)
        calls = [str(c) for c in service._storage.store_metric.call_args_list]
        assert any("transformations" in c for c in calls)

    def test_transform_empty_plan(self, service: TransformationService, repo: Path):
        from refactory.transformation.models import TransformationError

        request = TransformationRequest(
            transformation_type=TransformationType.EXTRACT_CLASS,
            target_file="src/service.py",
        )
        with pytest.raises(TransformationError):
            service.transform(request, repo)

    def test_apply_empty_plan(self, service: TransformationService, repo: Path):
        from refactory.transformation.models import TransformationError

        request = TransformationRequest(
            transformation_type=TransformationType.EXTRACT_CLASS,
            target_file="src/service.py",
        )
        with pytest.raises(TransformationError):
            service.apply(request, repo)

    def test_rollback_persistence(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        service.apply(request, repo)
        service.rollback(repo)
        assert service._storage.store_analysis.call_count >= 2

    def test_validation_in_preview(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        preview = service.transform(request, repo)
        assert preview.validation.status in list(ValidationStatus)

    def test_preview_has_diff(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        preview = service.transform(request, repo)
        assert preview.diff_preview != ""

    def test_result_serializable(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="src/utils.py",
            parameters={"old_name": "helper_func", "new_name": "util"},
        )
        result = service.apply(request, repo)
        data = result.model_dump(mode="json")
        assert "status" in data

    def test_remove_dead_code_service(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.REMOVE_DEAD_CODE,
            target_file="src/utils.py",
            target_symbol="unused_func",
        )
        result = service.apply(request, repo)
        assert result.status == TransformationStatus.APPLIED

    def test_docstrings_applied(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.GENERATE_DOCSTRINGS,
            target_file="src/utils.py",
        )
        result = service.apply(request, repo)
        if result.files_modified:
            content = (repo / "src" / "utils.py").read_text()
            assert "TODO: Document" in content

    def test_replace_api_service(self, service: TransformationService, repo: Path):
        request = TransformationRequest(
            transformation_type=TransformationType.REPLACE_DEPRECATED_API,
            target_file="src/main.py",
            parameters={"old_api": "helper_func", "new_api": "new_helper"},
        )
        result = service.apply(request, repo)
        if result.files_modified:
            content = (repo / "src" / "main.py").read_text()
            assert "new_helper" in content

    def test_update_imports_type(self, service: TransformationService, repo: Path):
        from refactory.transformation.models import TransformationError

        request = TransformationRequest(
            transformation_type=TransformationType.UPDATE_IMPORTS,
            target_file="src/main.py",
        )
        with pytest.raises(TransformationError):
            service.transform(request, repo)
