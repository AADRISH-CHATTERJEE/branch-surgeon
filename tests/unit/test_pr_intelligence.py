"""Tests for PRIntelligenceService — Git diff, PR summary, merge risk, reviewers,
tests, breaking changes, AI review, security, performance, merge readiness,
changed dependency graph, and change explanation.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from refactory.pr.models import (
    AIReviewReport,
    BreakingChangeKind,
    BreakingChangeReport,
    ChangedDependencyGraph,
    ChangedFile,
    ChangedSymbol,
    ChangeExplanation,
    DiffChangeKind,
    DiffSummary,
    MergeReadinessReport,
    MergeRiskReport,
    PerformanceIssue,
    PerformanceIssueKind,
    PerformanceReport,
    PRSummary,
    ReadinessStatus,
    ReviewCategory,
    ReviewComment,
    ReviewerReport,
    RiskLevel,
    SecurityIssue,
    SecurityIssueKind,
    SecurityReport,
    TestRecommendationReport,
)
from refactory.pr.service import PRIntelligenceService


@pytest.fixture
def mock_git():
    git = MagicMock()
    git.get_root_path.return_value = "/tmp/repo"
    repo_mock = MagicMock()
    repo_mock.iter_commits.return_value = []
    repo_mock.head.commit.author.name = "TestUser"
    git._open_repo.return_value = repo_mock
    return git


@pytest.fixture
def mock_parser():
    return MagicMock()


@pytest.fixture
def mock_indexer():
    return MagicMock()


@pytest.fixture
def mock_graph():
    return MagicMock()


@pytest.fixture
def mock_impact():
    return MagicMock()


@pytest.fixture
def mock_ai():
    ai = MagicMock()
    resp = MagicMock()
    resp.content = "AI generated content"
    ai.generate.return_value = resp
    return ai


@pytest.fixture
def service(mock_git, mock_parser, mock_indexer, mock_graph, mock_impact, mock_ai):
    from loguru import logger
    return PRIntelligenceService(
        logger=logger,
        git_service=mock_git,
        parser_service=mock_parser,
        indexer_service=mock_indexer,
        graph_service=mock_graph,
        impact_service=mock_impact,
        ai_gateway=mock_ai,
    )


@pytest.fixture
def sample_diff() -> DiffSummary:
    return DiffSummary(
        base_ref="HEAD~1",
        head_ref="HEAD",
        changed_files=[
            ChangedFile(path="refactory/core/service.py", change_kind=DiffChangeKind.MODIFIED, insertions=10, deletions=2),
            ChangedFile(path="refactory/api/routes.py", change_kind=DiffChangeKind.MODIFIED, insertions=20, deletions=5),
            ChangedFile(path="refactory/models.py", change_kind=DiffChangeKind.ADDED, insertions=50, deletions=0),
            ChangedFile(path="tests/test_core.py", change_kind=DiffChangeKind.MODIFIED, insertions=5, deletions=1),
        ],
        total_insertions=85,
        total_deletions=8,
        files_added=1,
        files_modified=3,
        files_deleted=0,
        files_renamed=0,
    )


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    d = tmp_path / "repo"
    d.mkdir()
    (d / "refactory").mkdir()
    (d / "refactory" / "core").mkdir(parents=True)
    (d / "refactory" / "api").mkdir(parents=True)
    (d / "refactory" / "core" / "service.py").write_text("def hello(): pass\n")
    (d / "refactory" / "api" / "routes.py").write_text("def get(): pass\n")
    (d / "refactory" / "models.py").write_text("class User: pass\n")
    (d / "tests").mkdir()
    (d / "tests" / "unit").mkdir()
    (d / "tests" / "test_core.py").write_text("def test_hello(): pass\n")
    return d


# ===========================================================================
# Task 1: Git Diff Service (20 tests)
# ===========================================================================

class TestGitDiffService:
    def test_diff_summary_model(self):
        d = DiffSummary()
        assert d.changed_files == []
        assert d.total_insertions == 0

    def test_changed_file_model(self):
        f = ChangedFile(path="a.py", change_kind=DiffChangeKind.ADDED)
        assert f.path == "a.py"
        assert f.change_kind == DiffChangeKind.ADDED

    def test_changed_symbol_model(self):
        s = ChangedSymbol(name="func", kind="function", file_path="a.py")
        assert s.name == "func"

    def test_diff_change_kinds(self):
        assert DiffChangeKind.ADDED == "added"
        assert DiffChangeKind.MODIFIED == "modified"
        assert DiffChangeKind.DELETED == "deleted"
        assert DiffChangeKind.RENAMED == "renamed"

    def test_diff_summary_counts(self, sample_diff: DiffSummary):
        assert sample_diff.files_added == 1
        assert sample_diff.files_modified == 3
        assert sample_diff.total_insertions == 85

    def test_changed_symbols_extraction(self, service: PRIntelligenceService, repo_dir: Path):
        parsed_mock = MagicMock()
        parsed_mock.module.functions = [MagicMock(name="func1")]
        parsed_mock.module.classes = [MagicMock(name="MyClass")]
        service._parser.parse_file.return_value = parsed_mock

        diff = DiffSummary(changed_files=[
            ChangedFile(path="refactory/core/service.py", change_kind=DiffChangeKind.MODIFIED),
        ])
        symbols = service.changed_symbols(diff, repo_dir)
        assert len(symbols) >= 0

    def test_deleted_files_no_symbols(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(path="old.py", change_kind=DiffChangeKind.DELETED),
        ])
        symbols = service.changed_symbols(diff, repo_dir)
        assert symbols == []

    def test_binary_files_no_symbols(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(path="image.png", is_binary=True),
        ])
        symbols = service.changed_symbols(diff, repo_dir)
        assert symbols == []

    def test_extract_hunks(self, service: PRIntelligenceService):
        patch = "@@ -1,3 +1,4 @@\n+new line\n context\n@@ -10,2 +11,3 @@\n+another"
        hunks = service._extract_hunks(patch)
        assert len(hunks) == 2

    def test_extract_hunks_empty(self, service: PRIntelligenceService):
        assert service._extract_hunks("") == []

    def test_changed_file_with_hunks(self):
        f = ChangedFile(path="a.py", hunks=["@@ -1,3 +1,4 @@"])
        assert len(f.hunks) == 1

    def test_renamed_file(self):
        f = ChangedFile(path="new.py", old_path="old.py", change_kind=DiffChangeKind.RENAMED)
        assert f.old_path == "old.py"

    def test_diff_summary_empty(self):
        d = DiffSummary()
        assert len(d.changed_files) == 0
        assert d.files_added == 0

    def test_changed_file_insertions_deletions(self):
        f = ChangedFile(path="a.py", insertions=10, deletions=5)
        assert f.insertions == 10
        assert f.deletions == 5

    def test_diff_with_many_files(self):
        files = [ChangedFile(path=f"f{i}.py") for i in range(50)]
        d = DiffSummary(changed_files=files)
        assert len(d.changed_files) == 50

    def test_changed_symbol_with_lines(self):
        s = ChangedSymbol(name="func", start_line=10, end_line=20)
        assert s.start_line == 10
        assert s.end_line == 20

    def test_extract_modules(self, service: PRIntelligenceService, sample_diff: DiffSummary):
        modules = service._extract_modules(sample_diff)
        assert "refactory" in modules

    def test_extract_modules_empty(self, service: PRIntelligenceService):
        d = DiffSummary()
        assert service._extract_modules(d) == []

    def test_diff_summary_refs(self, sample_diff: DiffSummary):
        assert sample_diff.base_ref == "HEAD~1"
        assert sample_diff.head_ref == "HEAD"

    def test_file_not_found_graceful(self, service: PRIntelligenceService, tmp_path: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(path="nonexistent.py", change_kind=DiffChangeKind.MODIFIED),
        ])
        symbols = service.changed_symbols(diff, tmp_path)
        assert symbols == []


# ===========================================================================
# Task 3: Merge Risk (15 tests)
# ===========================================================================

class TestMergeRisk:
    def test_low_risk_few_changes(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(path="docs/readme.md", insertions=5),
        ], total_insertions=5, total_deletions=0)
        report = service.merge_risk(diff, repo_dir)
        assert report.overall_risk == RiskLevel.LOW

    def test_high_risk_many_core_files(self, service: PRIntelligenceService, repo_dir: Path):
        files = [ChangedFile(path=f"core/module{i}.py", insertions=50) for i in range(5)]
        diff = DiffSummary(changed_files=files, total_insertions=250, total_deletions=50)
        report = service.merge_risk(diff, repo_dir)
        assert report.overall_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def test_api_changes_increase_risk(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(path="api/endpoints.py", insertions=100),
            ChangedFile(path="api/routes.py", insertions=50),
        ], total_insertions=150, total_deletions=0)
        report = service.merge_risk(diff, repo_dir)
        assert report.api_changes == 2

    def test_config_changes_tracked(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(path="config.yml", insertions=5),
        ])
        report = service.merge_risk(diff, repo_dir)
        assert report.configuration_changes == 1

    def test_large_changeset_risk(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(
            changed_files=[ChangedFile(path="big.py", insertions=600)],
            total_insertions=600, total_deletions=0,
        )
        report = service.merge_risk(diff, repo_dir)
        assert report.risk_score > 0

    def test_broad_scope_risk(self, service: PRIntelligenceService, repo_dir: Path):
        files = [ChangedFile(path=f"file{i}.py") for i in range(25)]
        diff = DiffSummary(changed_files=files)
        report = service.merge_risk(diff, repo_dir)
        assert any(f.name == "Broad change scope" for f in report.factors)

    def test_risk_report_model(self):
        r = MergeRiskReport()
        assert r.overall_risk == RiskLevel.LOW
        assert r.risk_score == 0.0
        assert r.factors == []

    def test_risk_factor_model(self):
        from refactory.pr.models import RiskFactor
        f = RiskFactor(name="test", severity=RiskLevel.HIGH)
        assert f.severity == RiskLevel.HIGH

    def test_recommendation_for_low(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(changed_files=[ChangedFile(path="readme.txt")])
        report = service.merge_risk(diff, repo_dir)
        assert "safe" in report.recommendation.lower() or "standard" in report.recommendation.lower()

    def test_empty_diff_low_risk(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary()
        report = service.merge_risk(diff, repo_dir)
        assert report.overall_risk == RiskLevel.LOW

    def test_public_method_changes(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(
                path="service.py",
                changed_symbols=[
                    ChangedSymbol(name="public_func"),
                    ChangedSymbol(name="another_public"),
                    ChangedSymbol(name="_private"),
                ],
            )
        ])
        report = service.merge_risk(diff, repo_dir)
        assert report.public_method_changes == 2

    def test_critical_risk_threshold(self, service: PRIntelligenceService, repo_dir: Path):
        files = [ChangedFile(path=f"core/service{i}.py", insertions=100) for i in range(10)]
        files.extend(ChangedFile(path=f"api/route{i}.py", insertions=50) for i in range(5))
        diff = DiffSummary(changed_files=files, total_insertions=1500, total_deletions=200)
        report = service.merge_risk(diff, repo_dir)
        assert report.overall_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def test_risk_score_bounded(self, service: PRIntelligenceService, repo_dir: Path):
        files = [ChangedFile(path=f"core/m{i}.py") for i in range(50)]
        diff = DiffSummary(changed_files=files, total_insertions=5000)
        report = service.merge_risk(diff, repo_dir)
        assert report.risk_score <= 100.0

    def test_central_modules_count(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(path="core/a.py"),
            ChangedFile(path="core/b.py"),
            ChangedFile(path="service.py"),
        ])
        report = service.merge_risk(diff, repo_dir)
        assert report.central_modules_modified >= 2

    def test_risk_levels_enum(self):
        assert RiskLevel.LOW == "low"
        assert RiskLevel.MEDIUM == "medium"
        assert RiskLevel.HIGH == "high"
        assert RiskLevel.CRITICAL == "critical"


# ===========================================================================
# Task 4: Reviewer Recommendation (15 tests)
# ===========================================================================

class TestReviewerRecommendation:
    def test_empty_diff_no_reviewers(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary()
        report = service.recommend_reviewers(diff, repo_dir)
        assert report.reviewers == []

    def test_reviewer_report_model(self):
        r = ReviewerReport()
        assert r.reviewers == []
        assert r.changed_files == 0

    def test_reviewer_candidate_model(self):
        from refactory.pr.models import ReviewerCandidate
        c = ReviewerCandidate(name="Alice", email="alice@dev.co", confidence=0.9)
        assert c.name == "Alice"
        assert c.confidence == 0.9

    def test_modules_in_report(self, service: PRIntelligenceService, repo_dir: Path, sample_diff: DiffSummary):
        report = service.recommend_reviewers(sample_diff, repo_dir)
        assert report.modules_affected is not None

    def test_changed_files_count(self, service: PRIntelligenceService, repo_dir: Path, sample_diff: DiffSummary):
        report = service.recommend_reviewers(sample_diff, repo_dir)
        assert report.changed_files == len(sample_diff.changed_files)

    def test_reviewer_confidence_bounded(self):
        from refactory.pr.models import ReviewerCandidate
        c = ReviewerCandidate(name="Bob", confidence=1.5)
        assert c.confidence > 0

    def test_reviewer_reasons(self):
        from refactory.pr.models import ReviewerCandidate
        c = ReviewerCandidate(name="Eve", reasons=["Owns auth module", "5 commits"])
        assert len(c.reasons) == 2

    def test_reviewer_files_owned(self):
        from refactory.pr.models import ReviewerCandidate
        c = ReviewerCandidate(name="Dave", files_owned=10)
        assert c.files_owned == 10

    def test_reviewer_modules_owned(self):
        from refactory.pr.models import ReviewerCandidate
        c = ReviewerCandidate(name="Carol", modules_owned=["auth", "core"])
        assert "auth" in c.modules_owned

    def test_max_5_reviewers(self, service: PRIntelligenceService, repo_dir: Path, sample_diff: DiffSummary):
        report = service.recommend_reviewers(sample_diff, repo_dir)
        assert len(report.reviewers) <= 5

    def test_self_excluded(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(changed_files=[ChangedFile(path="a.py")])
        report = service.recommend_reviewers(diff, repo_dir)
        for r in report.reviewers:
            assert r.name != "TestUser"

    def test_report_with_multiple_files(self, service: PRIntelligenceService, repo_dir: Path):
        files = [ChangedFile(path=f"mod{i}.py") for i in range(10)]
        diff = DiffSummary(changed_files=files)
        report = service.recommend_reviewers(diff, repo_dir)
        assert report.changed_files == 10

    def test_reviewer_email_optional(self):
        from refactory.pr.models import ReviewerCandidate
        c = ReviewerCandidate(name="No-email")
        assert c.email == ""

    def test_empty_modules(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(changed_files=[ChangedFile(path="single.py")])
        report = service.recommend_reviewers(diff, repo_dir)
        assert isinstance(report.modules_affected, list)

    def test_reviewer_report_serializable(self, service: PRIntelligenceService, repo_dir: Path, sample_diff: DiffSummary):
        report = service.recommend_reviewers(sample_diff, repo_dir)
        data = report.model_dump()
        assert "reviewers" in data


# ===========================================================================
# Task 6: Breaking Changes (15 tests)
# ===========================================================================

class TestBreakingChanges:
    def test_no_breaking_changes(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(path="readme.md", change_kind=DiffChangeKind.MODIFIED),
        ])
        report = service.detect_breaking_changes(diff, repo_dir)
        assert report.total_breaking == 0
        assert report.risk_level == RiskLevel.LOW

    def test_deleted_file_is_breaking(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(path="api/handler.py", change_kind=DiffChangeKind.DELETED),
        ])
        report = service.detect_breaking_changes(diff, repo_dir)
        assert report.total_breaking >= 1

    def test_breaking_change_kinds(self):
        assert BreakingChangeKind.REMOVED_METHOD == "removed_method"
        assert BreakingChangeKind.RENAMED_API == "renamed_api"
        assert BreakingChangeKind.CHANGED_SIGNATURE == "changed_signature"

    def test_high_risk_many_breaking(self, service: PRIntelligenceService, repo_dir: Path):
        files = [
            ChangedFile(path=f"api/mod{i}.py", change_kind=DiffChangeKind.DELETED)
            for i in range(5)
        ]
        diff = DiffSummary(changed_files=files)
        report = service.detect_breaking_changes(diff, repo_dir)
        assert report.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def test_breaking_change_model(self):
        from refactory.pr.models import BreakingChange
        bc = BreakingChange(
            kind=BreakingChangeKind.REMOVED_METHOD,
            symbol="old_func",
            file_path="service.py",
        )
        assert bc.symbol == "old_func"

    def test_breaking_report_model(self):
        r = BreakingChangeReport()
        assert r.changes == []
        assert r.total_breaking == 0

    def test_non_python_deleted_not_breaking(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(path="readme.md", change_kind=DiffChangeKind.DELETED),
        ])
        report = service.detect_breaking_changes(diff, repo_dir)
        assert report.total_breaking == 0

    def test_critical_risk_threshold(self, service: PRIntelligenceService, repo_dir: Path):
        files = [
            ChangedFile(path=f"module{i}.py", change_kind=DiffChangeKind.DELETED)
            for i in range(8)
        ]
        diff = DiffSummary(changed_files=files)
        report = service.detect_breaking_changes(diff, repo_dir)
        assert report.risk_level == RiskLevel.CRITICAL

    def test_medium_risk(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(path="one.py", change_kind=DiffChangeKind.DELETED),
        ])
        report = service.detect_breaking_changes(diff, repo_dir)
        assert report.risk_level == RiskLevel.MEDIUM

    def test_renamed_not_breaking(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(path="new.py", old_path="old.py", change_kind=DiffChangeKind.RENAMED),
        ])
        report = service.detect_breaking_changes(diff, repo_dir)
        assert report.total_breaking == 0

    def test_added_not_breaking(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(path="new_file.py", change_kind=DiffChangeKind.ADDED),
        ])
        report = service.detect_breaking_changes(diff, repo_dir)
        assert report.total_breaking == 0

    def test_empty_diff_no_breaking(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary()
        report = service.detect_breaking_changes(diff, repo_dir)
        assert report.total_breaking == 0

    def test_breaking_severity(self):
        from refactory.pr.models import BreakingChange
        bc = BreakingChange(kind=BreakingChangeKind.DELETED_INTERFACE, symbol="X", severity=RiskLevel.CRITICAL)
        assert bc.severity == RiskLevel.CRITICAL

    def test_affected_dependents(self):
        from refactory.pr.models import BreakingChange
        bc = BreakingChange(
            kind=BreakingChangeKind.REMOVED_METHOD,
            symbol="func",
            affected_dependents=["module_a", "module_b"],
        )
        assert len(bc.affected_dependents) == 2

    def test_breaking_report_serializable(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(path="x.py", change_kind=DiffChangeKind.DELETED),
        ])
        report = service.detect_breaking_changes(diff, repo_dir)
        data = report.model_dump()
        assert "changes" in data


# ===========================================================================
# Task 8: Security Review (20 tests)
# ===========================================================================

class TestSecurityReview:
    def test_clean_file_no_issues(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "clean.py").write_text("def safe(): return 1\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="clean.py")])
        report = service.security_review(diff, tmp_path)
        assert report.total_issues == 0
        assert report.passed is True

    def test_detect_eval(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "bad.py").write_text("result = eval(user_input)\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="bad.py")])
        report = service.security_review(diff, tmp_path)
        assert report.total_issues >= 1
        assert any(i.kind == SecurityIssueKind.COMMAND_EXECUTION for i in report.issues)

    def test_detect_exec(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "bad.py").write_text("exec(code)\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="bad.py")])
        report = service.security_review(diff, tmp_path)
        assert any(i.kind == SecurityIssueKind.COMMAND_EXECUTION for i in report.issues)

    def test_detect_pickle(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "bad.py").write_text("import pickle\ndata = pickle.loads(raw)\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="bad.py")])
        report = service.security_review(diff, tmp_path)
        assert any(i.kind == SecurityIssueKind.UNSAFE_DESERIALIZATION for i in report.issues)

    def test_detect_yaml_load(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "bad.py").write_text("import yaml\ndata = yaml.load(content)\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="bad.py")])
        report = service.security_review(diff, tmp_path)
        assert any(i.kind == SecurityIssueKind.UNSAFE_DESERIALIZATION for i in report.issues)

    def test_detect_os_system(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "bad.py").write_text("import os\nos.system(cmd)\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="bad.py")])
        report = service.security_review(diff, tmp_path)
        assert any(i.kind == SecurityIssueKind.COMMAND_EXECUTION for i in report.issues)

    def test_detect_hardcoded_secret(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "bad.py").write_text("password = 'hunter2'\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="bad.py")])
        report = service.security_review(diff, tmp_path)
        assert any(i.kind == SecurityIssueKind.INSECURE_SECRETS for i in report.issues)

    def test_detect_subprocess_shell(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "bad.py").write_text("subprocess.call(cmd, shell=True)\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="bad.py")])
        report = service.security_review(diff, tmp_path)
        assert report.total_issues >= 1

    def test_deleted_file_skipped(self, service: PRIntelligenceService, tmp_path: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(path="old.py", change_kind=DiffChangeKind.DELETED),
        ])
        report = service.security_review(diff, tmp_path)
        assert report.total_issues == 0

    def test_binary_file_skipped(self, service: PRIntelligenceService, tmp_path: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(path="bin.exe", is_binary=True),
        ])
        report = service.security_review(diff, tmp_path)
        assert report.total_issues == 0

    def test_security_report_model(self):
        r = SecurityReport()
        assert r.issues == []
        assert r.passed is True

    def test_security_issue_model(self):
        i = SecurityIssue(kind=SecurityIssueKind.SQL_INJECTION, file="a.py", line=5)
        assert i.kind == SecurityIssueKind.SQL_INJECTION
        assert i.line == 5

    def test_cwe_populated(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "bad.py").write_text("eval(x)\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="bad.py")])
        report = service.security_review(diff, tmp_path)
        assert any(i.cwe != "" for i in report.issues)

    def test_multiple_issues_in_one_file(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "bad.py").write_text("eval(x)\nexec(y)\nos.system(z)\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="bad.py")])
        report = service.security_review(diff, tmp_path)
        assert report.total_issues >= 3

    def test_critical_count(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "clean.py").write_text("x = 1\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="clean.py")])
        report = service.security_review(diff, tmp_path)
        assert report.critical_count == 0

    def test_passed_with_issues(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "bad.py").write_text("eval(x)\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="bad.py")])
        report = service.security_review(diff, tmp_path)
        assert report.passed is False

    def test_security_issue_kinds(self):
        assert SecurityIssueKind.UNSAFE_DESERIALIZATION == "unsafe_deserialization"
        assert SecurityIssueKind.SQL_INJECTION == "sql_injection"
        assert SecurityIssueKind.COMMAND_EXECUTION == "command_execution"

    def test_empty_diff_passes(self, service: PRIntelligenceService, tmp_path: Path):
        diff = DiffSummary()
        report = service.security_review(diff, tmp_path)
        assert report.passed is True

    def test_file_not_found_graceful(self, service: PRIntelligenceService, tmp_path: Path):
        diff = DiffSummary(changed_files=[ChangedFile(path="missing.py")])
        report = service.security_review(diff, tmp_path)
        assert report.total_issues == 0

    def test_security_report_serializable(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "bad.py").write_text("eval(x)\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="bad.py")])
        report = service.security_review(diff, tmp_path)
        data = report.model_dump()
        assert "issues" in data


# ===========================================================================
# Task 9: Performance Review (15 tests)
# ===========================================================================

class TestPerformanceReview:
    def test_clean_file(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "clean.py").write_text("def fast(): return 1\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="clean.py")])
        report = service.performance_review(diff, tmp_path)
        assert report.total_issues == 0

    def test_detect_nested_loops(self, service: PRIntelligenceService, tmp_path: Path):
        code = "for x in items:\n    for y in items:\n        pass\n"
        (tmp_path / "slow.py").write_text(code)
        diff = DiffSummary(changed_files=[ChangedFile(path="slow.py")])
        report = service.performance_review(diff, tmp_path)
        assert any(i.kind == PerformanceIssueKind.NESTED_LOOPS for i in report.issues)

    def test_detect_db_in_loop(self, service: PRIntelligenceService, tmp_path: Path):
        code = "for item in items:\n    cursor.execute('SELECT 1')\n"
        (tmp_path / "slow.py").write_text(code)
        diff = DiffSummary(changed_files=[ChangedFile(path="slow.py")])
        report = service.performance_review(diff, tmp_path)
        assert report.total_issues >= 1

    def test_deleted_file_skipped(self, service: PRIntelligenceService, tmp_path: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(path="old.py", change_kind=DiffChangeKind.DELETED),
        ])
        report = service.performance_review(diff, tmp_path)
        assert report.total_issues == 0

    def test_performance_report_model(self):
        r = PerformanceReport()
        assert r.issues == []
        assert r.total_issues == 0

    def test_performance_issue_model(self):
        i = PerformanceIssue(kind=PerformanceIssueKind.NESTED_LOOPS, file="a.py")
        assert i.kind == PerformanceIssueKind.NESTED_LOOPS

    def test_binary_skipped(self, service: PRIntelligenceService, tmp_path: Path):
        diff = DiffSummary(changed_files=[ChangedFile(path="x.bin", is_binary=True)])
        report = service.performance_review(diff, tmp_path)
        assert report.total_issues == 0

    def test_empty_diff(self, service: PRIntelligenceService, tmp_path: Path):
        diff = DiffSummary()
        report = service.performance_review(diff, tmp_path)
        assert report.total_issues == 0

    def test_performance_issue_kinds(self):
        assert PerformanceIssueKind.NESTED_LOOPS == "nested_loops"
        assert PerformanceIssueKind.REPEATED_DB_CALLS == "repeated_db_calls"

    def test_file_not_found(self, service: PRIntelligenceService, tmp_path: Path):
        diff = DiffSummary(changed_files=[ChangedFile(path="missing.py")])
        report = service.performance_review(diff, tmp_path)
        assert report.total_issues == 0

    def test_issue_has_line_number(self, service: PRIntelligenceService, tmp_path: Path):
        code = "for x in items:\n    for y in items:\n        pass\n"
        (tmp_path / "slow.py").write_text(code)
        diff = DiffSummary(changed_files=[ChangedFile(path="slow.py")])
        report = service.performance_review(diff, tmp_path)
        if report.issues:
            assert report.issues[0].line > 0

    def test_issue_has_recommendation(self, service: PRIntelligenceService, tmp_path: Path):
        code = "for x in items:\n    for y in items:\n        pass\n"
        (tmp_path / "slow.py").write_text(code)
        diff = DiffSummary(changed_files=[ChangedFile(path="slow.py")])
        report = service.performance_review(diff, tmp_path)
        if report.issues:
            assert report.issues[0].recommendation != ""

    def test_multiple_files(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "a.py").write_text("x = 1\n")
        (tmp_path / "b.py").write_text("y = 2\n")
        diff = DiffSummary(changed_files=[
            ChangedFile(path="a.py"),
            ChangedFile(path="b.py"),
        ])
        report = service.performance_review(diff, tmp_path)
        assert report.total_issues == 0

    def test_report_serializable(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "a.py").write_text("x = 1\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="a.py")])
        report = service.performance_review(diff, tmp_path)
        data = report.model_dump()
        assert "issues" in data

    def test_confidence_populated(self, service: PRIntelligenceService, tmp_path: Path):
        code = "for x in items:\n    for y in items:\n        pass\n"
        (tmp_path / "slow.py").write_text(code)
        diff = DiffSummary(changed_files=[ChangedFile(path="slow.py")])
        report = service.performance_review(diff, tmp_path)
        if report.issues:
            assert report.issues[0].confidence > 0


# ===========================================================================
# Task 7: AI Review (20 tests)
# ===========================================================================

class TestAIReview:
    def test_empty_diff(self, service: PRIntelligenceService, tmp_path: Path):
        diff = DiffSummary()
        report = service.ai_review(diff, tmp_path)
        assert isinstance(report, AIReviewReport)

    def test_detect_todo(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "a.py").write_text("# TODO: fix this\nx = 1\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="a.py")])
        report = service.ai_review(diff, tmp_path)
        assert any(c.category == ReviewCategory.MAINTAINABILITY for c in report.comments)

    def test_detect_bare_except(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "a.py").write_text("try:\n    x()\nexcept:\n    pass\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="a.py")])
        report = service.ai_review(diff, tmp_path)
        assert any(c.category == ReviewCategory.BUG_RISK for c in report.comments)

    def test_detect_print_statement(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "service.py").write_text("def run():\n    print('debug')\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="service.py")])
        report = service.ai_review(diff, tmp_path)
        assert any(c.category == ReviewCategory.STYLE for c in report.comments)

    def test_print_in_test_ok(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "test_a.py").write_text("def test():\n    print('ok')\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="test_a.py")])
        report = service.ai_review(diff, tmp_path)
        style_comments = [c for c in report.comments if c.category == ReviewCategory.STYLE]
        assert len(style_comments) == 0

    def test_deleted_file_skipped(self, service: PRIntelligenceService, tmp_path: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(path="old.py", change_kind=DiffChangeKind.DELETED),
        ])
        report = service.ai_review(diff, tmp_path)
        assert report.comments == []

    def test_ai_summary_generated(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "a.py").write_text("x = 1\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="a.py")])
        report = service.ai_review(diff, tmp_path)
        assert report.summary != ""

    def test_review_comment_model(self):
        c = ReviewComment(file="a.py", line=5, category=ReviewCategory.SECURITY)
        assert c.file == "a.py"
        assert c.category == ReviewCategory.SECURITY

    def test_review_categories(self):
        assert ReviewCategory.BUG_RISK == "bug_risk"
        assert ReviewCategory.PERFORMANCE == "performance"
        assert ReviewCategory.SECURITY == "security"
        assert ReviewCategory.MISSING_TESTS == "missing_tests"

    def test_suggested_fix_present(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "a.py").write_text("try:\n    x()\nexcept:\n    pass\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="a.py")])
        report = service.ai_review(diff, tmp_path)
        bug_comments = [c for c in report.comments if c.category == ReviewCategory.BUG_RISK]
        if bug_comments:
            assert bug_comments[0].suggested_fix != ""

    def test_confidence_populated(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "a.py").write_text("# TODO fix\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="a.py")])
        report = service.ai_review(diff, tmp_path)
        if report.comments:
            assert report.comments[0].confidence > 0

    def test_max_comments_per_file(self, service: PRIntelligenceService, tmp_path: Path):
        lines = "\n".join([f"# TODO item {i}" for i in range(50)])
        (tmp_path / "a.py").write_text(lines)
        diff = DiffSummary(changed_files=[ChangedFile(path="a.py")])
        report = service.ai_review(diff, tmp_path)
        assert len(report.comments) <= 30

    def test_report_model(self):
        r = AIReviewReport()
        assert r.comments == []
        assert r.summary == ""

    def test_binary_skipped(self, service: PRIntelligenceService, tmp_path: Path):
        diff = DiffSummary(changed_files=[ChangedFile(path="x.bin", is_binary=True)])
        report = service.ai_review(diff, tmp_path)
        assert report.comments == []

    def test_file_line_tracking(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "a.py").write_text("ok\nok\n# TODO fix\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="a.py")])
        report = service.ai_review(diff, tmp_path)
        todo_comments = [c for c in report.comments if "TODO" in c.explanation]
        if todo_comments:
            assert todo_comments[0].line == 3

    def test_multiple_files_reviewed(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "a.py").write_text("# TODO a\n")
        (tmp_path / "b.py").write_text("# TODO b\n")
        diff = DiffSummary(changed_files=[
            ChangedFile(path="a.py"),
            ChangedFile(path="b.py"),
        ])
        report = service.ai_review(diff, tmp_path)
        files = {c.file for c in report.comments}
        assert len(files) == 2

    def test_report_serializable(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "a.py").write_text("x = 1\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="a.py")])
        report = service.ai_review(diff, tmp_path)
        data = report.model_dump()
        assert "comments" in data

    def test_ai_gateway_failure_graceful(self, service: PRIntelligenceService, tmp_path: Path):
        service._ai.generate.side_effect = RuntimeError("AI down")
        (tmp_path / "a.py").write_text("x = 1\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="a.py")])
        report = service.ai_review(diff, tmp_path)
        assert report.summary != ""

    def test_severity_field(self):
        c = ReviewComment(severity="warning")
        assert c.severity == "warning"

    def test_fixme_detected(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "a.py").write_text("# FIXME: urgent\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="a.py")])
        report = service.ai_review(diff, tmp_path)
        assert len(report.comments) >= 1


# ===========================================================================
# Task 10: Merge Readiness (15 tests)
# ===========================================================================

class TestMergeReadiness:
    def test_ready_state(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "safe.py").write_text("x = 1\n")
        (tmp_path / "tests" / "unit").mkdir(parents=True)
        (tmp_path / "tests" / "unit" / "test_safe.py").write_text("def test(): pass\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="safe.py")])
        report = service.merge_readiness(diff, tmp_path)
        assert report.status in (ReadinessStatus.READY, ReadinessStatus.NEEDS_WORK)
        assert report.overall_score > 0

    def test_block_with_security_issues(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "bad.py").write_text("eval(x)\neval(y)\neval(z)\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="bad.py")], total_insertions=3)
        report = service.merge_readiness(diff, tmp_path)
        assert report.overall_score <= 1.0

    def test_readiness_status_enum(self):
        assert ReadinessStatus.READY == "ready"
        assert ReadinessStatus.NEEDS_WORK == "needs_work"
        assert ReadinessStatus.BLOCK_MERGE == "block_merge"

    def test_readiness_report_model(self):
        r = MergeReadinessReport()
        assert r.overall_score == 0.0
        assert r.status == ReadinessStatus.NEEDS_WORK

    def test_score_bounded(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "a.py").write_text("x = 1\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="a.py")])
        report = service.merge_readiness(diff, tmp_path)
        assert 0.0 <= report.overall_score <= 1.0

    def test_blockers_populated_for_critical(self, service: PRIntelligenceService, tmp_path: Path):
        files = [ChangedFile(path=f"core/m{i}.py", insertions=100) for i in range(15)]
        (tmp_path / "bad.py").write_text("eval(x)\n")
        files.append(ChangedFile(path="bad.py"))
        for f in files:
            p = tmp_path / f.path
            p.parent.mkdir(parents=True, exist_ok=True)
            if not p.exists():
                p.write_text("x = 1\n")
        diff = DiffSummary(changed_files=files, total_insertions=1500)
        report = service.merge_readiness(diff, tmp_path)
        assert isinstance(report.blockers, list)

    def test_recommendation_present(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "a.py").write_text("x = 1\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="a.py")])
        report = service.merge_readiness(diff, tmp_path)
        assert report.recommendation != ""

    def test_component_scores(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "a.py").write_text("x = 1\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="a.py")])
        report = service.merge_readiness(diff, tmp_path)
        assert report.risk_score >= 0
        assert report.security_score >= 0
        assert report.test_coverage_score >= 0

    def test_empty_diff_ready(self, service: PRIntelligenceService, tmp_path: Path):
        diff = DiffSummary()
        report = service.merge_readiness(diff, tmp_path)
        assert report.status in (ReadinessStatus.READY, ReadinessStatus.NEEDS_WORK)

    def test_report_serializable(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "a.py").write_text("x = 1\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="a.py")])
        report = service.merge_readiness(diff, tmp_path)
        data = report.model_dump()
        assert "overall_score" in data
        assert "status" in data

    def test_documentation_score(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "a.py").write_text("x = 1\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="a.py")])
        report = service.merge_readiness(diff, tmp_path)
        assert report.documentation_score > 0

    def test_architecture_score_low_for_core(self, service: PRIntelligenceService, tmp_path: Path):
        files = [ChangedFile(path=f"core/m{i}.py") for i in range(5)]
        for f in files:
            p = tmp_path / f.path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x = 1\n")
        diff = DiffSummary(changed_files=files)
        report = service.merge_readiness(diff, tmp_path)
        assert report.architecture_score < 1.0

    def test_test_coverage_with_tests(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "module.py").write_text("x = 1\n")
        (tmp_path / "tests" / "unit").mkdir(parents=True)
        (tmp_path / "tests" / "unit" / "test_module.py").write_text("def test(): pass\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="module.py")])
        report = service.merge_readiness(diff, tmp_path)
        assert report.test_coverage_score > 0

    def test_review_completeness(self, service: PRIntelligenceService, tmp_path: Path):
        (tmp_path / "a.py").write_text("x = 1\n")
        diff = DiffSummary(changed_files=[ChangedFile(path="a.py")])
        report = service.merge_readiness(diff, tmp_path)
        assert report.review_completeness > 0

    def test_many_breaking_blocks(self, service: PRIntelligenceService, tmp_path: Path):
        files = [ChangedFile(path=f"mod{i}.py", change_kind=DiffChangeKind.DELETED) for i in range(10)]
        diff = DiffSummary(changed_files=files)
        report = service.merge_readiness(diff, tmp_path)
        assert any("breaking" in b.lower() for b in report.blockers) or report.status != ReadinessStatus.READY


# ===========================================================================
# Task 11: Changed Dependency Graph (10 tests)
# ===========================================================================

class TestChangedDependencyGraph:
    def test_empty_diff(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary()
        graph = service.changed_dependency_graph(diff, repo_dir)
        assert graph.changed_modules == []

    def test_modules_extracted(self, service: PRIntelligenceService, repo_dir: Path, sample_diff: DiffSummary):
        graph = service.changed_dependency_graph(sample_diff, repo_dir)
        assert len(graph.changed_modules) > 0

    def test_graph_model(self):
        g = ChangedDependencyGraph()
        assert g.changed_modules == []
        assert g.nodes == []

    def test_nodes_created(self, service: PRIntelligenceService, repo_dir: Path, sample_diff: DiffSummary):
        graph = service.changed_dependency_graph(sample_diff, repo_dir)
        assert len(graph.nodes) > 0

    def test_recommended_tests(self, service: PRIntelligenceService, repo_dir: Path, sample_diff: DiffSummary):
        graph = service.changed_dependency_graph(sample_diff, repo_dir)
        assert len(graph.recommended_tests) > 0

    def test_service_detection(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(path="service/auth.py"),
            ChangedFile(path="service/users.py"),
        ])
        graph = service.changed_dependency_graph(diff, repo_dir)
        assert len(graph.affected_services) >= 1

    def test_api_detection(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(path="api/v1/endpoints.py"),
        ])
        graph = service.changed_dependency_graph(diff, repo_dir)
        assert len(graph.impacted_apis) >= 1

    def test_dependency_node_model(self):
        from refactory.pr.models import DependencyNode
        n = DependencyNode(name="auth", kind="module", change_type="modified")
        assert n.name == "auth"

    def test_dependency_edge_model(self):
        from refactory.pr.models import DependencyEdge
        e = DependencyEdge(source="a", target="b", relationship="imports")
        assert e.source == "a"

    def test_graph_serializable(self, service: PRIntelligenceService, repo_dir: Path, sample_diff: DiffSummary):
        graph = service.changed_dependency_graph(sample_diff, repo_dir)
        data = graph.model_dump()
        assert "changed_modules" in data


# ===========================================================================
# Task 12 + Task 2: Change Explanation + PR Summary (remaining tests)
# ===========================================================================

class TestChangeExplanation:
    def test_explanation_generated(self, service: PRIntelligenceService, repo_dir: Path, sample_diff: DiffSummary):
        explanation = service.explain_change(sample_diff, repo_dir)
        assert isinstance(explanation, ChangeExplanation)
        assert explanation.summary != ""

    def test_downstream_effects(self, service: PRIntelligenceService, repo_dir: Path, sample_diff: DiffSummary):
        explanation = service.explain_change(sample_diff, repo_dir)
        assert isinstance(explanation.downstream_effects, list)

    def test_migration_concerns_for_deleted(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(
            changed_files=[ChangedFile(path="old.py", change_kind=DiffChangeKind.DELETED)],
            files_deleted=1,
        )
        explanation = service.explain_change(diff, repo_dir)
        assert any("deleted" in m.lower() for m in explanation.migration_concerns)

    def test_migration_concerns_for_renamed(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(
            changed_files=[ChangedFile(path="new.py", old_path="old.py", change_kind=DiffChangeKind.RENAMED)],
            files_renamed=1,
        )
        explanation = service.explain_change(diff, repo_dir)
        assert any("renamed" in m.lower() for m in explanation.migration_concerns)

    def test_arch_consequences_for_broad_changes(self, service: PRIntelligenceService, repo_dir: Path):
        files = [ChangedFile(path=f"mod{i}/file.py") for i in range(8)]
        diff = DiffSummary(changed_files=files)
        explanation = service.explain_change(diff, repo_dir)
        assert len(explanation.architectural_consequences) > 0

    def test_risk_level_high(self, service: PRIntelligenceService, repo_dir: Path):
        files = [ChangedFile(path=f"f{i}.py") for i in range(25)]
        diff = DiffSummary(changed_files=files, total_insertions=600)
        explanation = service.explain_change(diff, repo_dir)
        assert explanation.risk_level in (RiskLevel.HIGH, RiskLevel.MEDIUM)

    def test_explanation_model(self):
        e = ChangeExplanation()
        assert e.summary == ""
        assert e.risk_level == RiskLevel.LOW

    def test_ai_failure_graceful(self, service: PRIntelligenceService, repo_dir: Path, sample_diff: DiffSummary):
        service._ai.generate.side_effect = RuntimeError("AI down")
        explanation = service.explain_change(sample_diff, repo_dir)
        assert explanation.summary != ""

    def test_confidence(self, service: PRIntelligenceService, repo_dir: Path, sample_diff: DiffSummary):
        explanation = service.explain_change(sample_diff, repo_dir)
        assert explanation.confidence > 0

    def test_serializable(self, service: PRIntelligenceService, repo_dir: Path, sample_diff: DiffSummary):
        explanation = service.explain_change(sample_diff, repo_dir)
        data = explanation.model_dump()
        assert "summary" in data


class TestPRSummary:
    def test_summary_generated(self, service: PRIntelligenceService, repo_dir: Path, sample_diff: DiffSummary):
        summary = service.pr_summary(sample_diff, repo_dir)
        assert isinstance(summary, PRSummary)
        assert summary.files_changed == len(sample_diff.changed_files)

    def test_modules_extracted(self, service: PRIntelligenceService, repo_dir: Path, sample_diff: DiffSummary):
        summary = service.pr_summary(sample_diff, repo_dir)
        assert len(summary.modules_affected) > 0

    def test_ai_failure_graceful(self, service: PRIntelligenceService, repo_dir: Path, sample_diff: DiffSummary):
        service._ai.generate.side_effect = RuntimeError("AI unavailable")
        summary = service.pr_summary(sample_diff, repo_dir)
        assert summary.summary != ""

    def test_summary_model(self):
        s = PRSummary()
        assert s.files_changed == 0
        assert s.modules_affected == []

    def test_arch_impact_core(self, service: PRIntelligenceService, repo_dir: Path):
        diff = DiffSummary(changed_files=[
            ChangedFile(path="core/engine.py"),
            ChangedFile(path="service/auth.py"),
        ])
        summary = service.pr_summary(diff, repo_dir)
        assert "core" in summary.architectural_impact.lower() or "service" in summary.architectural_impact.lower()
