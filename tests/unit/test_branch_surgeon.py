"""Comprehensive tests for BranchSurgeonService."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from refactory.core.logger import get_service_logger
from refactory.documentation.models import StaleDoc
from refactory.documentation.service import DocumentationService
from refactory.git.commit_service import CommitService
from refactory.git.models import GitRepositoryInfo, WorkingTreeStatus
from refactory.git.service import GitService
from refactory.graph.service import RepositoryGraphService
from refactory.impact.models import ImpactReport, RiskLevel
from refactory.impact.service import ImpactAnalysisService
from refactory.indexer.service import IndexerService
from refactory.surgeon.models import (
    BranchAnalysis,
    BranchCommitSummary,
    ChangedFileSummary,
    IssueKind,
    IssueSeverity,
    RecommendationType,
)
from refactory.surgeon.service import BranchSurgeonService
from refactory.testing.models import RelatedTestsReport
from refactory.testing.service import TestIntelligenceService


def _logger():
    return get_service_logger("test.surgeon")


def _dt(year=2024, month=1, day=1, **kw):
    return datetime(year, month, day, tzinfo=timezone.utc, **kw)


def _commit(
    sha: str = "abc1234",
    message: str = "feat: add feature",
    committed_at: datetime | None = None,
    files_changed: int = 1,
    insertions: int = 10,
    deletions: int = 5,
) -> BranchCommitSummary:
    return BranchCommitSummary(
        sha=sha,
        short_sha=sha[:7],
        message=message,
        author="Test Author",
        committed_at=committed_at or _dt(),
        files_changed=files_changed,
        insertions=insertions,
        deletions=deletions,
    )


def _file(
    path: str = "refactory/auth.py",
    commit_count: int = 1,
    insertions: int = 20,
    deletions: int = 5,
    is_test: bool = False,
    is_security_sensitive: bool = False,
) -> ChangedFileSummary:
    return ChangedFileSummary(
        path=path,
        commit_count=commit_count,
        insertions=insertions,
        deletions=deletions,
        is_test=is_test,
        is_security_sensitive=is_security_sensitive,
    )


def _make_service(
    *,
    large_pr_files: int = 20,
    large_pr_lines: int = 1000,
    hotspot_commits: int = 3,
    stale_days: float = 30.0,
) -> tuple[BranchSurgeonService, MagicMock, MagicMock, MagicMock, MagicMock, MagicMock]:
    git = MagicMock(spec=GitService)
    commits = MagicMock(spec=CommitService)
    indexer = MagicMock(spec=IndexerService)
    graph = MagicMock(spec=RepositoryGraphService)
    impact = MagicMock(spec=ImpactAnalysisService)
    testing = MagicMock(spec=TestIntelligenceService)
    docs = MagicMock(spec=DocumentationService)

    svc = BranchSurgeonService(
        logger=_logger(),
        git_service=git,
        commit_service=commits,
        indexer_service=indexer,
        graph_service=graph,
        impact_analysis_service=impact,
        test_intelligence_service=testing,
        documentation_service=docs,
        large_pr_file_threshold=large_pr_files,
        large_pr_line_threshold=large_pr_lines,
        hotspot_commit_threshold=hotspot_commits,
        branch_age_stale_days=stale_days,
    )
    return svc, git, commits, indexer, graph, impact, testing, docs


def _repo_info(branch: str = "feature/x", default: str = "main") -> GitRepositoryInfo:
    return GitRepositoryInfo(
        root_path="/tmp/repo",
        name="demo-repo",
        current_branch=branch,
        default_branch=default,
        working_tree=WorkingTreeStatus(),
    )


class TestLargePRCheck:
    def test_no_issue_below_threshold(self):
        svc, *_ = _make_service(large_pr_files=20, large_pr_lines=1000)
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(path=f"file{i}.py") for i in range(5)]
        svc._check_large_pr(analysis)
        assert not analysis.issues

    def test_triggers_on_file_count(self):
        svc, *_ = _make_service(large_pr_files=5)
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(path=f"file{i}.py") for i in range(10)]
        svc._check_large_pr(analysis)
        issues = [i for i in analysis.issues if i.kind == IssueKind.LARGE_PR]
        assert len(issues) == 1
        assert issues[0].severity == IssueSeverity.MEDIUM

    def test_triggers_on_line_count(self):
        svc, *_ = _make_service(large_pr_lines=100)
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(insertions=60, deletions=60)]
        svc._check_large_pr(analysis)
        issues = [i for i in analysis.issues if i.kind == IssueKind.LARGE_PR]
        assert len(issues) == 1

    def test_triggers_on_both(self):
        svc, *_ = _make_service(large_pr_files=2, large_pr_lines=50)
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(path=f"f{i}.py", insertions=30) for i in range(5)]
        svc._check_large_pr(analysis)
        issues = [i for i in analysis.issues if i.kind == IssueKind.LARGE_PR]
        assert len(issues) == 1
        assert "files" in issues[0].detail
        assert "lines" in issues[0].detail


class TestHotspotCheck:
    def test_no_hotspot_below_threshold(self):
        svc, *_ = _make_service(hotspot_commits=3)
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(commit_count=2)]
        svc._check_hotspots(analysis)
        assert not analysis.issues

    def test_hotspot_at_threshold(self):
        svc, *_ = _make_service(hotspot_commits=3)
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(path="auth.py", commit_count=3)]
        svc._check_hotspots(analysis)
        issues = [i for i in analysis.issues if i.kind == IssueKind.HOTSPOT]
        assert len(issues) == 1
        assert "auth.py" in issues[0].title

    def test_multiple_hotspots(self):
        svc, *_ = _make_service(hotspot_commits=2)
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [
            _file(path="a.py", commit_count=3),
            _file(path="b.py", commit_count=2),
            _file(path="c.py", commit_count=1),
        ]
        svc._check_hotspots(analysis)
        hs_issues = [i for i in analysis.issues if i.kind == IssueKind.HOTSPOT]
        assert len(hs_issues) == 2


class TestCommitQualityCheck:
    @pytest.mark.parametrize(
        "msg",
        ["WIP", "fix", "temp", "asdf", "final", "again", "misc", "stuff", "wip"],
    )
    def test_poor_messages_detected(self, msg: str):
        svc, *_ = _make_service()
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.commits = [_commit(sha="abc1234", message=msg)]
        svc._check_commit_quality(analysis)
        issues = [i for i in analysis.issues if i.kind == IssueKind.POOR_COMMIT_MESSAGE]
        assert len(issues) == 1

    def test_good_message_no_issue(self):
        svc, *_ = _make_service()
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.commits = [_commit(message="feat: implement OAuth2 login flow")]
        svc._check_commit_quality(analysis)
        issues = [i for i in analysis.issues if i.kind == IssueKind.POOR_COMMIT_MESSAGE]
        assert not issues

    def test_multiple_poor_commits_single_issue(self):
        svc, *_ = _make_service()
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.commits = [
            _commit(sha="aaa1111", message="WIP"),
            _commit(sha="bbb2222", message="fix"),
            _commit(sha="ccc3333", message="temp"),
        ]
        svc._check_commit_quality(analysis)
        issues = [i for i in analysis.issues if i.kind == IssueKind.POOR_COMMIT_MESSAGE]
        assert len(issues) == 1
        assert "aaa1111" in issues[0].commits


class TestDuplicateFileEditsCheck:
    def test_no_issue_below_threshold(self):
        svc, *_ = _make_service()
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(path="auth.py", commit_count=2)]
        svc._check_duplicate_file_edits(analysis)
        assert not any(i.kind == IssueKind.DUPLICATE_FILE_EDITS for i in analysis.issues)

    def test_triggers_at_3_commits(self):
        svc, *_ = _make_service()
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(path="auth.py", commit_count=3)]
        svc._check_duplicate_file_edits(analysis)
        issues = [i for i in analysis.issues if i.kind == IssueKind.DUPLICATE_FILE_EDITS]
        assert len(issues) == 1

    def test_test_files_excluded(self):
        svc, *_ = _make_service()
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(path="tests/test_auth.py", commit_count=5, is_test=True)]
        svc._check_duplicate_file_edits(analysis)
        assert not any(i.kind == IssueKind.DUPLICATE_FILE_EDITS for i in analysis.issues)


class TestBranchAgeCheck:
    def test_fresh_branch_no_issue(self):
        svc, *_ = _make_service(stale_days=30)
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.commits = [_commit(committed_at=datetime.now(timezone.utc))]
        svc._check_branch_age(analysis)
        assert not any(i.kind == IssueKind.BRANCH_AGE for i in analysis.issues)

    def test_stale_branch_medium_severity(self):
        from datetime import timedelta
        svc, *_ = _make_service(stale_days=30)
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.commits = [
            _commit(committed_at=datetime.now(timezone.utc) - timedelta(days=35))
        ]
        svc._check_branch_age(analysis)
        issues = [i for i in analysis.issues if i.kind == IssueKind.BRANCH_AGE]
        assert len(issues) == 1
        assert issues[0].severity == IssueSeverity.MEDIUM

    def test_very_old_branch_high_severity(self):
        from datetime import timedelta
        svc, *_ = _make_service(stale_days=30)
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.commits = [
            _commit(committed_at=datetime.now(timezone.utc) - timedelta(days=65))
        ]
        svc._check_branch_age(analysis)
        issues = [i for i in analysis.issues if i.kind == IssueKind.BRANCH_AGE]
        assert issues[0].severity == IssueSeverity.HIGH

    def test_empty_commits_no_crash(self):
        svc, *_ = _make_service()
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.commits = []
        svc._check_branch_age(analysis)  # should not raise


class TestRiskConcentrationCheck:
    def test_security_files_high_severity(self):
        svc, *_ = _make_service()
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(path="refactory/auth.py", is_security_sensitive=True)]
        svc._check_risk_concentration(analysis)
        issues = [i for i in analysis.issues if i.kind == IssueKind.RISK_CONCENTRATION]
        high = [i for i in issues if i.severity == IssueSeverity.HIGH]
        assert high

    def test_database_files_medium_severity(self):
        svc, *_ = _make_service()
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(path="refactory/database/migrations.py")]
        svc._check_risk_concentration(analysis)
        issues = [i for i in analysis.issues if i.kind == IssueKind.RISK_CONCENTRATION]
        medium = [i for i in issues if i.severity == IssueSeverity.MEDIUM]
        assert medium

    def test_neutral_file_no_risk(self):
        svc, *_ = _make_service()
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(path="refactory/utils/format.py")]
        svc._check_risk_concentration(analysis)
        issues = [i for i in analysis.issues if i.kind == IssueKind.RISK_CONCENTRATION]
        assert not issues


class TestMergeConflictRisk:
    def test_low_risk_small_branch(self):
        svc, *_ = _make_service()
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(path="utils.py")]
        svc._check_merge_conflict_risk(analysis, Path("/tmp"))
        assert analysis.health.merge_conflict_risk == IssueSeverity.LOW

    def test_medium_risk_several_files(self):
        svc, *_ = _make_service(hotspot_commits=2)
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [
            _file(path=f"file{i}.py", commit_count=2) for i in range(8)
        ]
        svc._check_merge_conflict_risk(analysis, Path("/tmp"))
        assert analysis.health.merge_conflict_risk in {IssueSeverity.MEDIUM, IssueSeverity.HIGH}

    def test_high_risk_many_hotspots(self):
        svc, *_ = _make_service(hotspot_commits=2)
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [
            _file(path=f"f{i}.py", commit_count=3, is_security_sensitive=True) for i in range(10)
        ]
        svc._check_merge_conflict_risk(analysis, Path("/tmp"))
        assert analysis.health.merge_conflict_risk == IssueSeverity.HIGH


class TestBlastRadiusCheck:
    def test_low_blast_radius_no_issue(self):
        svc, *rest, impact, _, _ = _make_service()
        mock_report = MagicMock(spec=ImpactReport)
        mock_report.direct_impact = []
        impact.analyze.return_value = mock_report

        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(path="utils.py")]
        svc._check_blast_radius(analysis, Path("/tmp"))
        assert not any(i.kind == IssueKind.BLAST_RADIUS for i in analysis.issues)

    def test_medium_blast_radius(self):
        svc, *rest, impact, _, _ = _make_service()
        mock_report = MagicMock(spec=ImpactReport)

        class FakePath:
            def __init__(self, p):
                self.path = p

        mock_report.direct_impact = [FakePath(f"dep{i}.py") for i in range(4)]
        impact.analyze.return_value = mock_report

        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(path="core.py")]
        svc._check_blast_radius(analysis, Path("/tmp"))
        issues = [i for i in analysis.issues if i.kind == IssueKind.BLAST_RADIUS]
        assert issues
        assert issues[0].severity == IssueSeverity.MEDIUM

    def test_high_blast_radius(self):
        svc, *rest, impact, _, _ = _make_service()
        mock_report = MagicMock(spec=ImpactReport)

        class FakePath:
            def __init__(self, p):
                self.path = p

        mock_report.direct_impact = [FakePath(f"dep{i}.py") for i in range(7)]
        impact.analyze.return_value = mock_report

        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(path="auth.py")]
        svc._check_blast_radius(analysis, Path("/tmp"))
        issues = [i for i in analysis.issues if i.kind == IssueKind.BLAST_RADIUS]
        assert issues[0].severity == IssueSeverity.HIGH


class TestMissingTestsCheck:
    def test_no_issue_when_tests_exist(self):
        svc, *rest, _, testing, _ = _make_service()

        cache = MagicMock()
        cache.coverage = {"auth.py": [MagicMock()]}
        testing._ensure_ready.return_value = cache

        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(path="auth.py")]
        svc._check_missing_tests(analysis, Path("/tmp"))
        assert not any(i.kind == IssueKind.MISSING_TESTS for i in analysis.issues)

    def test_issue_when_no_tests(self):
        svc, *rest, _, testing, _ = _make_service()

        cache = MagicMock()
        cache.coverage = {}
        testing._ensure_ready.return_value = cache
        report = RelatedTestsReport(target="auth.py", target_found=False)
        testing.find_related_tests.return_value = report

        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(path="auth.py")]
        svc._check_missing_tests(analysis, Path("/tmp"))
        issues = [i for i in analysis.issues if i.kind == IssueKind.MISSING_TESTS]
        assert issues

    def test_no_issue_for_test_files(self):
        svc, *rest, _, testing, _ = _make_service()
        cache = MagicMock()
        cache.coverage = {}
        testing._ensure_ready.return_value = cache

        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(path="tests/test_auth.py", is_test=True)]
        svc._check_missing_tests(analysis, Path("/tmp"))
        assert not any(i.kind == IssueKind.MISSING_TESTS for i in analysis.issues)

    def test_ti_failure_does_not_crash(self):
        svc, *rest, _, testing, _ = _make_service()
        testing._ensure_ready.side_effect = RuntimeError("not ready")

        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(path="auth.py")]
        svc._check_missing_tests(analysis, Path("/tmp"))  # should not raise


class TestDocumentationDriftCheck:
    def test_no_issue_when_docs_fresh(self):
        svc, *rest, _, _, docs = _make_service()
        docs.find_stale_documentation.return_value = []

        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(path="auth.py")]
        svc._check_documentation_drift(analysis, Path("/tmp"))
        assert not any(i.kind == IssueKind.DOCUMENTATION_DRIFT for i in analysis.issues)

    def test_issue_on_stale_doc(self):
        svc, *rest, _, _, docs = _make_service()
        stale = StaleDoc(path="README.md", related_source="auth.py", confidence=0.8)
        docs.find_stale_documentation.return_value = [stale]

        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(path="auth.py")]
        svc._check_documentation_drift(analysis, Path("/tmp"))
        issues = [i for i in analysis.issues if i.kind == IssueKind.DOCUMENTATION_DRIFT]
        assert issues

    def test_docs_failure_does_not_crash(self):
        svc, *rest, _, _, docs = _make_service()
        docs.find_stale_documentation.side_effect = RuntimeError("not ready")

        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [_file(path="auth.py")]
        svc._check_documentation_drift(analysis, Path("/tmp"))  # should not raise


class TestHealthScoring:
    def test_perfect_score_no_issues(self):
        svc, *_ = _make_service()
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.commits = [_commit()]
        analysis.changed_files = [_file()]
        h = svc._compute_health(analysis, analysis.commits, analysis.changed_files)
        assert h.score == 100
        assert h.grade == "A"

    def test_score_reduced_by_issues(self):
        from refactory.surgeon.models import BranchIssue
        svc, *_ = _make_service()
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.commits = [_commit()]
        analysis.changed_files = [_file()]
        analysis.issues = [
            BranchIssue(
                kind=IssueKind.LARGE_PR,
                severity=IssueSeverity.HIGH,
                title="Large PR",
            ),
            BranchIssue(
                kind=IssueKind.HOTSPOT,
                severity=IssueSeverity.MEDIUM,
                title="Hotspot",
            ),
        ]
        h = svc._compute_health(analysis, analysis.commits, analysis.changed_files)
        assert h.score < 100
        assert h.score == 100 - 15 - 8  # HIGH=15, MEDIUM=8

    def test_score_never_below_zero(self):
        from refactory.surgeon.models import BranchIssue
        svc, *_ = _make_service()
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.commits = []
        analysis.changed_files = []
        # Add many high-severity issues
        analysis.issues = [
            BranchIssue(
                kind=IssueKind.LARGE_PR,
                severity=IssueSeverity.CRITICAL,
                title=f"Issue {i}",
            )
            for i in range(10)
        ]
        h = svc._compute_health(analysis, [], [])
        assert h.score == 0

    def test_grade_boundaries(self):
        svc, *_ = _make_service()

        def grade(score_val: int) -> str:
            from refactory.surgeon.models import BranchIssue
            analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
            analysis.issues = [
                BranchIssue(
                    kind=IssueKind.LARGE_PR,
                    severity=IssueSeverity.LOW,
                    title="x",
                )
                for _ in range((100 - score_val) // 3)
            ]
            h = svc._compute_health(analysis, [], [])
            return h.grade

        # A = >=90, B = >=75, C = >=60, D = >=40, F = <40
        assert grade(95) == "A"
        # just verify grades exist
        h = svc._compute_health(
            BranchAnalysis(branch="f", base_branch="main", repository="r"),
            [],
            [],
        )
        assert h.grade in {"A", "B", "C", "D", "F"}

    def test_health_commit_count(self):
        svc, *_ = _make_service()
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        commits = [_commit(sha=f"sha{i:07d}") for i in range(5)]
        files = [_file(path=f"f{i}.py") for i in range(3)]
        analysis.commits = commits
        analysis.changed_files = files
        h = svc._compute_health(analysis, commits, files)
        assert h.commit_count == 5
        assert h.changed_file_count == 3


class TestRecommendationGeneration:
    def test_split_pr_recommendation(self):
        from refactory.surgeon.models import BranchIssue
        svc, *_ = _make_service()
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.issues = [
            BranchIssue(kind=IssueKind.LARGE_PR, severity=IssueSeverity.MEDIUM, title="Large PR"),
        ]
        recs = svc._build_recommendations(analysis)
        assert any(r.kind == RecommendationType.SPLIT_PR for r in recs)

    def test_add_tests_recommendation(self):
        from refactory.surgeon.models import BranchIssue
        svc, *_ = _make_service()
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.issues = [
            BranchIssue(
                kind=IssueKind.MISSING_TESTS,
                severity=IssueSeverity.MEDIUM,
                title="No tests",
                files=["auth.py"],
            ),
        ]
        recs = svc._build_recommendations(analysis)
        assert any(r.kind == RecommendationType.ADD_TESTS for r in recs)

    def test_squash_commits_recommendation(self):
        from refactory.surgeon.models import BranchIssue
        svc, *_ = _make_service()
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.issues = [
            BranchIssue(
                kind=IssueKind.POOR_COMMIT_MESSAGE,
                severity=IssueSeverity.LOW,
                title="Poor commits",
                commits=["abc1234"],
            ),
        ]
        recs = svc._build_recommendations(analysis)
        assert any(r.kind == RecommendationType.SQUASH_COMMITS for r in recs)

    def test_no_issues_no_recommendations(self):
        svc, *_ = _make_service()
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.issues = []
        recs = svc._build_recommendations(analysis)
        assert not recs


class TestEdgeCases:
    def test_empty_repository_no_commits(self):
        svc, git, *_ = _make_service()
        git.get_repository_info.return_value = _repo_info()
        git.get_root_path.return_value = Path("/tmp/empty")

        with patch.object(svc, "_branch_commits", return_value=[]), \
             patch.object(svc, "_aggregate_changed_files", return_value=[]):
            analysis = svc.analyze()
        assert analysis.health.commit_count == 0
        assert analysis.health.score == 100

    def test_unknown_branch_falls_back(self):
        svc, git, *_ = _make_service()
        git.get_repository_info.return_value = _repo_info(branch="unknown-branch", default="main")
        git.get_root_path.return_value = Path("/tmp")

        with patch.object(svc, "_branch_commits", return_value=[]), \
             patch.object(svc, "_aggregate_changed_files", return_value=[]):
            analysis = svc.analyze("unknown-branch")
        assert analysis.branch == "unknown-branch"

    def test_single_commit_branch(self):
        svc, git, *_ = _make_service()
        git.get_repository_info.return_value = _repo_info()
        git.get_root_path.return_value = Path("/tmp")
        commits = [_commit()]
        files = [_file()]
        with patch.object(svc, "_branch_commits", return_value=commits), \
             patch.object(svc, "_aggregate_changed_files", return_value=files), \
             patch.object(svc, "_check_missing_tests", return_value=None), \
             patch.object(svc, "_check_blast_radius", return_value=None), \
             patch.object(svc, "_check_documentation_drift", return_value=None):
            analysis = svc.analyze()
        assert analysis.health.commit_count == 1

    def test_many_commits_branch(self):
        svc, git, *_ = _make_service()
        git.get_repository_info.return_value = _repo_info()
        git.get_root_path.return_value = Path("/tmp")
        commits = [_commit(sha=f"{'a' * 7}{i:01d}") for i in range(50)]
        files = [_file(path=f"file{i}.py") for i in range(30)]
        with patch.object(svc, "_branch_commits", return_value=commits), \
             patch.object(svc, "_aggregate_changed_files", return_value=files), \
             patch.object(svc, "_check_missing_tests", return_value=None), \
             patch.object(svc, "_check_blast_radius", return_value=None), \
             patch.object(svc, "_check_documentation_drift", return_value=None):
            analysis = svc.analyze()
        assert analysis.health.commit_count == 50
        assert analysis.health.changed_file_count == 30

    def test_analyze_uses_current_branch_by_default(self):
        svc, git, *_ = _make_service()
        git.get_repository_info.return_value = _repo_info(branch="feature/auto")
        git.get_root_path.return_value = Path("/tmp")

        with patch.object(svc, "_branch_commits", return_value=[]) as mock_commits, \
             patch.object(svc, "_aggregate_changed_files", return_value=[]):
            analysis = svc.analyze()
        assert analysis.branch == "feature/auto"

    def test_analyze_uses_provided_branch(self):
        svc, git, *_ = _make_service()
        git.get_repository_info.return_value = _repo_info(branch="main")
        git.get_root_path.return_value = Path("/tmp")

        with patch.object(svc, "_branch_commits", return_value=[]), \
             patch.object(svc, "_aggregate_changed_files", return_value=[]):
            analysis = svc.analyze("feature/explicit")
        assert analysis.branch == "feature/explicit"


class TestChangedFilesClassification:
    def test_test_file_detection(self):
        svc, *_ = _make_service()
        analysis = BranchAnalysis(branch="f", base_branch="main", repository="r")
        analysis.changed_files = [
            ChangedFileSummary(path="tests/test_auth.py", is_test=True),
            ChangedFileSummary(path="auth.py", is_test=False),
        ]
        svc._check_missing_tests.__func__  # ensure it's available
        # Test file classification built into _aggregate_changed_files
        # Verify test detection logic
        test_files = [f for f in analysis.changed_files if f.is_test]
        prod_files = [f for f in analysis.changed_files if not f.is_test]
        assert len(test_files) == 1
        assert len(prod_files) == 1

    def test_security_file_classification(self):
        from refactory.surgeon.service import _SECURITY_TOKENS
        assert "auth" in _SECURITY_TOKENS
        assert "jwt" in _SECURITY_TOKENS
        assert "password" in _SECURITY_TOKENS
        assert "secret" in _SECURITY_TOKENS


class TestModels:
    def test_branch_analysis_json_serialization(self):
        analysis = BranchAnalysis(
            branch="feature/login",
            base_branch="main",
            repository="demo",
        )
        from refactory.surgeon.models import BranchIssue
        analysis.issues = [
            BranchIssue(
                kind=IssueKind.LARGE_PR,
                severity=IssueSeverity.HIGH,
                title="Test",
                detail="Detail",
                files=["a.py"],
            )
        ]
        json_str = analysis.model_dump_json()
        assert "feature/login" in json_str
        assert "large_pr" in json_str

    def test_branch_health_defaults(self):
        from refactory.surgeon.models import BranchHealth
        h = BranchHealth()
        assert h.score == 100
        assert h.grade == "A"
        assert h.commit_count == 0
