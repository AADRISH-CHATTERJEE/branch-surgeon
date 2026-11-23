"""Single source of truth for recommendation counts — Branch Surgeon + Recommendations."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from refactory.recommendation.stats import (
    RecommendationRepositorySummary,
    RecommendationStatsService,
)
from refactory.surgeon.models import SurgeonRecommendationCounts
from refactory.surgeon.service import BranchSurgeonService


def _logger():
    from loguru import logger

    return logger


def _stats_service(query: MagicMock | None = None) -> RecommendationStatsService:
    q = query or MagicMock()
    return RecommendationStatsService(_logger(), q, persistence_service=MagicMock())


class TestRecommendationStatsService:
    def test_empty_repository_returns_zeros(self, tmp_path: Path):
        query = MagicMock()
        query.get_repository_by_root.return_value = None
        query.get_repository.return_value = None
        svc = _stats_service(query)
        summary = svc.get_repository_summary(repo_root=tmp_path)
        assert summary.total == 0
        assert summary.critical == 0
        assert summary.pending == 0
        assert summary.source == "RecommendationStatsService"
        assert summary.version == "2"

    def test_aggregate_buckets(self, tmp_path: Path):
        query = MagicMock()
        query.get_repository_by_root.return_value = {
            "id": "r1",
            "name": "demo-repo",
        }
        query.aggregate_recommendations.return_value = {
            "total": 10,
            # by_priority is pending-only from the repository layer
            "by_priority": {"critical": 2, "high": 3, "medium": 0, "low": 0},
            "by_priority_all": {"critical": 2, "high": 3, "medium": 4, "low": 1},
            "by_status": {
                "pending": 5,
                "resolved": 2,
                "applied": 1,
                "ignored": 1,
                "rejected": 1,
            },
            "by_type": {"security": 4, "architecture": 6},
            "last_updated": None,
        }
        svc = _stats_service(query)
        summary = svc.get_repository_summary(repo_root=tmp_path, branch="main")
        assert summary.total == 10
        assert summary.critical == 2
        assert summary.high == 3
        assert summary.medium == 0
        assert summary.low == 0
        assert summary.pending == 5
        assert summary.applied == 1
        assert summary.resolved == 2  # applied is separate from resolved
        assert summary.ignored == 2  # ignored + rejected
        assert summary.by_type["security"] == 4
        assert summary.repository == "demo-repo"
        assert summary.branch == "main"
        assert summary.version == "2"

    def test_cache_invalidation(self, tmp_path: Path):
        query = MagicMock()
        query.get_repository_by_root.return_value = {"id": "r1", "name": "demo"}
        query.aggregate_recommendations.return_value = {
            "total": 1,
            "by_priority": {"critical": 1},
            "by_status": {"pending": 1},
            "by_type": {},
            "last_updated": None,
        }
        svc = _stats_service(query)
        first = svc.get_repository_summary(repo_root=tmp_path)
        assert first.total == 1
        assert query.aggregate_recommendations.call_count == 1
        svc.get_repository_summary(repo_root=tmp_path)
        assert query.aggregate_recommendations.call_count == 1  # cached
        svc.invalidate(repository_id="r1")
        query.aggregate_recommendations.return_value = {
            "total": 2,
            "by_priority": {"critical": 1, "medium": 1},
            "by_status": {"pending": 1, "resolved": 1},
            "by_type": {},
            "last_updated": None,
        }
        second = svc.get_repository_summary(repo_root=tmp_path)
        assert second.total == 2
        assert query.aggregate_recommendations.call_count == 2


class TestIdenticalOutputs:
    """Branch Surgeon and Recommendations page consume the same summary object."""

    def test_branch_surgeon_matches_stats_service(self, tmp_path: Path):
        from refactory.git.models import GitRepositoryInfo, WorkingTreeStatus

        summary = RecommendationRepositorySummary(
            total=12,
            critical=3,
            high=4,
            medium=3,
            low=2,
            pending=8,
            resolved=3,
            ignored=1,
            repository_id="r1",
            repository="demo-repo",
            repo_root=str(tmp_path),
            branch="feature/x",
        )
        stats = MagicMock()
        stats.get_repository_summary.return_value = summary

        git = MagicMock()
        git.get_repository_info.return_value = GitRepositoryInfo(
            root_path=str(tmp_path),
            name="demo-repo",
            current_branch="feature/x",
            default_branch="main",
            head_sha="abc",
            working_tree=WorkingTreeStatus(),
        )
        git.get_root_path.return_value = str(tmp_path)
        git.get_commits_since_ref.return_value = []
        git.get_changed_files_vs_default_branch.return_value = []

        query = MagicMock()
        query.get_repository_by_root.return_value = {"id": "r1", "name": "demo-repo"}
        query.get_recommendations.return_value = []
        query.get_reviews.return_value = []
        query.get_analyses.return_value = []
        query.get_graph.return_value = {
            "nodes": [],
            "edges": [],
            "node_count": 0,
            "edge_count": 0,
        }

        engine = MagicMock()
        from refactory.recommendation.models import HealthReport, HealthScores

        engine.calculate_health.return_value = HealthReport(scores=HealthScores())

        surgeon = BranchSurgeonService(
            logger=_logger(),
            git_service=git,
            commit_service=MagicMock(),
            indexer_service=MagicMock(),
            graph_service=MagicMock(),
            impact_analysis_service=MagicMock(),
            test_intelligence_service=MagicMock(),
            documentation_service=MagicMock(),
            query_service=query,
            recommendation_engine=engine,
            recommendation_stats_service=stats,
            company_rules_checker=MagicMock(),
        )
        ws = surgeon.compose_workspace()
        page_summary = stats.get_repository_summary(
            repo_root=tmp_path, repository_id="r1"
        )
        assert ws.recommendations.total == page_summary.total == 12
        assert ws.recommendations.critical == page_summary.critical == 3
        assert ws.recommendations.pending == page_summary.pending == 8
        assert ws.recommendations.source == "RecommendationStatsService"
        assert ws.recommendations.version == page_summary.version

    def test_resolve_decreases_pending(self, tmp_path: Path):
        persistence = MagicMock()
        persistence.update_recommendation_status.return_value = {
            "id": "rec1",
            "repository_id": "r1",
            "status": "resolved",
        }
        query = MagicMock()
        query.get_repository_by_root.return_value = {"id": "r1", "name": "demo"}
        query.aggregate_recommendations.side_effect = [
            {
                "total": 2,
                "by_priority": {"medium": 2},
                "by_status": {"pending": 2},
                "by_type": {},
                "last_updated": None,
            },
            {
                "total": 2,
                "by_priority": {"medium": 2},
                "by_status": {"pending": 1, "resolved": 1},
                "by_type": {},
                "last_updated": None,
            },
        ]
        svc = RecommendationStatsService(
            _logger(), query, persistence_service=persistence
        )
        before = svc.get_repository_summary(repo_root=tmp_path)
        assert before.pending == 2
        svc.set_status("rec1", "resolved")
        after = svc.get_repository_summary(repo_root=tmp_path, force_refresh=True)
        assert after.pending == 1
        assert after.resolved == 1

    def test_ignore_increases_ignored(self, tmp_path: Path):
        persistence = MagicMock()
        persistence.update_recommendation_status.return_value = {
            "id": "rec1",
            "repository_id": "r1",
            "status": "ignored",
        }
        query = MagicMock()
        query.get_repository_by_root.return_value = {"id": "r1", "name": "demo"}
        query.aggregate_recommendations.side_effect = [
            {
                "total": 1,
                "by_priority": {"low": 1},
                "by_status": {"pending": 1},
                "by_type": {},
                "last_updated": None,
            },
            {
                "total": 1,
                "by_priority": {"low": 1},
                "by_status": {"ignored": 1},
                "by_type": {},
                "last_updated": None,
            },
        ]
        svc = RecommendationStatsService(
            _logger(), query, persistence_service=persistence
        )
        before = svc.get_repository_summary(repo_root=tmp_path)
        assert before.ignored == 0
        svc.set_status("rec1", "ignored")
        after = svc.get_repository_summary(repo_root=tmp_path, force_refresh=True)
        assert after.ignored == 1
        assert after.pending == 0

    def test_delete_decreases_total(self, tmp_path: Path):
        persistence = MagicMock()
        persistence.delete_recommendation.return_value = True
        query = MagicMock()
        query.get_recommendation.return_value = {"id": "rec1", "repository_id": "r1"}
        query.get_repository_by_root.return_value = {"id": "r1", "name": "demo"}
        query.aggregate_recommendations.side_effect = [
            {
                "total": 3,
                "by_priority": {"medium": 3},
                "by_status": {"pending": 3},
                "by_type": {},
                "last_updated": None,
            },
            {
                "total": 2,
                "by_priority": {"medium": 2},
                "by_status": {"pending": 2},
                "by_type": {},
                "last_updated": None,
            },
        ]
        svc = RecommendationStatsService(
            _logger(), query, persistence_service=persistence
        )
        before = svc.get_repository_summary(repo_root=tmp_path)
        assert before.total == 3
        assert svc.delete_recommendation("rec1") is True
        after = svc.get_repository_summary(repo_root=tmp_path, force_refresh=True)
        assert after.total == 2

    def test_severity_update_moves_buckets(self, tmp_path: Path):
        persistence = MagicMock()
        persistence.update_recommendation_fields.return_value = {
            "id": "rec1",
            "repository_id": "r1",
            "priority": "medium",
        }
        query = MagicMock()
        query.get_repository_by_root.return_value = {"id": "r1", "name": "demo"}
        query.aggregate_recommendations.side_effect = [
            {
                "total": 2,
                "by_priority": {"critical": 1, "medium": 1},
                "by_status": {"pending": 2},
                "by_type": {},
                "last_updated": None,
            },
            {
                "total": 2,
                "by_priority": {"medium": 2},
                "by_status": {"pending": 2},
                "by_type": {},
                "last_updated": None,
            },
        ]
        svc = RecommendationStatsService(
            _logger(), query, persistence_service=persistence
        )
        before = svc.get_repository_summary(repo_root=tmp_path)
        assert before.critical == 1
        assert before.medium == 1
        svc.set_priority("rec1", "medium")
        after = svc.get_repository_summary(repo_root=tmp_path, force_refresh=True)
        assert after.critical == 0
        assert after.medium == 2

    def test_repository_switch_changes_counts(self, tmp_path: Path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        query = MagicMock()

        def _by_root(root: str):
            if str(a.resolve()) in root or root.endswith("a"):
                return {"id": "ra", "name": "repo-a"}
            return {"id": "rb", "name": "repo-b"}

        query.get_repository_by_root.side_effect = _by_root

        def _agg(rid: str):
            if rid == "ra":
                return {
                    "total": 5,
                    "by_priority": {"critical": 5},
                    "by_status": {"pending": 5},
                    "by_type": {},
                    "last_updated": None,
                }
            return {
                "total": 1,
                "by_priority": {"low": 1},
                "by_status": {"pending": 1},
                "by_type": {},
                "last_updated": None,
            }

        query.aggregate_recommendations.side_effect = _agg
        svc = _stats_service(query)
        sa = svc.get_repository_summary(repo_root=a)
        sb = svc.get_repository_summary(repo_root=b)
        assert sa.total == 5 and sa.critical == 5
        assert sb.total == 1 and sb.low == 1
        assert sa.repository_id != sb.repository_id

    def test_surgeon_counts_model_from_summary(self):
        summary = RecommendationRepositorySummary(
            total=4, critical=1, high=1, medium=1, low=1, pending=4
        )
        counts = SurgeonRecommendationCounts(
            total=summary.total,
            critical=summary.critical,
            high=summary.high,
            medium=summary.medium,
            low=summary.low,
            pending=summary.pending,
            source=summary.source,
            version=summary.version,
        )
        assert counts.total == 4
        assert counts.source == "RecommendationStatsService"

    def test_branch_surgeon_compose_force_refreshes(self, tmp_path: Path):
        """GET /branch-surgeon path must request force_refresh=True."""
        from refactory.git.models import GitRepositoryInfo, WorkingTreeStatus
        from refactory.recommendation.models import HealthReport, HealthScores

        summary = RecommendationRepositorySummary(
            total=9,
            critical=2,
            high=1,
            pending=9,
            repository_id="r1",
            repository="demo-repo",
        )
        stats = MagicMock()
        stats.get_repository_summary.return_value = summary

        git = MagicMock()
        git.get_repository_info.return_value = GitRepositoryInfo(
            root_path=str(tmp_path),
            name="demo-repo",
            current_branch="main",
            default_branch="main",
            head_sha="abc",
            working_tree=WorkingTreeStatus(),
        )
        git.get_root_path.return_value = str(tmp_path)
        git.get_commits_since_ref.return_value = []
        git.get_changed_files_vs_default_branch.return_value = []

        query = MagicMock()
        query.get_recommendations.return_value = []
        query.get_reviews.return_value = []
        query.get_analyses.return_value = []
        query.get_graph.return_value = {
            "nodes": [],
            "edges": [],
            "node_count": 0,
            "edge_count": 0,
        }
        engine = MagicMock()
        engine.calculate_health.return_value = HealthReport(scores=HealthScores())

        surgeon = BranchSurgeonService(
            logger=_logger(),
            git_service=git,
            commit_service=MagicMock(),
            indexer_service=MagicMock(),
            graph_service=MagicMock(),
            impact_analysis_service=MagicMock(),
            test_intelligence_service=MagicMock(),
            documentation_service=MagicMock(),
            query_service=query,
            recommendation_engine=engine,
            recommendation_stats_service=stats,
            company_rules_checker=MagicMock(),
        )
        ws = surgeon.compose_workspace()
        assert ws.recommendations.total == 9
        assert ws.recommendations.critical == 2
        # First call must be a live refresh.
        first = stats.get_repository_summary.call_args_list[0]
        assert first.kwargs.get("force_refresh") is True
