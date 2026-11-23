"""Phase 8 Feature 2 — Persist company-rules / blocked-review gate results to DB.

Tests cover:
1. ReviewEngine._persist_gate_result stores analysis run for BLOCK/WARN/PASS.
2. ReviewEngine.review() persists gate result alongside blocked review.
3. ReviewEngine.review() persists gate result for successful (PASS/WARN) reviews.
4. CLI `rules check` persists gate result via _persist_gate_result.
5. Persistence failures never abort the review/CLI.
6. result_data structure matches expected schema.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from refactory.company.models import (
    CompanyGuidelines,
    CompanyRuleViolation,
    CompanyStandards,
    GateOutcome,
    GateResult,
)
from refactory.review.engine import ReviewEngine
from refactory.review.models import ReviewResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gate(outcome: GateOutcome, violations: list | None = None) -> GateResult:
    return GateResult(
        outcome=outcome,
        violations=violations or [],
        guidelines=CompanyGuidelines(),
        standards=CompanyStandards(),
    )


def _make_repository(name="test-repo", root_path="/tmp/test-repo"):
    repo = MagicMock()
    repo.name = name
    repo.root_path = root_path
    repo.default_branch = "main"
    repo.remote_url = "https://example.com/test-repo.git"
    repo.current_branch = "feature/test"
    return repo


def _make_pull_request(pr_number=42):
    pr = MagicMock()
    pr.number = pr_number
    pr.title = "feat: test PR"
    pr.body = "Test body"
    pr.state = "open"
    pr.base_branch = "main"
    pr.head_branch = "feature/test"
    pr.changed_files = []
    pr.diff = ""
    return pr


def _make_review_engine(
    *,
    persistence=None,
    company_rules_checker=None,
    gateway=None,
) -> ReviewEngine:
    git = MagicMock()
    github = MagicMock()
    parser = MagicMock()
    indexer = MagicMock()
    retrieval = MagicMock()
    ai = MagicMock()
    graph = MagicMock()
    prompt_builder = MagicMock()
    response_parser = MagicMock()

    gw = gateway or MagicMock()

    return ReviewEngine(
        git_service=git,
        github_service=github,
        parser_service=parser,
        indexer_service=indexer,
        retrieval_service=retrieval,
        ai_service=ai,
        logger=MagicMock(),
        graph_service=graph,
        prompt_builder=prompt_builder,
        ai_gateway=gw,
        response_parser=response_parser,
        persistence_service=persistence,
        company_rules_checker=company_rules_checker,
    )


# ---------------------------------------------------------------------------
# 1. _persist_gate_result unit tests
# ---------------------------------------------------------------------------

class TestPersistGateResult:
    def test_persists_block_outcome(self):
        persistence = MagicMock()
        persistence.get_or_create_repository.return_value = {"id": "repo-1"}
        persistence.persist_analysis_run.return_value = {"id": "run-1"}

        engine = _make_review_engine(persistence=persistence)
        repo = _make_repository()
        gate = _make_gate(
            GateOutcome.BLOCK,
            [
                CompanyRuleViolation(
                    rule="branch_naming",
                    message="Bad branch",
                    blocking=True,
                    severity="error",
                    detail="Expected ^feature/.*",
                ),
            ],
        )

        engine._persist_gate_result(repo, gate, branch="feature/test", elapsed_ms=12.5)

        persistence.get_or_create_repository.assert_called_once_with(
            name="test-repo",
            root_path="/tmp/test-repo",
            default_branch="main",
            remote_url="https://example.com/test-repo.git",
        )
        persistence.persist_analysis_run.assert_called_once()
        call_kwargs = persistence.persist_analysis_run.call_args.kwargs
        assert call_kwargs["repository_id"] == "repo-1"
        assert call_kwargs["command"] == "rules-check"
        assert call_kwargs["result_type"] == "company_rules"
        assert call_kwargs["status"] == "block"
        assert call_kwargs["branch"] == "feature/test"
        assert call_kwargs["duration_ms"] == 12.5

        result_data = call_kwargs["result_data"]
        assert result_data["outcome"] == "block"
        assert result_data["blocker_count"] == 1
        assert result_data["warning_count"] == 0
        assert len(result_data["violations"]) == 1
        assert result_data["violations"][0]["rule"] == "branch_naming"

    def test_persists_warn_outcome(self):
        persistence = MagicMock()
        persistence.get_or_create_repository.return_value = {"id": "repo-1"}
        persistence.persist_analysis_run.return_value = {"id": "run-1"}

        engine = _make_review_engine(persistence=persistence)
        repo = _make_repository()
        gate = _make_gate(
            GateOutcome.WARN,
            [
                CompanyRuleViolation(
                    rule="require_tests",
                    message="Missing tests",
                    blocking=False,
                    severity="warning",
                ),
            ],
        )

        engine._persist_gate_result(repo, gate, branch="feature/x")

        call_kwargs = persistence.persist_analysis_run.call_args.kwargs
        assert call_kwargs["status"] == "warn"
        assert call_kwargs["result_data"]["warning_count"] == 1
        assert call_kwargs["result_data"]["blocker_count"] == 0

    def test_persists_pass_outcome(self):
        persistence = MagicMock()
        persistence.get_or_create_repository.return_value = {"id": "repo-1"}
        persistence.persist_analysis_run.return_value = {"id": "run-1"}

        engine = _make_review_engine(persistence=persistence)
        repo = _make_repository()
        gate = _make_gate(GateOutcome.PASS)

        engine._persist_gate_result(repo, gate, branch="main")

        call_kwargs = persistence.persist_analysis_run.call_args.kwargs
        assert call_kwargs["status"] == "pass"
        assert call_kwargs["result_data"]["blocker_count"] == 0
        assert call_kwargs["result_data"]["warning_count"] == 0
        assert call_kwargs["result_data"]["violations"] == []

    def test_noop_without_persistence(self):
        engine = _make_review_engine(persistence=None)
        repo = _make_repository()
        gate = _make_gate(GateOutcome.BLOCK)
        # Should not raise
        engine._persist_gate_result(repo, gate, branch="main")

    def test_persistence_failure_logged_not_raised(self):
        persistence = MagicMock()
        persistence.get_or_create_repository.side_effect = RuntimeError("DB down")

        engine = _make_review_engine(persistence=persistence)
        repo = _make_repository()
        gate = _make_gate(GateOutcome.BLOCK)

        # Should not raise
        engine._persist_gate_result(repo, gate, branch="main")
        engine._logger.error.assert_called()

    def test_non_gate_result_is_noop(self):
        persistence = MagicMock()
        engine = _make_review_engine(persistence=persistence)
        repo = _make_repository()

        engine._persist_gate_result(repo, "not-a-gate-result", branch="main")
        persistence.persist_analysis_run.assert_not_called()


# ---------------------------------------------------------------------------
# 2. ReviewEngine.review() blocked path persists gate AND review
# ---------------------------------------------------------------------------

class TestReviewBlockedPersistence:
    def test_blocked_review_persists_both(self):
        persistence = MagicMock()
        persistence.get_or_create_repository.return_value = {"id": "repo-1"}
        persistence.persist_review.return_value = {"id": "rev-1"}
        persistence.persist_analysis_run.return_value = {"id": "run-1"}

        checker = MagicMock()
        gate = _make_gate(
            GateOutcome.BLOCK,
            [
                CompanyRuleViolation(
                    rule="branch_naming",
                    message="Bad branch",
                    blocking=True,
                ),
            ],
        )
        checker.check.return_value = gate

        engine = _make_review_engine(
            persistence=persistence,
            company_rules_checker=checker,
        )

        repo = _make_repository()
        pr = _make_pull_request(pr_number=10)
        engine._git.require_repository.return_value = repo
        engine._github.fetch_pull_request.return_value = pr

        result = engine.review(10)

        assert result.risk_level == "blocked"
        # Review row + rules-check run (History mirrors both via persist_analysis_run)
        persistence.persist_review.assert_called_once()
        assert persistence.persist_analysis_run.call_count == 2
        commands = [
            c.kwargs["command"] for c in persistence.persist_analysis_run.call_args_list
        ]
        assert "review" in commands
        assert "rules-check" in commands
        rules_kwargs = next(
            c.kwargs
            for c in persistence.persist_analysis_run.call_args_list
            if c.kwargs["command"] == "rules-check"
        )
        assert rules_kwargs["status"] == "block"
        assert rules_kwargs["result_data"]["blocker_count"] == 1


# ---------------------------------------------------------------------------
# 3. Successful review persists gate result when gate ran
# ---------------------------------------------------------------------------

def _make_dummy_prompt():
    """Build a minimal PromptRequest that passes Pydantic validation."""
    from refactory.prompt.models import PromptMetadata, PromptRequest
    return PromptRequest(
        system_prompt="You are a code reviewer.",
        user_prompt="Review this PR.",
        metadata=PromptMetadata(template_source="test"),
    )


class TestReviewPassPersistence:
    def test_pass_gate_persisted_after_ai_review(self):
        persistence = MagicMock()
        persistence.get_or_create_repository.return_value = {"id": "repo-1"}
        persistence.persist_review.return_value = {"id": "rev-1"}
        persistence.persist_analysis_run.return_value = {"id": "run-1"}

        checker = MagicMock()
        gate = _make_gate(GateOutcome.PASS)
        checker.check.return_value = gate

        from refactory.ai.models import AIResponse

        ai_response = AIResponse(text='{"summary":"ok"}', provider="test", model="m")

        gateway = MagicMock()
        gateway.generate.return_value = ai_response
        gateway.last_cache_hit = False

        engine = _make_review_engine(
            persistence=persistence,
            company_rules_checker=checker,
            gateway=gateway,
        )

        repo = _make_repository()
        pr = _make_pull_request(pr_number=5)
        engine._git.require_repository.return_value = repo
        engine._github.fetch_pull_request.return_value = pr

        parsed = MagicMock()
        parsed.summary = "All good"
        parsed.suggestions = []
        parsed.overall_risk = "low"
        parsed.confidence = 0.9
        parsed.is_partial = False
        parsed.warnings = []
        parsed.metadata = MagicMock()
        parsed.metadata.source_format = "json"
        parsed.metadata.raw_length = 100
        parsed.metadata.extra = {}
        parsed.metadata.provider = "test"
        parsed.metadata.model = "m"
        engine._response_parser.parse_response.return_value = parsed

        prompt = _make_dummy_prompt()
        with patch.object(engine, "_build_prompt_impl", return_value=prompt):
            result = engine.review(5)

        assert result.risk_level == "low"
        persistence.persist_review.assert_called_once()
        assert persistence.persist_analysis_run.call_count == 2
        commands = [
            c.kwargs["command"] for c in persistence.persist_analysis_run.call_args_list
        ]
        assert "review" in commands
        assert "rules-check" in commands
        rules_kwargs = next(
            c.kwargs
            for c in persistence.persist_analysis_run.call_args_list
            if c.kwargs["command"] == "rules-check"
        )
        assert rules_kwargs["status"] == "pass"

    def test_no_gate_still_persists_review_run(self):
        """Without a company checker, review still persists (no rules-check run)."""
        persistence = MagicMock()
        persistence.get_or_create_repository.return_value = {"id": "repo-1"}
        persistence.persist_review.return_value = {"id": "rev-1"}

        from refactory.ai.models import AIResponse

        ai_response = AIResponse(text='{"summary":"ok"}', provider="test", model="m")

        gateway = MagicMock()
        gateway.generate.return_value = ai_response
        gateway.last_cache_hit = False

        engine = _make_review_engine(
            persistence=persistence,
            company_rules_checker=None,
            gateway=gateway,
        )

        repo = _make_repository()
        pr = _make_pull_request(pr_number=5)
        engine._git.require_repository.return_value = repo
        engine._github.fetch_pull_request.return_value = pr

        parsed = MagicMock()
        parsed.summary = "All good"
        parsed.suggestions = []
        parsed.overall_risk = "low"
        parsed.confidence = 0.9
        parsed.is_partial = False
        parsed.warnings = []
        parsed.metadata = MagicMock()
        parsed.metadata.source_format = "json"
        parsed.metadata.raw_length = 100
        parsed.metadata.extra = {}
        parsed.metadata.provider = "test"
        parsed.metadata.model = "m"
        engine._response_parser.parse_response.return_value = parsed

        prompt = _make_dummy_prompt()
        with patch.object(engine, "_build_prompt_impl", return_value=prompt):
            result = engine.review(5)

        persistence.persist_review.assert_called_once()
        persistence.persist_analysis_run.assert_called_once()
        assert persistence.persist_analysis_run.call_args.kwargs["command"] == "review"


# ---------------------------------------------------------------------------
# 4. result_data schema correctness
# ---------------------------------------------------------------------------

class TestResultDataSchema:
    def test_result_data_has_all_expected_keys(self):
        persistence = MagicMock()
        persistence.get_or_create_repository.return_value = {"id": "repo-1"}
        persistence.persist_analysis_run.return_value = {"id": "run-1"}

        engine = _make_review_engine(persistence=persistence)
        repo = _make_repository()

        violations = [
            CompanyRuleViolation(
                rule="branch_naming", message="Bad branch",
                blocking=True, severity="error", detail="Must match ^feature/.*",
            ),
            CompanyRuleViolation(
                rule="require_tests", message="No tests",
                blocking=False, severity="warning",
            ),
        ]
        gate = _make_gate(GateOutcome.BLOCK, violations)

        engine._persist_gate_result(repo, gate, branch="fix/hotfix", elapsed_ms=5.0)

        call_kwargs = persistence.persist_analysis_run.call_args.kwargs
        rd = call_kwargs["result_data"]

        assert set(rd.keys()) == {"outcome", "violations", "blocker_count", "warning_count", "summary"}
        assert rd["outcome"] == "block"
        assert rd["blocker_count"] == 1
        assert rd["warning_count"] == 1
        assert len(rd["violations"]) == 2
        assert isinstance(rd["summary"], str)

        v0 = rd["violations"][0]
        assert "rule" in v0
        assert "message" in v0
        assert "severity" in v0
        assert "blocking" in v0

    def test_violation_model_dump_is_serialisable(self):
        """Ensure model_dump() produces JSON-serialisable output."""
        import json

        v = CompanyRuleViolation(
            rule="test", message="msg", blocking=True,
            severity="error", file_path="a.py", detail="d",
        )
        serialised = json.dumps(v.model_dump())
        assert "test" in serialised


# ---------------------------------------------------------------------------
# 5. CLI `rules check` persistence
# ---------------------------------------------------------------------------

class TestCliRulesCheckPersistence:
    def test_cli_persists_gate_result(self, tmp_path: Path):
        from typer.testing import CliRunner
        from refactory.cli.app import app

        runner = CliRunner()

        gate = _make_gate(GateOutcome.PASS)
        container = MagicMock()
        container.company_rules_checker.check.return_value = gate

        repo_meta = MagicMock()
        repo_meta.root_path = str(tmp_path)
        repo_meta.name = "cli-repo"
        repo_meta.default_branch = "main"
        repo_meta.remote_url = None
        container.git_service.get_repository_metadata.return_value = repo_meta
        container.git_service.get_current_branch.return_value = "main"
        container.git_service.get_default_branch.return_value = "main"
        container.git_service.get_head_sha.return_value = "abc123"

        commit_info = MagicMock()
        commit_info.message = "feat: init"
        commit_info.sha = "abc123"
        container.git_service.get_current_commit.return_value = commit_info
        container.git_service.get_commits_since_ref.return_value = [commit_info]
        container.git_service.get_changed_files_vs_default_branch.return_value = []
        container.git_service.get_changed_files_vs_ref.return_value = []
        container.git_service.get_working_tree_status.return_value = MagicMock(
            staged_files=[], modified_files=[], deleted_files=[],
            renamed_files=[], untracked_files=[],
        )

        container.persistence_service.get_or_create_repository.return_value = {"id": "r1"}
        container.persistence_service.persist_analysis_run.return_value = {"id": "a1"}

        (tmp_path / ".refactory").mkdir()

        with patch("refactory.cli.commands.rules.get_container", return_value=container):
            completed = runner.invoke(app, ["rules", "check", "--root", str(tmp_path)])

        assert completed.exit_code == 0
        container.persistence_service.persist_analysis_run.assert_called_once()

        call_kwargs = container.persistence_service.persist_analysis_run.call_args.kwargs
        assert call_kwargs["command"] == "rules-check"
        assert call_kwargs["result_type"] == "company_rules"
        assert call_kwargs["status"] == "pass"
        assert call_kwargs["git_commit"] == "abc123"

    def test_cli_persists_block_result(self, tmp_path: Path):
        from typer.testing import CliRunner
        from refactory.cli.app import app

        runner = CliRunner()

        gate = _make_gate(
            GateOutcome.BLOCK,
            [CompanyRuleViolation(rule="x", message="y", blocking=True)],
        )
        container = MagicMock()
        container.company_rules_checker.check.return_value = gate

        repo_meta = MagicMock()
        repo_meta.root_path = str(tmp_path)
        repo_meta.name = "cli-repo"
        repo_meta.default_branch = "main"
        repo_meta.remote_url = None
        container.git_service.get_repository_metadata.return_value = repo_meta
        container.git_service.get_current_branch.return_value = "bad-branch"
        container.git_service.get_default_branch.return_value = "main"
        container.git_service.get_head_sha.return_value = "def456"

        commit_info = MagicMock()
        commit_info.message = "bad commit"
        commit_info.sha = "def456"
        container.git_service.get_current_commit.return_value = commit_info
        container.git_service.get_commits_since_ref.return_value = [commit_info]
        container.git_service.get_changed_files_vs_default_branch.return_value = []
        container.git_service.get_changed_files_vs_ref.return_value = []
        container.git_service.get_working_tree_status.return_value = MagicMock(
            staged_files=[], modified_files=[], deleted_files=[],
            renamed_files=[], untracked_files=[],
        )

        container.persistence_service.get_or_create_repository.return_value = {"id": "r1"}
        container.persistence_service.persist_analysis_run.return_value = {"id": "a1"}

        (tmp_path / ".refactory").mkdir()

        with patch("refactory.cli.commands.rules.get_container", return_value=container):
            completed = runner.invoke(app, ["rules", "check", "--root", str(tmp_path)])

        assert completed.exit_code == 1
        call_kwargs = container.persistence_service.persist_analysis_run.call_args.kwargs
        assert call_kwargs["status"] == "block"
        assert call_kwargs["result_data"]["blocker_count"] == 1

    def test_cli_persistence_failure_does_not_abort(self, tmp_path: Path):
        from typer.testing import CliRunner
        from refactory.cli.app import app

        runner = CliRunner()

        gate = _make_gate(GateOutcome.PASS)
        container = MagicMock()
        container.company_rules_checker.check.return_value = gate

        repo_meta = MagicMock()
        repo_meta.root_path = str(tmp_path)
        repo_meta.name = "cli-repo"
        repo_meta.default_branch = "main"
        repo_meta.remote_url = None
        container.git_service.get_repository_metadata.return_value = repo_meta
        container.git_service.get_current_branch.return_value = "main"
        container.git_service.get_default_branch.return_value = "main"
        container.git_service.get_head_sha.return_value = "abc"

        commit_info = MagicMock()
        commit_info.message = "ok"
        commit_info.sha = "abc"
        container.git_service.get_current_commit.return_value = commit_info
        container.git_service.get_commits_since_ref.return_value = [commit_info]
        container.git_service.get_changed_files_vs_default_branch.return_value = []
        container.git_service.get_changed_files_vs_ref.return_value = []
        container.git_service.get_working_tree_status.return_value = MagicMock(
            staged_files=[], modified_files=[], deleted_files=[],
            renamed_files=[], untracked_files=[],
        )

        container.persistence_service.get_or_create_repository.side_effect = RuntimeError("DB boom")

        (tmp_path / ".refactory").mkdir()

        with patch("refactory.cli.commands.rules.get_container", return_value=container):
            completed = runner.invoke(app, ["rules", "check", "--root", str(tmp_path)])

        # Should still succeed since persistence failure is swallowed
        assert completed.exit_code == 0
        assert "PASS" in completed.stdout
