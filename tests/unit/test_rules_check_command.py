"""Tests for `refactory rules check` CLI (Feature 1)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from refactory.cli.app import app
from refactory.cli.commands.rules import _render_gate_result
from refactory.company.models import (
    CompanyRuleViolation,
    GateOutcome,
    GateResult,
)


runner = CliRunner()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _mock_container(checker_result: GateResult, *, root: Path):
    container = MagicMock()
    container.company_rules_checker.check.return_value = checker_result

    repo = MagicMock()
    repo.root_path = str(root)
    repo.name = "test-repo"
    repo.default_branch = "main"
    repo.remote_url = None
    container.git_service.get_repository_metadata.return_value = repo
    container.git_service.get_current_branch.return_value = "feature/ABC-1-login"
    container.git_service.get_default_branch.return_value = "main"
    container.git_service.get_head_sha.return_value = "abc1234"
    commit = MagicMock()
    commit.message = "feat: login"
    commit.sha = "abc1234"
    container.git_service.get_current_commit.return_value = commit
    container.git_service.get_commits_since_ref.return_value = [commit]
    container.git_service.get_changed_files_vs_default_branch.return_value = []
    container.git_service.get_changed_files_vs_ref.return_value = []
    container.git_service.get_working_tree_status.return_value = MagicMock(
        staged_files=[],
        modified_files=[],
        deleted_files=[],
        renamed_files=[],
        untracked_files=[],
    )
    container.persistence_service.get_or_create_repository.return_value = {"id": "r1"}
    container.persistence_service.persist_analysis_run.return_value = {"id": "a1"}
    return container


class TestRulesCheckExitCodes:
    def test_pass_exits_zero(self, tmp_path: Path):
        (tmp_path / ".refactory").mkdir()
        result = GateResult(outcome=GateOutcome.PASS)
        container = _mock_container(result, root=tmp_path)

        with patch("refactory.cli.commands.rules.get_container", return_value=container):
            completed = runner.invoke(app, ["rules", "check", "--root", str(tmp_path)])

        assert completed.exit_code == 0
        assert "PASS" in completed.stdout
        container.company_rules_checker.check.assert_called_once()

    def test_warn_exits_zero(self, tmp_path: Path):
        (tmp_path / ".refactory").mkdir()
        result = GateResult(
            outcome=GateOutcome.WARN,
            violations=[
                CompanyRuleViolation(
                    rule="require_tests",
                    message="Missing tests",
                    blocking=False,
                    severity="warning",
                )
            ],
        )
        container = _mock_container(result, root=tmp_path)

        with patch("refactory.cli.commands.rules.get_container", return_value=container):
            completed = runner.invoke(app, ["rules", "check", "--root", str(tmp_path)])

        assert completed.exit_code == 0
        assert "WARN" in completed.stdout
        assert "require_tests" in completed.stdout

    def test_block_exits_one(self, tmp_path: Path):
        (tmp_path / ".refactory").mkdir()
        result = GateResult(
            outcome=GateOutcome.BLOCK,
            violations=[
                CompanyRuleViolation(
                    rule="branch_naming",
                    message="Branch must match pattern",
                    blocking=True,
                    severity="error",
                    detail="Expected pattern: ^feature/.*",
                )
            ],
        )
        container = _mock_container(result, root=tmp_path)

        with patch("refactory.cli.commands.rules.get_container", return_value=container):
            completed = runner.invoke(app, ["rules", "check", "--root", str(tmp_path)])

        assert completed.exit_code == 1
        assert "BLOCK" in completed.stdout
        assert "branch_naming" in completed.stdout


class TestRulesCheckOverrides:
    def test_branch_and_commit_flags_passed_to_checker(self, tmp_path: Path):
        (tmp_path / ".refactory").mkdir()
        result = GateResult(outcome=GateOutcome.PASS)
        container = _mock_container(result, root=tmp_path)

        with patch("refactory.cli.commands.rules.get_container", return_value=container):
            completed = runner.invoke(
                app,
                [
                    "rules",
                    "check",
                    "--root",
                    str(tmp_path),
                    "--branch",
                    "feature/login",
                    "--commit",
                    "fixed login",
                ],
            )

        assert completed.exit_code == 0
        kwargs = container.company_rules_checker.check.call_args
        assert kwargs.kwargs["branch_name"] == "feature/login"
        assert kwargs.kwargs["commit_message"] == "fixed login"

    def test_defaults_use_git_branch_and_commit(self, tmp_path: Path):
        (tmp_path / ".refactory").mkdir()
        result = GateResult(outcome=GateOutcome.PASS)
        container = _mock_container(result, root=tmp_path)

        with patch("refactory.cli.commands.rules.get_container", return_value=container):
            completed = runner.invoke(app, ["rules", "check", "--root", str(tmp_path)])

        assert completed.exit_code == 0
        kwargs = container.company_rules_checker.check.call_args
        assert kwargs.kwargs["branch_name"] == "feature/ABC-1-login"
        assert kwargs.kwargs["commit_message"] == "feat: login"


class TestRenderGateResult:
    def test_render_blockers_and_warnings(self):
        result = GateResult(
            outcome=GateOutcome.BLOCK,
            violations=[
                CompanyRuleViolation(
                    rule="branch_naming",
                    message="bad branch",
                    blocking=True,
                ),
                CompanyRuleViolation(
                    rule="require_tests",
                    message="add tests",
                    blocking=False,
                ),
            ],
        )
        # Should not raise
        _render_gate_result(result, branch_name="x", commit_message="y")


class TestContainerExposesChecker:
    def test_container_has_company_rules_checker(self):
        from refactory.core.container import ServiceContainer
        assert "company_rules_checker" in ServiceContainer.__dataclass_fields__
