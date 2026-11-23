"""Phase 8 Feature 3 — Richer git context for the company-rules gate.

Covers:
1. resolve_gate_context priority (override → git → PR)
2. Branch commits since base preferred over PR title
3. Changed files vs PR base / default branch
4. Working-tree fallback when no committed diff
5. Checker validates ALL branch commit messages
6. ReviewEngine uses resolved git context (not PR title alone)
7. CLI --base flag
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from refactory.cli.app import app
from refactory.company.checker import CompanyRulesChecker
from refactory.company.context import resolve_gate_context
from refactory.company.models import GateOutcome
from refactory.github.models import ChangedFile, PullRequest
from refactory.rules.engine import RuleEngine


runner = CliRunner()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _commit(message: str, sha: str = "aaaaaaa") -> MagicMock:
    c = MagicMock()
    c.message = message
    c.sha = sha
    c.short_sha = sha[:7]
    return c


def _changed(path: str) -> MagicMock:
    item = MagicMock()
    item.path = path
    return item


# ---------------------------------------------------------------------------
# resolve_gate_context
# ---------------------------------------------------------------------------


class TestResolveGateContext:
    def test_prefers_branch_commits_over_pr_title(self):
        git = MagicMock()
        git.get_current_branch.return_value = "feature/ABC-1-login"
        git.get_default_branch.return_value = "main"
        git.get_head_sha.return_value = "deadbeef"
        git.get_commits_since_ref.return_value = [
            _commit("feat: real commit", "deadbeef"),
            _commit("fix: earlier", "cafebabe"),
        ]
        git.get_changed_files_vs_ref.return_value = [_changed("src/a.py")]
        git.get_changed_files_vs_default_branch.return_value = []
        git.get_working_tree_status.return_value = MagicMock(
            staged_files=[], modified_files=[], deleted_files=[],
            renamed_files=[], untracked_files=[],
        )

        pr = PullRequest(
            number=1,
            title="PR title that should NOT win",
            head_branch="feature/ABC-1-login",
            base_branch="main",
            changed_files=[],
        )

        ctx = resolve_gate_context(git, pull_request=pr)

        assert ctx.commit_message == "feat: real commit"
        assert ctx.commit_messages == ["feat: real commit", "fix: earlier"]
        assert ctx.changed_files == ["src/a.py"]
        assert ctx.base_branch == "main"
        # Branch from PR + commits/files from git → mixed is expected
        assert ctx.source in {"git", "mixed", "pr"}
        assert ctx.head_sha == "deadbeef"

    def test_falls_back_to_pr_title_when_no_git_commits(self):
        git = MagicMock()
        git.get_current_branch.return_value = "feature/x"
        git.get_default_branch.return_value = "main"
        git.get_head_sha.return_value = None
        git.get_commits_since_ref.return_value = []
        git.get_current_commit.return_value = None
        git.get_changed_files_vs_ref.return_value = []
        git.get_changed_files_vs_default_branch.return_value = []
        git.get_working_tree_status.return_value = MagicMock(
            staged_files=[], modified_files=[], deleted_files=[],
            renamed_files=[], untracked_files=[],
        )

        pr = PullRequest(
            number=2,
            title="feat: from pr title",
            head_branch="feature/x",
            base_branch="develop",
            changed_files=[ChangedFile(path="svc.py", status="modified")],
        )

        ctx = resolve_gate_context(git, pull_request=pr)

        assert ctx.commit_message == "feat: from pr title"
        assert ctx.base_branch == "develop"
        assert ctx.changed_files == ["svc.py"]
        assert "pr" in ctx.source

    def test_explicit_overrides_win(self):
        git = MagicMock()
        git.get_current_branch.return_value = "ignored"
        git.get_default_branch.return_value = "main"
        git.get_commits_since_ref.return_value = [_commit("feat: ignored")]
        git.get_changed_files_vs_ref.return_value = [_changed("ignored.py")]
        git.get_changed_files_vs_default_branch.return_value = []
        git.get_working_tree_status.return_value = MagicMock(
            staged_files=[], modified_files=[], deleted_files=[],
            renamed_files=[], untracked_files=[],
        )

        ctx = resolve_gate_context(
            git,
            branch_name="feature/OVERRIDE",
            commit_message="fix: override",
            base_branch="release",
            changed_files=["forced.py"],
        )

        assert ctx.branch_name == "feature/OVERRIDE"
        assert ctx.commit_message == "fix: override"
        assert ctx.commit_messages == ["fix: override"]
        assert ctx.base_branch == "release"
        assert ctx.changed_files == ["forced.py"]

    def test_working_tree_fallback(self):
        git = MagicMock()
        git.get_current_branch.return_value = "feature/wip"
        git.get_default_branch.return_value = "main"
        git.get_commits_since_ref.return_value = []
        git.get_current_commit.return_value = _commit("feat: head")
        git.get_head_sha.return_value = "abc"
        git.get_changed_files_vs_ref.return_value = []
        git.get_changed_files_vs_default_branch.return_value = []

        dirty = MagicMock()
        dirty.path = "local.py"
        git.get_working_tree_status.return_value = MagicMock(
            staged_files=[],
            modified_files=[dirty],
            deleted_files=[],
            renamed_files=[],
            untracked_files=["new.py"],
        )

        ctx = resolve_gate_context(git)

        assert "local.py" in ctx.changed_files
        assert "new.py" in ctx.changed_files
        assert ctx.commit_message == "feat: head"

    def test_uses_pr_base_for_commit_range(self):
        git = MagicMock()
        git.get_current_branch.return_value = "feature/x"
        git.get_default_branch.return_value = "main"
        git.get_commits_since_ref.return_value = [_commit("feat: vs develop")]
        git.get_changed_files_vs_ref.return_value = [_changed("a.py")]
        git.get_changed_files_vs_default_branch.return_value = []
        git.get_working_tree_status.return_value = MagicMock(
            staged_files=[], modified_files=[], deleted_files=[],
            renamed_files=[], untracked_files=[],
        )
        git.get_head_sha.return_value = "x"

        pr = PullRequest(
            number=3,
            title="ignored",
            head_branch="feature/x",
            base_branch="develop",
            changed_files=[],
        )
        resolve_gate_context(git, pull_request=pr)

        git.get_commits_since_ref.assert_called()
        args, kwargs = git.get_commits_since_ref.call_args
        assert args[0] == "develop"
        git.get_changed_files_vs_ref.assert_called_with("develop")


# ---------------------------------------------------------------------------
# Checker — multi-commit validation
# ---------------------------------------------------------------------------


class TestMultiCommitCheck:
    def test_blocks_when_any_branch_commit_fails(self, tmp_path: Path):
        _write(
            tmp_path / ".refactory" / "company.yaml",
            """
commit:
  pattern: "^(feat|fix):"
  block: true
""",
        )
        checker = CompanyRulesChecker(
            logger=MagicMock(),
            rule_engine=RuleEngine(logger=MagicMock()),
        )
        result = checker.check(
            tmp_path,
            commit_messages=["feat: good", "fixed login", "fix: also good"],
        )
        assert result.outcome == GateOutcome.BLOCK
        assert any(v.rule == "commit_message" for v in result.blockers)
        assert "fixed login" in result.blockers[0].message

    def test_pass_when_all_commits_match(self, tmp_path: Path):
        _write(
            tmp_path / ".refactory" / "company.yaml",
            """
commit:
  pattern: "^(feat|fix):"
  block: true
""",
        )
        checker = CompanyRulesChecker(
            logger=MagicMock(),
            rule_engine=RuleEngine(logger=MagicMock()),
        )
        result = checker.check(
            tmp_path,
            commit_messages=["feat: a", "fix: b"],
        )
        assert result.outcome == GateOutcome.PASS

    def test_single_commit_message_still_works(self, tmp_path: Path):
        _write(
            tmp_path / ".refactory" / "company.yaml",
            """
commit:
  pattern: "^(feat|fix):"
  block: true
""",
        )
        checker = CompanyRulesChecker(
            logger=MagicMock(),
            rule_engine=RuleEngine(logger=MagicMock()),
        )
        result = checker.check(tmp_path, commit_message="fixed login")
        assert result.outcome == GateOutcome.BLOCK


# ---------------------------------------------------------------------------
# ReviewEngine uses git context
# ---------------------------------------------------------------------------


class TestReviewEngineUsesGitContext:
    def test_gate_prefers_git_commit_not_pr_title(self, tmp_path: Path):
        _write(
            tmp_path / ".refactory" / "company.yaml",
            """
commit:
  pattern: "^(feat|fix):"
  block: true
""",
        )
        checker = CompanyRulesChecker(
            logger=MagicMock(),
            rule_engine=RuleEngine(logger=MagicMock()),
        )

        from refactory.review.engine import ReviewEngine

        git = MagicMock()
        repo = MagicMock()
        repo.name = "demo"
        repo.root_path = str(tmp_path)
        repo.current_branch = "feature/ABC-1-x"
        repo.default_branch = "main"
        repo.remote_url = None
        git.require_repository.return_value = repo
        git.get_current_branch.return_value = "feature/ABC-1-x"
        git.get_default_branch.return_value = "main"
        git.get_head_sha.return_value = "deadbeef"
        # Real commit fails convention; PR title would pass
        git.get_commits_since_ref.return_value = [_commit("fixed login", "deadbeef")]
        git.get_changed_files_vs_ref.return_value = []
        git.get_changed_files_vs_default_branch.return_value = []
        git.get_working_tree_status.return_value = MagicMock(
            staged_files=[], modified_files=[], deleted_files=[],
            renamed_files=[], untracked_files=[],
        )
        git.get_current_commit.return_value = _commit("fixed login", "deadbeef")

        engine = ReviewEngine(
            git_service=git,
            github_service=MagicMock(),
            parser_service=MagicMock(),
            indexer_service=MagicMock(),
            retrieval_service=MagicMock(),
            ai_service=MagicMock(),
            logger=MagicMock(),
            graph_service=MagicMock(),
            prompt_builder=MagicMock(),
            ai_gateway=MagicMock(),
            response_parser=MagicMock(),
            company_rules_checker=checker,
        )
        engine._gateway.generate.side_effect = AssertionError("AI must not run")

        engine._resolve_pull_request = MagicMock(
            return_value=PullRequest(
                number=1,
                title="feat: looks fine",  # would PASS if used
                head_branch="feature/ABC-1-x",
                base_branch="main",
                changed_files=[],
            )
        )

        result = engine.review(1)
        assert result.risk_level == "blocked"
        assert any("commit" in s.title.lower() or "commit" in s.detail.lower()
                   for s in result.suggestions) or "commit" in result.summary.lower()


# ---------------------------------------------------------------------------
# CLI --base + richer context
# ---------------------------------------------------------------------------


class TestCliRicherContext:
    def test_base_flag_passed_to_resolver(self, tmp_path: Path):
        (tmp_path / ".refactory").mkdir()
        from refactory.company.models import GateResult

        result = GateResult(outcome=GateOutcome.PASS)
        container = MagicMock()
        container.company_rules_checker.check.return_value = result

        repo = MagicMock()
        repo.root_path = str(tmp_path)
        repo.name = "cli-repo"
        repo.default_branch = "main"
        repo.remote_url = None
        container.git_service.get_repository_metadata.return_value = repo
        container.git_service.get_current_branch.return_value = "feature/x"
        container.git_service.get_default_branch.return_value = "main"
        container.git_service.get_head_sha.return_value = "abc"
        container.git_service.get_commits_since_ref.return_value = [
            _commit("feat: ok", "abc")
        ]
        container.git_service.get_current_commit.return_value = _commit("feat: ok", "abc")
        container.git_service.get_changed_files_vs_ref.return_value = []
        container.git_service.get_changed_files_vs_default_branch.return_value = []
        container.git_service.get_working_tree_status.return_value = MagicMock(
            staged_files=[], modified_files=[], deleted_files=[],
            renamed_files=[], untracked_files=[],
        )
        container.persistence_service.get_or_create_repository.return_value = {"id": "r1"}
        container.persistence_service.persist_analysis_run.return_value = {"id": "a1"}

        with patch("refactory.cli.commands.rules.get_container", return_value=container):
            completed = runner.invoke(
                app,
                ["rules", "check", "--root", str(tmp_path), "--base", "develop"],
            )

        assert completed.exit_code == 0
        container.git_service.get_commits_since_ref.assert_called()
        assert container.git_service.get_commits_since_ref.call_args[0][0] == "develop"
        assert "Base:" in completed.stdout or "develop" in completed.stdout

    def test_cli_passes_commit_messages_list(self, tmp_path: Path):
        (tmp_path / ".refactory").mkdir()
        from refactory.company.models import GateResult

        result = GateResult(outcome=GateOutcome.PASS)
        container = MagicMock()
        container.company_rules_checker.check.return_value = result

        repo = MagicMock()
        repo.root_path = str(tmp_path)
        repo.name = "cli-repo"
        repo.default_branch = "main"
        repo.remote_url = None
        container.git_service.get_repository_metadata.return_value = repo
        container.git_service.get_current_branch.return_value = "feature/x"
        container.git_service.get_default_branch.return_value = "main"
        container.git_service.get_head_sha.return_value = "abc"
        container.git_service.get_commits_since_ref.return_value = [
            _commit("feat: one", "aaa"),
            _commit("fix: two", "bbb"),
        ]
        container.git_service.get_current_commit.return_value = _commit("feat: one", "aaa")
        container.git_service.get_changed_files_vs_ref.return_value = [
            _changed("a.py"),
            _changed("b.py"),
        ]
        container.git_service.get_changed_files_vs_default_branch.return_value = []
        container.git_service.get_working_tree_status.return_value = MagicMock(
            staged_files=[], modified_files=[], deleted_files=[],
            renamed_files=[], untracked_files=[],
        )
        container.persistence_service.get_or_create_repository.return_value = {"id": "r1"}
        container.persistence_service.persist_analysis_run.return_value = {"id": "a1"}

        with patch("refactory.cli.commands.rules.get_container", return_value=container):
            completed = runner.invoke(app, ["rules", "check", "--root", str(tmp_path)])

        assert completed.exit_code == 0
        kwargs = container.company_rules_checker.check.call_args.kwargs
        assert kwargs["commit_messages"] == ["feat: one", "fix: two"]
        assert kwargs["changed_files"] == ["a.py", "b.py"]
        assert "2 commits" in completed.stdout
        assert "2 changed" in completed.stdout
