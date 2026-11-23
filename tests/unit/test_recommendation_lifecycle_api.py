"""API tests for PATCH /recommendations/{id} lifecycle."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from refactory.api.app import create_app
from refactory.api.deps import clear_container_cache, get_container


@pytest.fixture()
def client(tmp_path: Path):
    container = MagicMock()
    container.git_service.get_root_path.return_value = str(tmp_path)
    container.query_service.get_repository_by_root.return_value = {
        "id": "repo-1",
        "name": "demo",
    }
    container.query_service.get_recommendation.return_value = {
        "id": "r1",
        "repository_id": "repo-1",
        "status": "pending",
        "title": "Fix me",
        "priority": "critical",
    }
    container.recommendation_stats_service.set_status.return_value = {
        "id": "r1",
        "repository_id": "repo-1",
        "status": "resolved",
        "resolved_at": "2026-08-04T00:00:00Z",
        "updated_by": "local",
        "reasoning": "because",
        "affected_files": ["a.py"],
        "effort": "S",
        "confidence": 0.9,
        "impact": ["Security"],
    }
    container.recommendation_stats_service.refresh.return_value = MagicMock(
        model_dump=lambda mode="json": {"critical": 0, "pending": 0, "resolved": 1},
        critical=0,
        pending=0,
        resolved=1,
    )
    container.branch_surgeon_service.compose_workspace.return_value = {}
    container.analysis_history_service = MagicMock()

    app = create_app()
    clear_container_cache()
    app.dependency_overrides[get_container] = lambda: container
    yield TestClient(app), container
    clear_container_cache()


def test_patch_resolve(client):
    http, container = client
    resp = http.patch("/recommendations/r1", json={"status": "resolved"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "resolved"
    assert body["message"] == "Recommendation Resolved"
    container.recommendation_stats_service.set_status.assert_called()
    container.recommendation_stats_service.refresh.assert_called()
    container.branch_surgeon_service.compose_workspace.assert_called()
    container.persistence_service.persist_analysis_run.assert_called()
    container.analysis_history_service.record.assert_called()


def test_patch_ignore(client):
    http, container = client
    container.recommendation_stats_service.set_status.return_value = {
        "id": "r1",
        "repository_id": "repo-1",
        "status": "ignored",
        "ignored_at": "2026-08-04T00:00:00Z",
    }
    resp = http.patch("/recommendations/r1", json={"status": "ignored"})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ignored"
    assert resp.json()["message"] == "Recommendation Ignored"


def test_openapi_exposes_patch(client):
    http, _ = client
    schema = http.app.openapi()
    path = "/recommendations/{recommendation_id}"
    assert path in schema["paths"]
    assert "patch" in schema["paths"][path]


def test_invalid_status(client):
    http, _ = client
    resp = http.patch("/recommendations/r1", json={"status": "nope"})
    assert resp.status_code == 422
