"""Tests for Phase 5: CT-2 (AST Rename) + CT-3 (AST Extract Method)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from refactory.transformation.models import TransformationRequest, TransformationType
from refactory.transformation.planner import TransformationPlanner


def _logger():
    from loguru import logger
    return logger


@pytest.fixture
def planner():
    return TransformationPlanner(_logger())


# ===========================================================================
# CT-2: Real AST-based Rename Symbol
# ===========================================================================

class TestASTRename:
    def test_rename_function_def(self, planner: TransformationPlanner, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "mod.py").write_text("def old_func():\n    return 1\n\nx = old_func()\n")
        req = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="mod.py",
            parameters={"old_name": "old_func", "new_name": "new_func"},
        )
        plan = planner.create_plan(req, repo)
        assert len(plan.steps) == 1
        new = plan.steps[0].new_content
        assert "def new_func()" in new
        assert "x = new_func()" in new
        assert "old_func" not in new
        ast.parse(new)

    def test_rename_preserves_strings(self, planner: TransformationPlanner, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "mod.py").write_text(
            'def calculate():\n    msg = "calculate total"\n    return msg\n\ncalculate()\n'
        )
        req = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="mod.py",
            parameters={"old_name": "calculate", "new_name": "compute"},
        )
        plan = planner.create_plan(req, repo)
        new = plan.steps[0].new_content
        assert "def compute()" in new
        assert "compute()" in new
        ast.parse(new)

    def test_rename_class(self, planner: TransformationPlanner, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "mod.py").write_text("class OldName:\n    pass\n\nobj = OldName()\n")
        req = TransformationRequest(
            transformation_type=TransformationType.RENAME_CLASS,
            target_file="mod.py",
            parameters={"old_name": "OldName", "new_name": "NewName"},
        )
        plan = planner.create_plan(req, repo)
        new = plan.steps[0].new_content
        assert "class NewName:" in new
        assert "obj = NewName()" in new
        assert "OldName" not in new
        ast.parse(new)

    def test_rename_variable(self, planner: TransformationPlanner, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "mod.py").write_text("old_var = 42\nprint(old_var)\n")
        req = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="mod.py",
            parameters={"old_name": "old_var", "new_name": "new_var"},
        )
        plan = planner.create_plan(req, repo)
        new = plan.steps[0].new_content
        assert "new_var = 42" in new
        assert "print(new_var)" in new
        ast.parse(new)

    def test_rename_attribute(self, planner: TransformationPlanner, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "mod.py").write_text(
            "class Svc:\n    def old_method(self):\n        pass\n\ns = Svc()\ns.old_method()\n"
        )
        req = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="mod.py",
            parameters={"old_name": "old_method", "new_name": "new_method"},
        )
        plan = planner.create_plan(req, repo)
        new = plan.steps[0].new_content
        assert "def new_method(self)" in new
        assert "s.new_method()" in new
        ast.parse(new)

    def test_rename_across_files(self, planner: TransformationPlanner, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "a.py").write_text("def shared():\n    pass\n")
        (repo / "b.py").write_text("from a import shared\nshared()\n")
        req = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            parameters={"old_name": "shared", "new_name": "common"},
        )
        plan = planner.create_plan(req, repo)
        assert len(plan.steps) == 2
        for step in plan.steps:
            assert "common" in step.new_content
            ast.parse(step.new_content)

    def test_rename_no_match(self, planner: TransformationPlanner, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "mod.py").write_text("x = 1\n")
        req = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="mod.py",
            parameters={"old_name": "nonexistent", "new_name": "something"},
        )
        plan = planner.create_plan(req, repo)
        assert len(plan.steps) == 0

    def test_rename_parameter(self, planner: TransformationPlanner, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "mod.py").write_text("def greet(old_param):\n    return old_param\n")
        req = TransformationRequest(
            transformation_type=TransformationType.RENAME_VARIABLE,
            target_file="mod.py",
            parameters={"old_name": "old_param", "new_name": "new_param"},
        )
        plan = planner.create_plan(req, repo)
        new = plan.steps[0].new_content
        assert "new_param" in new
        ast.parse(new)

    def test_rename_valid_python_output(self, planner: TransformationPlanner, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        code = (
            "class Calculator:\n"
            "    def add(self, a, b):\n"
            "        return a + b\n"
            "\n"
            "c = Calculator()\n"
            "result = c.add(1, 2)\n"
        )
        (repo / "calc.py").write_text(code)
        req = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="calc.py",
            parameters={"old_name": "add", "new_name": "sum_values"},
        )
        plan = planner.create_plan(req, repo)
        new = plan.steps[0].new_content
        ast.parse(new)
        assert "def sum_values(self" in new
        assert "c.sum_values(1, 2)" in new


# ===========================================================================
# CT-3: Real Extract Method Transformation
# ===========================================================================

class TestASTExtractMethod:
    def test_extract_basic(self, planner: TransformationPlanner, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        code = (
            "def process():\n"
            "    x = 1\n"
            "    y = 2\n"
            "    z = x + y\n"
            "    print(z)\n"
            "    return z\n"
        )
        (repo / "mod.py").write_text(code)
        req = TransformationRequest(
            transformation_type=TransformationType.EXTRACT_METHOD,
            target_file="mod.py",
            parameters={"start_line": 4, "end_line": 5, "method_name": "compute_and_print"},
        )
        plan = planner.create_plan(req, repo)
        assert len(plan.steps) == 1
        new = plan.steps[0].new_content
        assert "def compute_and_print(" in new
        assert "compute_and_print(" in new

    def test_extract_missing_lines_rejected(self, planner: TransformationPlanner, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "mod.py").write_text("x = 1\n")
        req = TransformationRequest(
            transformation_type=TransformationType.EXTRACT_METHOD,
            target_file="mod.py",
            parameters={"method_name": "extracted"},
        )
        plan = planner.create_plan(req, repo)
        assert len(plan.steps) == 0

    def test_extract_detects_used_variables(self, planner: TransformationPlanner, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        code = (
            "def main():\n"
            "    data = [1, 2, 3]\n"
            "    total = sum(data)\n"
            "    avg = total / len(data)\n"
            "    return avg\n"
        )
        (repo / "mod.py").write_text(code)
        req = TransformationRequest(
            transformation_type=TransformationType.EXTRACT_METHOD,
            target_file="mod.py",
            parameters={"start_line": 3, "end_line": 4, "method_name": "compute_avg"},
        )
        plan = planner.create_plan(req, repo)
        new = plan.steps[0].new_content
        assert "compute_avg(" in new

    def test_extract_invalid_range(self, planner: TransformationPlanner, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "mod.py").write_text("x = 1\n")
        req = TransformationRequest(
            transformation_type=TransformationType.EXTRACT_METHOD,
            target_file="mod.py",
            parameters={"start_line": 5, "end_line": 10, "method_name": "bad"},
        )
        plan = planner.create_plan(req, repo)
        assert len(plan.steps) == 0

    def test_extract_file_not_found(self, planner: TransformationPlanner, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        req = TransformationRequest(
            transformation_type=TransformationType.EXTRACT_METHOD,
            target_file="nonexistent.py",
            parameters={"start_line": 1, "end_line": 3, "method_name": "x"},
        )
        plan = planner.create_plan(req, repo)
        assert len(plan.steps) == 0

    def test_extract_places_call(self, planner: TransformationPlanner, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        code = (
            "a = 10\n"
            "b = 20\n"
            "c = a + b\n"
            "print(c)\n"
        )
        (repo / "mod.py").write_text(code)
        req = TransformationRequest(
            transformation_type=TransformationType.EXTRACT_METHOD,
            target_file="mod.py",
            parameters={"start_line": 3, "end_line": 4, "method_name": "add_and_print"},
        )
        plan = planner.create_plan(req, repo)
        new = plan.steps[0].new_content
        lines = new.split("\n")
        call_found = any("add_and_print(" in l for l in lines)
        assert call_found

    def test_extract_from_class_method(self, planner: TransformationPlanner, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        code = (
            "class Processor:\n"
            "    def run(self):\n"
            "        step1 = 'a'\n"
            "        step2 = 'b'\n"
            "        result = step1 + step2\n"
            "        return result\n"
        )
        (repo / "mod.py").write_text(code)
        req = TransformationRequest(
            transformation_type=TransformationType.EXTRACT_METHOD,
            target_file="mod.py",
            parameters={"start_line": 4, "end_line": 5, "method_name": "combine_steps"},
        )
        plan = planner.create_plan(req, repo)
        assert len(plan.steps) == 1
        new = plan.steps[0].new_content
        assert "combine_steps(" in new
