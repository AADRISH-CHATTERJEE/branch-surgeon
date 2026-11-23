"""PostTransformationPipeline + recommendation reconciliation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine

from refactory.db.base import Base
from refactory.db.persistence import PersistenceService
from refactory.db.session import SessionFactory
from refactory.recommendation.models import RecommendationReport
from refactory.recommendation.post_transformation import PostTransformationPipeline


@pytest.fixture()
def persistence():
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    factory = SessionFactory(eng)
    svc = PersistenceService(factory, logger=MagicMock())
    yield svc
    eng.dispose()


class TestReconcileRecommendations:
    def test_resolve_missing_and_keep_active(self, persistence: PersistenceService):
        repo = persistence.get_or_create_repository(
            name="demo", root_path="/tmp/demo-reconcile"
        )
        rid = repo["id"]
        persistence.persist_recommendations(
            rid,
            [
                {
                    "id": "R-AAAA1111",
                    "type": "security",
                    "priority": "critical",
                    "title": "Fix XSS",
                    "status": "pending",
                },
                {
                    "id": "R-BBBB2222",
                    "type": "security",
                    "priority": "critical",
                    "title": "SQL injection",
                    "status": "pending",
                },
            ],
        )

        stats = persistence.reconcile_recommendations(
            rid,
            [
                {
                    "id": "R-AAAA1111",
                    "type": "security",
                    "priority": "critical",
                    "title": "Fix XSS",
                },
                {
                    "id": "R-CCCC3333",
                    "type": "testing",
                    "priority": "medium",
                    "title": "Add unit tests",
                },
            ],
        )
        assert stats["resolved"] == 1
        assert stats["created"] == 1
        assert stats["active"] == 2

        rows = {r["id"]: r for r in persistence.get_recommendations(rid, limit=100)}
        assert rows["R-AAAA1111"]["status"] == "pending"
        assert rows["R-BBBB2222"]["status"] == "resolved"
        assert rows["R-BBBB2222"]["resolved_at"] is not None
        assert rows["R-CCCC3333"]["status"] == "pending"

    def test_reopen_resolved_when_issue_returns(self, persistence: PersistenceService):
        repo = persistence.get_or_create_repository(
            name="demo2", root_path="/tmp/demo-reopen"
        )
        rid = repo["id"]
        persistence.persist_recommendations(
            rid,
            [
                {
                    "id": "R-DEAD0001",
                    "type": "security",
                    "priority": "critical",
                    "title": "Fix XSS",
                    "status": "resolved",
                },
            ],
        )
        # Force resolved_at via update
        persistence.update_recommendation_fields(
            "R-DEAD0001", status="resolved"
        )
        stats = persistence.reconcile_recommendations(
            rid,
            [
                {
                    "id": "R-DEAD0001",
                    "type": "security",
                    "priority": "critical",
                    "title": "Fix XSS",
                },
            ],
        )
        assert stats["reopened"] == 1
        row = persistence.get_recommendation("R-DEAD0001")
        assert row is not None
        assert row["status"] == "pending"
        assert row["resolved_at"] is None


class TestPendingPriorityAggregation:
    def test_critical_counts_all_statuses(self, persistence: PersistenceService):
        from refactory.db.query_service import RepositoryQueryService

        repo = persistence.get_or_create_repository(
            name="prio", root_path="/tmp/prio"
        )
        rid = repo["id"]
        persistence.persist_recommendations(
            rid,
            [
                {
                    "id": "R-C1",
                    "type": "security",
                    "priority": "critical",
                    "title": "A",
                    "status": "pending",
                },
                {
                    "id": "R-C2",
                    "type": "security",
                    "priority": "critical",
                    "title": "B",
                    "status": "pending",
                },
            ],
        )
        persistence.reconcile_recommendations(
            rid,
            [
                {
                    "id": "R-C1",
                    "type": "security",
                    "priority": "critical",
                    "title": "A",
                },
            ],
        )
        query = RepositoryQueryService(persistence._sf)
        agg = query.aggregate_recommendations(rid)
        # Priority tiles count all persisted rows by priority.
        assert agg["by_priority"].get("critical") == 2
        assert agg["by_status"].get("pending") == 1
        assert agg["by_status"].get("resolved") == 1


class TestPostTransformationPipeline:
    def test_runs_index_recommend_surgeon_activity(self, tmp_path: Path):
        events: list[str] = []

        def activity_writer(**kwargs):
            events.append(str(kwargs.get("summary") or ""))

        index = MagicMock()
        index.build_index.return_value = MagicMock()
        graph = MagicMock()
        engine = MagicMock()
        engine.generate_recommendations.return_value = RecommendationReport(
            total_recommendations=21,
            critical_count=21,
            reconcile_stats={"resolved": 1, "active": 21},
        )
        stats = MagicMock()
        summary = MagicMock()
        summary.model_dump.return_value = {
            "critical": 21,
            "pending": 355,
            "resolved": 1,
        }
        stats.get_repository_summary.return_value = summary
        surgeon = MagicMock()

        pipeline = PostTransformationPipeline(
            MagicMock(),
            indexer_service=index,
            graph_service=graph,
            recommendation_engine=engine,
            recommendation_stats_service=stats,
            branch_surgeon_service=surgeon,
            activity_writer=activity_writer,
        )
        result = pipeline.run(
            tmp_path,
            trigger="transform-apply",
            skip_activity_applied=False,
        )

        assert result.indexed is True
        assert result.graph_updated is True
        assert result.recommendations_active == 21
        assert result.branch_surgeon_refreshed is True
        engine.generate_recommendations.assert_called_once()
        call_kw = engine.generate_recommendations.call_args.kwargs
        assert call_kw.get("reconcile") is True
        surgeon.compose_workspace.assert_called_once()
        assert "Transformation Applied" in events
        assert "Repository Indexed" in events
        assert "Recommendations Generated" in events
        assert "Branch Surgeon Updated" in events
