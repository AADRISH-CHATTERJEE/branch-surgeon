"""Tests for GET /branch-surgeon orchestration endpoint."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from refactory.api.app import app
from refactory.api.deps import get_container, resolve_repo_root
from refactory.core.logger import get_service_logger
from refactory.git.models import GitRepositoryInfo, WorkingTreeStatus
from refactory.recommendation.models import HealthReport, HealthScores
from refactory.surgeon.service import BranchSurgeonService


def _logger():
    return get_service_logger("test.branch_surgeon_api")


def _repo_info(branch: str = "feature/login", default: str = "master") -> GitRepositoryInfo:
    return GitRepositoryInfo(
        root_path="/tmp/demo",
        name="demo-repo",
        current_branch=branch,
        default_branch=default,
        head_sha="8ea41d5abcdef",
        working_tree=WorkingTreeStatus(),
    )


def _make_orchestrator(**overrides) -> BranchSurgeonService:
    git = MagicMock()
    git.get_repository_info.return_value = _repo_info()
    git.get_root_path.return_value = "/tmp/demo"
    git.get_commits_since_ref.return_value = [
        SimpleNamespace(sha="aaa", short_sha="aaa", message="one"),
        SimpleNamespace(sha="bbb", short_sha="bbb", message="two"),
        SimpleNamespace(sha="ccc", short_sha="ccc", message="three"),
    ]
    git.get_changed_files_vs_default_branch.return_value = [
        SimpleNamespace(path="auth.py"),
        SimpleNamespace(path="login.py"),
    ]
    commits = MagicMock()
    commits.get_commit_statistics.return_value = SimpleNamespace(
        insertions=30, deletions=6, files_changed=2
    )

    query = MagicMock()
    query.get_repository_by_root.return_value = {"id": "repo1", "name": "demo-repo"}
    query.get_recommendations.return_value = [
        {"id": "1", "priority": "critical", "title": "c1", "confidence": 0.9},
        {"id": "2", "priority": "critical", "title": "c2"},
    ]
    from refactory.recommendation.stats import RecommendationRepositorySummary

    stats = MagicMock()
    stats.get_repository_summary.return_value = RecommendationRepositorySummary(
        total=7,
        critical=2,
        high=4,
        medium=1,
        low=0,
        pending=7,
        repository_id="repo1",
        repository="demo-repo",
        source="RecommendationStatsService",
        version="1",
    )
    query.get_reviews.return_value = [
        {
            "id": "r1",
            "pr_number": 1,
            "risk": "high",
            "summary": "ok",
            "created_at": "2026-08-01T00:00:00",
            "suggestion_count": 3,
        }
    ]
    query.get_analyses.return_value = [
        {
            "id": "a1",
            "command": "review",
            "status": "success",
            "created_at": "2026-08-01T01:00:00",
            "summary": "done",
        }
    ]
    query.get_graph.return_value = {
        "node_count": 5,
        "edge_count": 3,
        "nodes": [
            {"id": "m1", "type": "module", "name": "auth"},
            {"id": "n1", "type": "file", "name": "auth.py"},
            {"id": "n2", "type": "file", "name": "login.py"},
            {"id": "m2", "type": "module", "name": "login"},
            {"id": "n3", "type": "file", "name": "service.py"},
        ],
        "edges": [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n3"},
            {"source": "m1", "target": "n1"},
        ],
    }

    engine = MagicMock()
    engine.calculate_health.return_value = HealthReport(
        scores=HealthScores(
            overall=86,
            architecture=100,
            security=100,
            testing=20,
            maintainability=80,
        )
    )

    rules = MagicMock()
    gate = MagicMock()
    gate.outcome.value = "pass"
    gate.blockers = []
    gate.warnings = []
    rules.check.return_value = gate

    kwargs = dict(
        logger=_logger(),
        git_service=git,
        commit_service=commits,
        indexer_service=MagicMock(),
        graph_service=MagicMock(),
        impact_analysis_service=MagicMock(),
        test_intelligence_service=MagicMock(),
        documentation_service=MagicMock(),
        query_service=query,
        recommendation_engine=engine,
        recommendation_stats_service=stats,
        company_rules_checker=rules,
    )
    kwargs.update(overrides)
    svc = BranchSurgeonService(**kwargs)
    return svc


class TestComposeWorkspace:
    def test_healthy_repository(self):
        svc = _make_orchestrator()
        ws = svc.compose_workspace()
        assert ws.branch.name == "feature/login"
        assert ws.branch.base_branch == "master"
        assert ws.branch.commits == 3
        assert ws.branch.changed_files == 2
        assert ws.branch.insertions == 90
        assert ws.branch.deletions == 18
        assert ws.health.overall == 86
        assert ws.recommendations.total == 7
        assert ws.recommendations.critical == 2
        assert ws.recommendations.high == 4
        assert ws.reviews.completed == 1
        assert ws.blast_radius.node_count == 5
        assert "auth.py" in ws.blast_radius.critical_files
        assert "auth" not in ws.blast_radius.critical_files
        assert "login" not in ws.blast_radius.critical_files
        assert ws.surgery.score >= 0
        assert ws.surgery.grade
        assert isinstance(ws.timeline, list)
        assert len(ws.timeline) >= 1
        # Review without confidence should still expose key as null (not 0).
        assert ws.reviews.latest is not None
        # Sample rec has confidence 0.9 used as fallback when review omits it.
        assert ws.reviews.latest.get("confidence") == 0.9

    def test_empty_repository(self):
        from refactory.recommendation.stats import RecommendationRepositorySummary

        git = MagicMock()
        git.get_repository_info.return_value = _repo_info()
        git.get_commits_since_ref.return_value = []
        git.get_changed_files_vs_default_branch.return_value = []
        query = MagicMock()
        query.get_repository_by_root.return_value = {"id": "repo1"}
        query.get_recommendations.return_value = []
        query.get_reviews.return_value = []
        query.get_analyses.return_value = []
        query.get_graph.return_value = {"nodes": [], "edges": [], "node_count": 0, "edge_count": 0}
        engine = MagicMock()
        engine.calculate_health.return_value = HealthReport(scores=HealthScores())
        rules = MagicMock()
        gate = MagicMock()
        gate.outcome.value = "pass"
        gate.blockers = []
        gate.warnings = []
        rules.check.return_value = gate
        stats = MagicMock()
        stats.get_repository_summary.return_value = RecommendationRepositorySummary(
            total=0, repository_id="repo1"
        )
        svc = _make_orchestrator(
            git_service=git,
            query_service=query,
            recommendation_engine=engine,
            recommendation_stats_service=stats,
            company_rules_checker=rules,
            commit_service=MagicMock(),
        )
        ws = svc.compose_workspace()
        assert ws.branch.commits == 0
        assert ws.branch.changed_files == 0
        assert ws.recommendations.total == 0
        assert ws.reviews.completed == 0
        assert ws.timeline == []
        assert ws.surgery.grade in {"Healthy", "Stable", "Caution", "At Risk", "Unknown"}

    def test_missing_graph(self):
        query = MagicMock()
        query.get_repository_by_root.return_value = {"id": "repo1"}
        query.count_recommendations.return_value = 0
        query.get_recommendations.return_value = []
        query.get_reviews.return_value = []
        query.get_analyses.return_value = []
        query.get_graph.side_effect = RuntimeError("no graph")
        svc = _make_orchestrator(query_service=query)
        ws = svc.compose_workspace()
        assert ws.blast_radius.node_count == 0
        assert ws.blast_radius.critical_files == []

    def test_no_reviews(self):
        from refactory.recommendation.stats import RecommendationRepositorySummary

        query = MagicMock()
        query.get_repository_by_root.return_value = {"id": "repo1"}
        query.get_recommendations.return_value = [{"id": "1", "priority": "low"}]
        query.get_reviews.return_value = []
        query.get_analyses.return_value = []
        query.get_graph.return_value = {"nodes": [], "edges": []}
        stats = MagicMock()
        stats.get_repository_summary.return_value = RecommendationRepositorySummary(
            total=1, low=1, pending=1, repository_id="repo1"
        )
        svc = _make_orchestrator(
            query_service=query, recommendation_stats_service=stats
        )
        ws = svc.compose_workspace()
        assert ws.reviews.completed == 0
        assert ws.reviews.latest is None
        assert ws.recommendations.total == 1

    def test_no_recommendations(self):
        from refactory.recommendation.stats import RecommendationRepositorySummary

        query = MagicMock()
        query.get_repository_by_root.return_value = {"id": "repo1"}
        query.get_recommendations.return_value = []
        query.get_reviews.return_value = []
        query.get_analyses.return_value = []
        query.get_graph.return_value = {"nodes": [], "edges": []}
        stats = MagicMock()
        stats.get_repository_summary.return_value = RecommendationRepositorySummary(
            total=0, repository_id="repo1"
        )
        svc = _make_orchestrator(
            query_service=query, recommendation_stats_service=stats
        )
        ws = svc.compose_workspace()
        assert ws.recommendations.total == 0
        assert ws.recommendations.critical == 0

    def test_normalize_file_labels_prefers_file_over_module(self):
        out = BranchSurgeonService._normalize_file_labels(
            ["auth", "auth.py", "login.py", "login"],
            prefer_types=["module", "file", "file", "module"],
        )
        assert out == ["auth.py", "login.py"]

    def test_confidence_not_fabricated_when_missing(self):
        query = MagicMock()
        query.get_repository_by_root.return_value = {"id": "repo1"}
        query.count_recommendations.return_value = 0
        query.get_recommendations.return_value = []
        query.get_reviews.return_value = [
            {
                "id": "r1",
                "pr_number": 1,
                "risk": "blocked",
                "summary": "blocked",
                "created_at": "2026-08-02T00:00:00",
                # no confidence key
            }
        ]
        query.get_analyses.return_value = []
        query.get_graph.return_value = {"nodes": [], "edges": []}
        svc = _make_orchestrator(query_service=query)
        ws = svc.compose_workspace()
        assert ws.reviews.latest is not None
        assert ws.reviews.latest.get("confidence") is None


@pytest.fixture
def api_client(tmp_path: Path):
    svc = _make_orchestrator()
    container = MagicMock()
    container.branch_surgeon_service = svc
    container.git_service.get_root_path.return_value = str(tmp_path)

    app.dependency_overrides[get_container] = lambda: container
    app.dependency_overrides[resolve_repo_root] = lambda: tmp_path.resolve()
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


class TestBranchSurgeonRoute:
    def test_get_branch_surgeon(self, api_client: TestClient):
        resp = api_client.get("/branch-surgeon")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        data = body["data"]
        assert data["branch"]["name"] == "feature/login"
        assert data["health"]["overall"] == 86
        assert "surgery" in data
        assert "blast_radius" in data
        assert "timeline" in data
        assert isinstance(data["timeline"], list)
        risk = data["merge_conflict_risk"]
        assert risk["level"] in {"low", "medium", "high"}
        assert 0.0 <= float(risk["score"]) <= 1.0
        assert isinstance(risk["reason"], str) and risk["reason"]
        assert "surgery_score" in data
        assert data["surgery_score"] == data["surgery"]["score"]
