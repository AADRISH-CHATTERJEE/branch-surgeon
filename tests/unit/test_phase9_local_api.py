"""Phase 9 — Local REST API tests (presentation layer only).

Mocks ServiceContainer so business engines are not re-tested here.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from refactory.api.app import create_app
from refactory.api.deps import clear_container_cache, get_container
from refactory.api.schemas import ApiResponse, ok
from refactory.company.models import GateOutcome, GateResult


@pytest.fixture()
def mock_container(tmp_path: Path):
    container = MagicMock()
    repo = MagicMock()
    repo.name = "demo"
    repo.root_path = str(tmp_path)
    repo.current_branch = "feature/x"
    repo.default_branch = "main"
    repo.remote_url = None
    repo.head_sha = "abc123"

    container.git_service.get_repository_metadata.return_value = repo
    # GET /repository uses the same snapshot as Branch Surgeon.
    container.git_service.get_repository_info.return_value = repo
    container.git_service.get_root_path.return_value = str(tmp_path)
    container.git_service.get_current_branch.return_value = "feature/x"
    container.git_service.get_default_branch.return_value = "main"
    container.git_service.get_current_commit.return_value = None
    container.git_service.get_commits_since_ref.return_value = []
    container.git_service.get_changed_files_vs_ref.return_value = []
    container.git_service.get_changed_files_vs_default_branch.return_value = []
    container.git_service.get_head_sha.return_value = "abc123"
    container.git_service.get_working_tree_status.return_value = MagicMock(
        staged_files=[],
        modified_files=[],
        deleted_files=[],
        renamed_files=[],
        untracked_files=[],
    )

    container.settings.ai.provider = "mock"
    container.settings.cache.enabled = True
    container.settings.backend.url = ""
    container.ai_gateway.model = "mock-model"
    container.indexer_service.assess_staleness.return_value = {
        "is_stale": False,
        "indexed_files": 1,
        "current_files": 1,
    }

    health = MagicMock()
    health.model_dump.return_value = {"scores": {"overall": 90}}
    # Pydantic-like: to_data uses model_dump if BaseModel — use a simple object
    from refactory.api.serialize import to_data

    # Make calculate_health return a plain dict-serialisable mock via model_dump
    class _Health:
        def model_dump(self, mode="json"):
            return {"scores": {"overall": 90.0}}

    container.recommendation_engine.calculate_health.return_value = _Health()

    gate = GateResult(outcome=GateOutcome.PASS)
    container.company_rules_checker.check.return_value = gate
    container.rule_engine.rules = []
    container.rule_engine.load_rules.return_value = 0

    review_result = MagicMock()
    review_result.model_dump.return_value = {
        "pull_request_number": 1,
        "risk_level": "low",
        "summary": "ok",
    }

    class _Review:
        def model_dump(self, mode="json"):
            return {
                "pull_request_number": 1,
                "risk_level": "low",
                "summary": "ok",
            }

    container.review_engine.review.return_value = _Review()

    class _RecReport:
        total_recommendations = 2

        def model_dump(self, mode="json"):
            return {"total_recommendations": 2, "recommendations": []}

    container.recommendation_engine.generate_recommendations.return_value = _RecReport()
    container.query_service.get_repository_by_root.return_value = {"id": "repo-1"}
    container.query_service.get_recommendations.return_value = [
        {"id": "r1", "title": "Fix X", "status": "pending"}
    ]
    container.query_service.get_recommendation.return_value = {
        "id": "r1",
        "repository_id": "repo-1",
        "title": "Fix X",
        "status": "pending",
    }

    class _PatchResult:
        id = "patch-1"
        recommendation_id = "r1"
        explanation = "demo"
        confidence = 0.7
        changed_files = ["a.py"]
        unified_diff = "--- a/a.py\n+++ b/a.py\n"
        patches = []
        prompt_version = "1.0.0"
        model = "mock"
        provider = "mock"
        apply_available = True

        def model_dump(self, mode="json"):
            return {
                "id": self.id,
                "recommendation_id": self.recommendation_id,
                "explanation": self.explanation,
                "confidence": self.confidence,
                "changed_files": self.changed_files,
                "unified_diff": self.unified_diff,
                "patches": self.patches,
                "prompt_version": self.prompt_version,
                "model": self.model,
                "provider": self.provider,
                "apply_available": True,
            }

    class _ApplyResult:
        status = "applied"
        applied = True
        patch_id = "patch-1"
        recommendation_id = "r1"
        changed_files = ["a.py"]
        repository_updated = True
        index_updated = True
        graph_updated = True
        message = "Applied patch to 1 file(s)."
        recommendation_status = "applied"
        git_commit = "abc123"
        applied_at = None
        applied_by = "local"
        validation = type(
            "V",
            (),
            {
                "ok": True,
                "checked_files": ["a.py"],
                "errors": [],
                "rolled_back": False,
            },
        )()

        def model_dump(self, mode="json"):
            return {
                "status": self.status,
                "applied": self.applied,
                "patch_id": self.patch_id,
                "recommendation_id": self.recommendation_id,
                "changed_files": self.changed_files,
                "validation": {
                    "ok": True,
                    "checked_files": ["a.py"],
                    "errors": [],
                    "rolled_back": False,
                },
                "repository_updated": self.repository_updated,
                "index_updated": self.index_updated,
                "graph_updated": self.graph_updated,
                "message": self.message,
                "details": {},
                "recommendation_status": self.recommendation_status,
                "git_commit": self.git_commit,
                "applied_by": self.applied_by,
            }

    container.recommendation_patch_service.generate_for_recommendation.return_value = (
        _PatchResult()
    )
    container.recommendation_service.list_patches.return_value = [
        _PatchResult().model_dump()
    ]
    container.recommendation_service.apply_patch_by_id.return_value = _ApplyResult()
    container.recommendation_service.apply_patch.return_value = _ApplyResult()
    container.recommendation_service.rollback_patch.return_value = _ApplyResult()
    container.organization_rule_service.list_rules.return_value = []
    container.organization_rule_service.export_rules.return_value = {
        "version": "1.0",
        "type": "refactory.organization_rules",
        "rules": [],
    }
    container.query_service.get_reviews.return_value = [
        {"id": "rev-1", "repository_id": "repo-1", "pr_number": 1, "risk": "low"}
    ]
    container.query_service.get_review.return_value = {
        "id": "rev-1",
        "repository_id": "repo-1",
        "pr_number": 1,
        "risk": "low",
        "summary": "ok",
    }
    container.query_service.get_review_suggestions.return_value = [
        {"id": "sug-1", "file": "a.py", "severity": "info", "message": "nit"}
    ]
    container.query_service.get_graph.return_value = {
        "repository_id": "repo-1",
        "nodes": [{"id": "n1", "name": "mod", "type": "module"}],
        "edges": [{"id": "e1", "source_node": "n1", "target_node": "n1", "relationship": "imports"}],
        "node_count": 1,
        "edge_count": 1,
    }
    container.query_service.get_graph_node.return_value = {
        "id": "n1",
        "name": "mod",
        "type": "module",
        "outgoing_edges": [],
        "incoming_edges": [],
    }
    container.query_service.get_files.return_value = [
        {"id": "f1", "path": "a.py", "language": "python"}
    ]
    container.query_service.get_file.return_value = {
        "id": "f1",
        "path": "a.py",
        "language": "python",
    }
    container.query_service.get_symbols.return_value = [
        {"id": "s1", "file_id": "f1", "name": "foo", "type": "function", "line": 1}
    ]
    container.query_service.get_imports.return_value = [
        {"id": "i1", "file_id": "f1", "module": "os", "symbol": None}
    ]
    container.query_service.get_analyses.return_value = [
        {"id": "run-1", "command": "review", "status": "completed"}
    ]

    class _Preview:
        def model_dump(self, mode="json"):
            return {"status": "preview", "target_file": "a.py"}

    class _Result:
        def __init__(self, status="applied"):
            self.status = status
            self.id = "hist-1"

        def model_dump(self, mode="json"):
            return {"status": self.status, "id": self.id}

    class _RollbackResult(_Result):
        def __init__(self):
            super().__init__(status="rolled_back")

    container.transformation_service.preview.return_value = _Preview()
    container.transformation_service.apply.return_value = _Result()
    container.transformation_service.rollback.return_value = _RollbackResult()
    container.post_transformation_pipeline.run.return_value = MagicMock(
        trigger="transform-apply",
        indexed=True,
        graph_updated=True,
        recommendations_active=0,
        reconcile={},
        summary=None,
        branch_surgeon_refreshed=True,
        duration_ms=1.0,
        errors=[],
    )

    index = MagicMock()
    index.files = []
    container.indexer_service.load_index.return_value = index
    container.indexer_service.build_index.return_value = MagicMock(
        summary=MagicMock(model_dump=lambda mode="json": {"total_indexed_files": 3}),
        statistics=MagicMock(model_dump=lambda mode="json": {"files_parsed": 1}),
    )
    # Fix nested MagicMock model_dump for to_data — use simple objects
    class _Sum:
        def model_dump(self, mode="json"):
            return {"total_indexed_files": 3}

    class _Stats:
        def model_dump(self, mode="json"):
            return {"files_parsed": 1}

    class _Index:
        summary = _Sum()
        statistics = _Stats()

    container.indexer_service.build_index.return_value = _Index()
    container.indexer_service.load_index.return_value = _Index()
    container.indexer_service.get_last_index.return_value = _Index()

    class _GStats:
        total_nodes = 10
        total_edges = 20

        def model_dump(self, mode="json"):
            return {"total_nodes": 10, "total_edges": 20}

    class _Graph:
        statistics = _GStats()

    container.graph_service.build_graph.return_value = _Graph()

    return container


@pytest.fixture()
def client(mock_container, tmp_path: Path):
    clear_container_cache()
    app = create_app()

    def _override_container():
        return mock_container

    app.dependency_overrides[get_container] = _override_container
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    clear_container_cache()


class TestHealthAndEnvelope:
    def test_health(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["data"]["service"] == "refactory-local-api"
        assert "errors" in body
        assert "meta" in body

    def test_ok_helper_shape(self):
        envelope = ok({"a": 1}, message="hi", meta={"x": 1})
        assert isinstance(envelope, ApiResponse)
        dumped = envelope.model_dump()
        assert dumped == {
            "status": "success",
            "message": "hi",
            "data": {"a": 1},
            "errors": [],
            "meta": {"x": 1},
        }


class TestRepositoryRoutes:
    def test_get_repository(self, client: TestClient):
        resp = client.get("/repository")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["name"] == "demo"
        assert data["head_sha"] == "abc123"

    def test_get_status(self, client: TestClient):
        resp = client.get("/repository/status")
        assert resp.status_code == 200
        assert resp.json()["data"]["ai_provider"] == "mock"

    def test_get_health(self, client: TestClient):
        resp = client.get("/repository/health")
        assert resp.status_code == 200
        assert resp.json()["data"]["scores"]["overall"] == 90.0


class TestRulesRoutes:
    def test_rules_check(self, client: TestClient, mock_container):
        resp = client.post("/rules/check", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["outcome"] == "pass"
        mock_container.company_rules_checker.check.assert_called_once()

    def test_list_rules(self, client: TestClient):
        resp = client.get("/rules")
        assert resp.status_code == 200
        assert "standards" in resp.json()["data"]


class TestReviewRoutes:
    def test_create_review(self, client: TestClient, mock_container):
        resp = client.post("/review", json={"pr_number": 1})
        assert resp.status_code == 200
        assert resp.json()["data"]["risk_level"] == "low"
        mock_container.review_engine.review.assert_called_once_with(1)

    def test_create_review_validation(self, client: TestClient):
        resp = client.post("/review", json={})
        assert resp.status_code == 422

    def test_list_reviews(self, client: TestClient):
        resp = client.get("/reviews")
        assert resp.status_code == 200
        assert resp.json()["data"][0]["id"] == "rev-1"

    def test_get_review(self, client: TestClient):
        resp = client.get("/review/rev-1")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["id"] == "rev-1"
        assert body["suggestions"][0]["id"] == "sug-1"

    def test_get_review_missing(self, client: TestClient, mock_container):
        mock_container.query_service.get_review.return_value = None
        mock_container.query_service.get_reviews.return_value = []
        resp = client.get("/review/missing")
        assert resp.status_code == 404
        assert resp.json()["status"] == "error"

    def test_patch_suggestion_status(self, client: TestClient, mock_container):
        mock_container.recommendation_stats_service.refresh.return_value = MagicMock(
            model_dump=lambda mode="json": {"critical": 0, "pending": 0},
            source="RecommendationStatsService",
            version="2",
            critical=0,
            pending=0,
            resolved=1,
            applied=0,
        )
        mock_container.review_suggestion_status_service.update_status.return_value = {
            "suggestion": {
                "id": "sug-1",
                "review_id": "rev-1",
                "status": "resolved",
                "file": "a.py",
                "category": "security",
                "title": "Find me",
                "resolved_at": "2026-08-04T00:00:00Z",
                "updated_at": "2026-08-04T00:00:00Z",
                "updated_by": "local",
            },
            "synced_recommendation_ids": ["R-1"],
            "review_id": "rev-1",
            "old_status": "pending",
            "new_status": "resolved",
            "updated_by": "local",
        }
        resp = client.patch(
            "/reviews/rev-1/suggestions/sug-1",
            json={"status": "resolved"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["status"] == "resolved"
        assert body["data"]["updated_by"] == "local"
        assert body["meta"]["synced_recommendation_ids"] == ["R-1"]
        assert body["message"] == "Resolved review suggestion"
        mock_container.review_suggestion_status_service.update_status.assert_called_once()
        mock_container.recommendation_stats_service.refresh.assert_called_once()
        mock_container.branch_surgeon_service.compose_workspace.assert_called_once()
        mock_container.persistence_service.persist_analysis_run.assert_called()

    def test_patch_suggestion_ignored(self, client: TestClient, mock_container):
        mock_container.review_suggestion_status_service.update_status.return_value = {
            "suggestion": {
                "id": "sug-1",
                "review_id": "rev-1",
                "status": "ignored",
                "ignored_at": "2026-08-04T00:00:00Z",
            },
            "synced_recommendation_ids": [],
            "review_id": "rev-1",
            "old_status": "pending",
            "new_status": "ignored",
        }
        mock_container.recommendation_stats_service.refresh.return_value = MagicMock(
            model_dump=lambda mode="json": {"ignored": 1, "pending": 0},
            critical=0,
            pending=0,
            ignored=1,
        )
        resp = client.patch(
            "/reviews/rev-1/suggestions/sug-1",
            json={"status": "ignored"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "ignored"
        assert resp.json()["message"] == "Ignored review suggestion"

    def test_openapi_exposes_suggestion_status_patch(self, client: TestClient):
        schema = client.app.openapi()
        path = "/reviews/{review_id}/suggestions/{suggestion_id}"
        assert path in schema["paths"]
        assert "patch" in schema["paths"][path]


class TestRecommendRoutes:
    def test_recommend(self, client: TestClient, mock_container):
        resp = client.post("/recommend", json={"top": 5})
        assert resp.status_code == 200
        assert resp.json()["data"]["total_recommendations"] == 2
        mock_container.recommendation_engine.generate_recommendations.assert_called_once()

    def test_list_recommendations(self, client: TestClient):
        resp = client.get("/recommendations")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 1

    def test_generate_recommendation_patch(self, client: TestClient, mock_container):
        resp = client.post("/recommendations/r1/patch")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["data"]["recommendation_id"] == "r1"
        assert body["data"]["unified_diff"]
        assert body["meta"]["apply_available"] is True
        mock_container.recommendation_patch_service.generate_for_recommendation.assert_called_once()

    def test_list_recommendation_patches(self, client: TestClient, mock_container):
        resp = client.get("/recommendations/r1/patches")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 1
        assert resp.json()["meta"]["apply_available"] is True
        mock_container.recommendation_service.list_patches.assert_called_once()

    def test_apply_stored_patch(self, client: TestClient, mock_container):
        resp = client.post("/patches/patch-1/apply")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["data"]["applied"] is True
        assert body["data"]["changed_files"] == ["a.py"]
        assert body["meta"]["index_updated"] is True
        mock_container.recommendation_service.apply_patch_by_id.assert_called_once()

    def test_apply_recommendation_route(self, client: TestClient, mock_container):
        resp = client.post("/recommendations/r1/apply", json={"patch_id": "patch-1"})
        assert resp.status_code == 200
        assert resp.json()["data"]["applied"] is True
        mock_container.recommendation_service.apply_patch.assert_called_once()

    def test_apply_stored_patch_conflict(self, client: TestClient, mock_container):
        from refactory.recommendation.patch_models import PatchConflictError

        mock_container.recommendation_service.apply_patch_by_id.side_effect = (
            PatchConflictError("stale", files=["a.py"])
        )
        resp = client.post("/patches/patch-1/apply")
        assert resp.status_code == 409
        body = resp.json()
        assert body["status"] == "error"
        assert body["meta"]["files"] == ["a.py"]


class TestTransformRoutes:
    def test_preview(self, client: TestClient, mock_container):
        resp = client.post(
            "/transform",
            json={"target_file": "a.py", "transformation_type": "rename_symbol"},
        )
        assert resp.status_code == 200
        mock_container.transformation_service.preview.assert_called_once()

    def test_apply(self, client: TestClient, mock_container):
        resp = client.post(
            "/transform/apply",
            json={"target_file": "a.py", "transformation_type": "rename_symbol"},
        )
        assert resp.status_code == 200
        mock_container.transformation_service.apply.assert_called_once()

    def test_rollback(self, client: TestClient, mock_container):
        resp = client.post("/transform/rollback")
        assert resp.status_code == 200
        mock_container.transformation_service.rollback.assert_called_once()


class TestGraphAndIndexRoutes:
    def test_build_graph(self, client: TestClient, mock_container):
        resp = client.post("/graph", json={"force": True})
        assert resp.status_code == 200
        assert resp.json()["data"]["nodes"] == 10
        mock_container.graph_service.build_graph.assert_called()

    def test_get_graph(self, client: TestClient):
        resp = client.get("/graph")
        assert resp.status_code == 200

    def test_get_graph_full(self, client: TestClient):
        resp = client.get("/graph/full")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["node_count"] == 1
        assert data["nodes"][0]["id"] == "n1"

    def test_get_graph_node(self, client: TestClient):
        resp = client.get("/graph/nodes/n1")
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == "n1"

    def test_build_index(self, client: TestClient, mock_container):
        resp = client.post("/index", json={"force": False})
        assert resp.status_code == 200
        mock_container.indexer_service.build_index.assert_called_once()

    def test_index_status(self, client: TestClient):
        resp = client.get("/index/status")
        assert resp.status_code == 200
        assert "staleness" in resp.json()["data"]


class TestExplorerActivityDocsAndCors:
    def test_repository_files(self, client: TestClient):
        resp = client.get("/repository/files")
        assert resp.status_code == 200
        assert resp.json()["data"][0]["path"] == "a.py"

    def test_repository_symbols(self, client: TestClient):
        resp = client.get("/repository/symbols", params={"path": "a.py"})
        assert resp.status_code == 200
        assert resp.json()["data"][0]["name"] == "foo"

    def test_repository_imports(self, client: TestClient):
        resp = client.get("/repository/imports", params={"file_id": "f1"})
        assert resp.status_code == 200
        assert resp.json()["data"][0]["module"] == "os"

    def test_activity(self, client: TestClient):
        resp = client.get("/activity")
        assert resp.status_code == 200
        assert resp.json()["data"][0]["command"] == "review"

    def test_documentation(self, client: TestClient, monkeypatch):
        from refactory.company.models import CompanyDocumentation

        monkeypatch.setattr(
            "refactory.api.routes.documentation.load_company_documentation",
            lambda root: CompanyDocumentation(architecture="# Arch"),
        )
        resp = client.get("/documentation")
        assert resp.status_code == 200
        assert resp.json()["data"]["architecture"] == "# Arch"

    def test_cors_preflight(self, client: TestClient):
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


class TestOpenAPI:
    def test_openapi_lists_engine_paths(self, client: TestClient):
        spec = client.get("/openapi.json").json()
        paths = spec["paths"]
        for path in (
            "/repository",
            "/repository/health",
            "/repository/files",
            "/repository/file",
            "/repository/symbols",
            "/repository/imports",
            "/branch-surgeon",
            "/rules/check",
            "/review",
            "/reviews",
            "/recommend",
            "/recommendations",
            "/recommendations/{recommendation_id}/patch",
            "/recommendations/{recommendation_id}/patches",
            "/transform",
            "/transform/apply",
            "/transform/rollback",
            "/graph",
            "/graph/full",
            "/graph/nodes/{node_id}",
            "/index",
            "/index/status",
            "/activity",
            "/documentation",
            "/health",
        ):
            assert path in paths, f"missing {path}"
