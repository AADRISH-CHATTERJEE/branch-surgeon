"""Phase 11.3 — Analysis History persistence, metrics, export, retention."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine

from refactory.db.base import Base
from refactory.db.models import AnalysisHistoryModel, RepositoryModel
from refactory.db.session import SessionFactory
from refactory.history.service import AnalysisHistoryService
from refactory.history.types import resolve_analysis_type


@pytest.fixture()
def history_env(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'history.db'}")
    Base.metadata.create_all(engine)
    factory = SessionFactory(engine)
    session = factory()
    try:
        session.add(RepositoryModel(id="repo1", name="demo", root_path=str(tmp_path)))
        session.commit()
    finally:
        session.close()
    svc = AnalysisHistoryService(logger=MagicMock(), session_factory=factory)
    return {"factory": factory, "svc": svc}


def test_resolve_analysis_type_mapping():
    assert resolve_analysis_type(command="review") == "review"
    assert resolve_analysis_type(command="recommend") == "recommendation"
    assert resolve_analysis_type(command="rules-check") == "rules_evaluation"
    assert resolve_analysis_type(command="surgeon") == "branch_surgeon"
    assert resolve_analysis_type(command="patch-apply") == "patch_apply"
    assert resolve_analysis_type(result_type="graph") == "repository_graph"
    assert resolve_analysis_type(explicit="index") == "index"
    assert resolve_analysis_type(command="organization-created") == "organization_admin"
    assert resolve_analysis_type(command="member-invited") == "organization_admin"
    assert resolve_analysis_type(command="organization-rule-updated") == "organization_rule"


def test_record_list_get_metrics(history_env):
    svc: AnalysisHistoryService = history_env["svc"]
    row = svc.record(
        repository_id="repo1",
        analysis_type="review",
        repository_name="demo",
        branch="main",
        commit="abc123",
        status="completed",
        duration_ms=42.5,
        summary="Review complete",
        result_data={"risk_level": "low"},
    )
    assert row["id"]
    assert row["analysis_type"] == "review"

    listed = svc.list_history(repository_id="repo1")
    assert len(listed) == 1
    assert listed[0]["summary"] == "Review complete"

    got = svc.get(row["id"])
    assert got is not None
    assert got["commit"] == "abc123"

    metrics = svc.metrics(repository_id="repo1")
    assert metrics["total_analyses"] == 1
    assert metrics["today"] == 1
    assert metrics["failures"] == 0
    assert metrics["success_rate"] == 100.0
    assert metrics["average_duration_ms"] == 42.5


def test_search_and_filters(history_env):
    svc: AnalysisHistoryService = history_env["svc"]
    svc.record(
        repository_id="repo1",
        analysis_type="recommendation",
        branch="feature/a",
        status="completed",
        summary="Recs for auth",
    )
    svc.record(
        repository_id="repo1",
        analysis_type="index",
        branch="main",
        status="failed",
        summary="Index failed",
    )
    assert len(svc.list_history(repository_id="repo1", analysis_type="index")) == 1
    assert len(svc.list_history(repository_id="repo1", status="failed")) == 1
    assert len(svc.list_history(repository_id="repo1", branch="feature/a")) == 1
    assert len(svc.list_history(repository_id="repo1", search="auth")) == 1


def test_export_formats(history_env):
    svc: AnalysisHistoryService = history_env["svc"]
    svc.record(
        repository_id="repo1",
        analysis_type="transform",
        status="completed",
        summary="Transform done",
    )
    json_body, json_media = svc.export(format="json", repository_id="repo1")
    assert "Transform done" in json_body
    assert "json" in json_media

    md_body, md_media = svc.export(format="markdown", repository_id="repo1")
    assert "Transform" in md_body
    assert "markdown" in md_media

    csv_body, csv_media = svc.export(format="csv", repository_id="repo1")
    assert "analysis_type" in csv_body
    assert "csv" in csv_media


def test_retention_unlimited_and_purge(history_env):
    svc: AnalysisHistoryService = history_env["svc"]
    factory: SessionFactory = history_env["factory"]

    assert svc.apply_retention(days=None, repository_id="repo1")["deleted"] == 0
    assert svc.apply_retention(days=0, repository_id="repo1")["deleted"] == 0

    old_ts = datetime.now(timezone.utc) - timedelta(days=60)
    session = factory()
    try:
        session.add(
            AnalysisHistoryModel(
                id="old1",
                timestamp=old_ts,
                analysis_type="review",
                repository_id="repo1",
                repository_name="demo",
                status="completed",
                summary="old",
            )
        )
        session.add(
            AnalysisHistoryModel(
                id="new1",
                timestamp=datetime.now(timezone.utc),
                analysis_type="review",
                repository_id="repo1",
                repository_name="demo",
                status="completed",
                summary="new",
            )
        )
        session.commit()
    finally:
        session.close()

    result = svc.apply_retention(days=30, repository_id="repo1")
    assert result["deleted"] == 1
    remaining = svc.list_history(repository_id="repo1")
    assert len(remaining) == 1
    assert remaining[0]["summary"] == "new"


def test_record_from_analysis_run(history_env):
    svc: AnalysisHistoryService = history_env["svc"]
    mirrored = svc.record_from_analysis_run(
        {
            "id": "run-1",
            "repository_id": "repo1",
            "command": "recommend",
            "result_type": "recommendations",
            "status": "completed",
            "duration_ms": 10,
            "branch": "main",
            "git_commit": "deadbeef",
            "result_data": {"total_recommendations": 3},
        },
        repository_name="demo",
        summary="3 recommendations",
    )
    assert mirrored["analysis_type"] == "recommendation"
    assert mirrored["analysis_run_id"] == "run-1"
