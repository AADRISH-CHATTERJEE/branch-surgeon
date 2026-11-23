"""Integration: PATCH suggestion status against real SQLite persistence."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from refactory.api.app import create_app
from refactory.api.deps import clear_container_cache, get_container
from refactory.db.base import Base
from refactory.db.persistence import PersistenceService
from refactory.db.query_service import RepositoryQueryService
from refactory.db.session import SessionFactory
from refactory.recommendation.stats import RecommendationStatsService
from refactory.review.suggestion_status import ReviewSuggestionStatusService


@pytest.fixture()
def integration_env(tmp_path: Path):
    root = str(tmp_path.resolve())
    eng = create_engine(f"sqlite:///{tmp_path / 'life.db'}", echo=False)
    Base.metadata.create_all(eng)
    factory = SessionFactory(eng)
    persistence = PersistenceService(factory, logger=MagicMock())
    query = RepositoryQueryService(factory)
    stats = RecommendationStatsService(
        MagicMock(), query, persistence_service=persistence
    )
    status_svc = ReviewSuggestionStatusService(
        MagicMock(),
        query_service=query,
        persistence_service=persistence,
        recommendation_stats_service=stats,
    )

    repo = persistence.get_or_create_repository(name="life", root_path=root)
    rid = repo["id"]
    persistence.persist_recommendations(
        rid,
        [
            {
                "id": "R-LIFE",
                "type": "security",
                "priority": "critical",
                "title": "Lifecycle sync finding",
                "status": "pending",
            }
        ],
    )
    review = persistence.persist_review(
        repository_id=rid,
        pr_number=7,
        summary="integration",
        suggestions=[
            {
                "file": "life.py",
                "line": 1,
                "severity": "critical",
                "category": "security",
                "title": "Lifecycle sync finding",
                "explanation": "demo",
            }
        ],
    )
    suggestion_id = query.get_review_suggestions(review["id"])[0]["id"]

    container = MagicMock()
    container.git_service.get_root_path.return_value = root
    container.git_service.get_current_branch.return_value = "main"
    container.git_service.get_current_commit.return_value = "abc123"
    container.git_service.get_repository_metadata.return_value = MagicMock(
        name="life",
        root_path=root,
        current_branch="main",
        default_branch="main",
        remote_url=None,
        head_sha="abc123",
    )
    container.query_service = query
    container.persistence_service = persistence
    container.review_suggestion_status_service = status_svc
    container.recommendation_stats_service = stats
    container.analysis_history_service = MagicMock()
    container.branch_surgeon_service.compose_workspace.return_value = MagicMock(
        recommendations=MagicMock(critical=0, pending=0)
    )

    app = create_app()
    clear_container_cache()
    app.dependency_overrides[get_container] = lambda: container
    client = TestClient(app)
    yield {
        "client": client,
        "review": review,
        "suggestion_id": suggestion_id,
        "rid": rid,
        "query": query,
        "stats": stats,
        "persistence": persistence,
        "root": root,
        "container": container,
    }
    clear_container_cache()
    eng.dispose()


class TestSuggestionLifecycleIntegration:
    def test_pending_to_resolved_syncs_everything(self, integration_env):
        env = integration_env
        client = env["client"]
        review = env["review"]
        suggestion_id = env["suggestion_id"]
        query = env["query"]
        stats = env["stats"]
        rid = env["rid"]
        root = env["root"]
        container = env["container"]

        resp = client.patch(
            f"/reviews/{review['id']}/suggestions/{suggestion_id}",
            json={"status": "resolved"},
            headers={"X-Repo-Root": root},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["data"]["status"] == "resolved"
        assert body["data"]["resolved_at"]
        assert body["data"]["created_at"]
        assert "R-LIFE" in body["meta"]["synced_recommendation_ids"]
        assert body["meta"]["summary"]["pending"] == 0
        assert body["meta"]["summary"]["resolved"] >= 1
        # Critical severity is pending-only — resolved critical no longer counts.
        assert body["meta"]["summary"]["critical"] == 0

        rec = query.get_recommendation("R-LIFE")
        assert rec is not None
        assert rec["status"] == "resolved"

        summary = stats.refresh(repo_root=root, repository_id=rid)
        assert summary.pending == 0
        assert summary.resolved >= 1
        assert summary.critical == 0

        container.branch_surgeon_service.compose_workspace.assert_called()
        container.analysis_history_service.record.assert_called()

        runs = query.get_analyses(rid, limit=50)
        assert any(
            r.get("result_type") == "review_suggestion"
            and isinstance(r.get("result_data"), dict)
            and r["result_data"].get("status") == "resolved"
            and r["result_data"].get("summary") == "Resolved review suggestion"
            and r.get("command") == "review-suggestion"
            for r in runs
        ), runs

    def test_pending_to_ignored_via_pr_number(self, integration_env):
        env = integration_env
        client = env["client"]
        suggestion_id = env["suggestion_id"]
        query = env["query"]
        persistence = env["persistence"]
        stats = env["stats"]
        rid = env["rid"]
        root = env["root"]

        persistence.update_review_suggestion_status(
            suggestion_id, "pending", updated_by="test"
        )
        persistence.update_recommendation_fields("R-LIFE", status="pending")
        stats.invalidate(repository_id=rid)

        resp = client.patch(
            f"/reviews/7/suggestions/{suggestion_id}",
            json={"status": "ignored"},
            headers={"X-Repo-Root": root},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["status"] == "ignored"
        assert query.get_recommendation("R-LIFE")["status"] == "ignored"
