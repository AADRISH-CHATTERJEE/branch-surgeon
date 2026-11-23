"""Phase 8 — Company Rules & Standards (pre-review gate) tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from refactory.company.checker import CompanyRulesChecker
from refactory.company.loader import (
    architecture_config_for_service,
    load_company_guidelines,
    load_company_standards,
)
from refactory.company.models import GateOutcome
from refactory.rules.engine import RuleEngine
from refactory.review.engine import ReviewEngine
from refactory.review.models import ReviewResult


@pytest.fixture()
def logger():
    return MagicMock()


@pytest.fixture()
def checker(logger):
    return CompanyRulesChecker(
        logger=logger,
        rule_engine=RuleEngine(logger=logger),
        architecture_policy=None,
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


class TestCompanyLoader:
    def test_load_branch_and_commit(self, tmp_path: Path):
        _write(
            tmp_path / ".refactory" / "company.yaml",
            """
organization:
  name: Acme
branch:
  pattern: "^feature/[A-Z]+-[0-9]+-.*$"
  block: true
commit:
  pattern: "^(feat|fix):"
  block: true
testing:
  require_tests: true
  block: false
""",
        )
        std = load_company_standards(tmp_path)
        assert std.organization_name == "Acme"
        assert std.branch is not None
        assert std.branch.block is True
        assert std.commit is not None
        assert std.testing is not None
        assert std.testing.require_tests is True

    def test_load_guidelines(self, tmp_path: Path):
        _write(tmp_path / ".refactory" / "architecture.md", "Use DAOs.")
        _write(tmp_path / ".refactory" / "coding_guidelines.md", "No wildcards.")
        _write(tmp_path / ".refactory" / "security_guidelines.md", "No eval.")
        g = load_company_guidelines(tmp_path)
        text = g.combined_for_prompt()
        assert "Use DAOs." in text
        assert "No wildcards." in text
        assert "No eval." in text
        assert "Architecture Guidelines" in text

    def test_architecture_deny_conversion(self):
        raw = {
            "layers": [
                {"name": "presentation", "patterns": ["*/cli/*"]},
                {"name": "business", "patterns": ["*/services/*"]},
                {"name": "data", "patterns": ["*/db/*"]},
            ],
            "policies": [
                {"from": "presentation", "to": "data", "action": "deny"},
            ],
        }
        cfg = architecture_config_for_service(raw)
        presentation = next(l for l in cfg["layers"] if l["name"] == "presentation")
        assert "data" not in presentation["allowed_dependencies"]
        assert "business" in presentation["allowed_dependencies"]


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------


class TestCompanyRulesChecker:
    def test_branch_block(self, checker, tmp_path: Path):
        _write(
            tmp_path / ".refactory" / "company.yaml",
            """
branch:
  pattern: "^feature/[A-Z]+-[0-9]+-.*$"
  block: true
""",
        )
        result = checker.check(tmp_path, branch_name="feature/login")
        assert result.outcome == GateOutcome.BLOCK
        assert any(v.rule == "branch_naming" for v in result.blockers)

    def test_branch_pass(self, checker, tmp_path: Path):
        _write(
            tmp_path / ".refactory" / "company.yaml",
            """
branch:
  pattern: "^feature/[A-Z]+-[0-9]+-.*$"
  block: true
""",
        )
        result = checker.check(tmp_path, branch_name="feature/ABC-123-login")
        assert result.outcome == GateOutcome.PASS

    def test_commit_block(self, checker, tmp_path: Path):
        _write(
            tmp_path / ".refactory" / "company.yaml",
            """
commit:
  pattern: "^(feat|fix|refactor|docs|test):"
  block: true
""",
        )
        result = checker.check(tmp_path, commit_message="fixed login")
        assert result.outcome == GateOutcome.BLOCK
        assert any(v.rule == "commit_message" for v in result.blockers)

    def test_commit_pass(self, checker, tmp_path: Path):
        _write(
            tmp_path / ".refactory" / "company.yaml",
            """
commit:
  pattern: "^(feat|fix|refactor|docs|test):"
  block: true
""",
        )
        result = checker.check(tmp_path, commit_message="fix: login redirect")
        assert result.outcome == GateOutcome.PASS

    def test_require_tests_warn(self, checker, tmp_path: Path):
        _write(
            tmp_path / ".refactory" / "company.yaml",
            """
testing:
  require_tests: true
  block: false
""",
        )
        result = checker.check(
            tmp_path,
            changed_files=["src/service.py"],
        )
        assert result.outcome == GateOutcome.WARN
        assert any(v.rule == "require_tests" for v in result.warnings)

    def test_require_tests_with_tests_pass(self, checker, tmp_path: Path):
        _write(
            tmp_path / ".refactory" / "company.yaml",
            """
testing:
  require_tests: true
  block: true
""",
        )
        result = checker.check(
            tmp_path,
            changed_files=["src/service.py", "tests/test_service.py"],
        )
        assert result.outcome == GateOutcome.PASS

    def test_architecture_forbidden(self, checker, tmp_path: Path):
        _write(
            tmp_path / ".refactory" / "company.yaml",
            """
architecture:
  block: true
  forbidden_dependencies:
    - from: frontend
      to: database
""",
        )
        _write(
            tmp_path / ".refactory" / "architecture.yaml",
            """
layers:
  - name: frontend
    patterns: ["frontend/*"]
  - name: database
    patterns: ["database/*"]
""",
        )
        result = checker.check(
            tmp_path,
            file_imports={"frontend/app.py": ["database/models.py"]},
        )
        assert result.outcome == GateOutcome.BLOCK
        assert any(v.rule == "architecture" for v in result.blockers)

    def test_rules_yaml_blocking(self, checker, tmp_path: Path):
        _write(
            tmp_path / ".refactory" / "rules.yaml",
            """
rules:
  - name: force-branch
    category: branch_naming
    severity: error
    blocking: true
    conditions:
      - field: branch_name
        operator: matches
        pattern: "^release/.*"
    message: "Only release branches allowed"
""",
        )
        result = checker.check(tmp_path, branch_name="feature/x")
        assert result.outcome == GateOutcome.BLOCK
        assert any(v.rule == "force-branch" for v in result.blockers)

    def test_no_config_passes(self, checker, tmp_path: Path):
        (tmp_path / ".refactory").mkdir()
        result = checker.check(tmp_path, branch_name="anything")
        assert result.outcome == GateOutcome.PASS


# ---------------------------------------------------------------------------
# ReviewEngine gate integration
# ---------------------------------------------------------------------------


def _make_review_engine(checker=None, gateway=None) -> ReviewEngine:
    git = MagicMock()
    repo = MagicMock()
    repo.name = "demo"
    repo.root_path = "/tmp/demo"
    repo.current_branch = "feature/login"
    repo.default_branch = "main"
    repo.remote_url = None
    git.require_repository.return_value = repo

    gw = gateway or MagicMock()
    if gateway is None:
        gw.generate.side_effect = AssertionError("AI must not run when blocked")

    return ReviewEngine(
        git_service=git,
        github_service=MagicMock(),
        parser_service=MagicMock(),
        indexer_service=MagicMock(),
        retrieval_service=MagicMock(),
        ai_service=MagicMock(),
        logger=MagicMock(),
        graph_service=MagicMock(),
        prompt_builder=MagicMock(),
        ai_gateway=gw,
        response_parser=MagicMock(),
        company_rules_checker=checker,
    )


class TestReviewEngineGate:
    def test_blocked_skips_ai(self, tmp_path: Path, logger):
        _write(
            tmp_path / ".refactory" / "company.yaml",
            """
branch:
  pattern: "^feature/[A-Z]+-[0-9]+-.*$"
  block: true
""",
        )
        checker = CompanyRulesChecker(
            logger=logger,
            rule_engine=RuleEngine(logger=logger),
        )
        engine = _make_review_engine(checker=checker)

        # Point repository root at tmp_path
        engine._git.require_repository.return_value.root_path = str(tmp_path)
        engine._git.require_repository.return_value.current_branch = "feature/login"

        # Force local PR synthesis with bad branch
        from refactory.github.models import PullRequest

        engine._resolve_pull_request = MagicMock(
            return_value=PullRequest(
                number=1,
                title="fix: something",
                head_branch="feature/login",
                base_branch="main",
                changed_files=[],
            )
        )

        result = engine.review(1)
        assert isinstance(result, ReviewResult)
        assert result.risk_level == "blocked"
        assert "BLOCKED" in result.summary or "branch" in result.summary.lower()
        assert result.suggestions

    def test_pass_runs_ai(self, tmp_path: Path, logger):
        (tmp_path / ".refactory").mkdir()
        checker = CompanyRulesChecker(
            logger=logger,
            rule_engine=RuleEngine(logger=logger),
        )

        from refactory.ai.models import AIResponse
        from refactory.github.models import PullRequest
        from refactory.prompt.models import PromptMetadata, PromptRequest
        from refactory.response.models import ReviewMetadata, ReviewResult as ParsedReviewResult

        gw = MagicMock()
        gw.generate.return_value = AIResponse(
            text="{}",
            provider="mock",
            model="mock",
            prompt_tokens=1,
            completion_tokens=1,
            latency_ms=1.0,
        )
        gw.last_cache_hit = False
        engine = _make_review_engine(checker=checker, gateway=gw)
        engine._git.require_repository.return_value.root_path = str(tmp_path)
        engine._resolve_pull_request = MagicMock(
            return_value=PullRequest(
                number=2,
                title="feat: ok",
                head_branch="feature/ABC-1-ok",
                changed_files=[],
            )
        )
        engine._build_prompt_impl = MagicMock(
            return_value=PromptRequest(
                system_prompt="s",
                user_prompt="u",
                metadata=PromptMetadata(template_source="local_default"),
            )
        )
        engine._response_parser.parse_response.return_value = ParsedReviewResult(
            summary="ok",
            overall_risk="low",
            suggestions=[],
            confidence=0.9,
            metadata=ReviewMetadata(source_format="json", provider="mock", model="mock"),
        )
        engine._persist_review = MagicMock()

        result = engine.review(2)
        assert result.risk_level != "blocked"
        gw.generate.assert_called_once()
        engine._build_prompt_impl.assert_called_once()
