"""Phase 7c — Migration tests for TransformationService read path.

Verifies that TransformationService produces identical results when reading
analysis history from RepositoryQueryService versus StorageService.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from refactory.db.base import Base
from refactory.db.models import RepositoryModel
from refactory.db.persistence import PersistenceService
from refactory.db.query_service import RepositoryQueryService
from refactory.transformation.models import (
    TransformationRequest,
    TransformationStatus,
    TransformationType,
    ValidationStatus,
)
from refactory.transformation.service import TransformationService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_services(storage_mock=None):
    """Create standard mock services for TransformationService."""
    storage = storage_mock or MagicMock()
    if not storage_mock:
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
    parser = MagicMock()
    parser.parse_file.return_value = None
    ai = MagicMock()
    resp = MagicMock()
    resp.content = "new code"
    ai.generate.return_value = resp
    return {
        "parser_service": parser,
        "indexer_service": MagicMock(),
        "graph_service": MagicMock(),
        "rule_engine": MagicMock(),
        "policy_service": MagicMock(),
        "storage_service": storage,
        "ai_gateway": ai,
        "prompt_service": MagicMock(),
    }


@pytest.fixture()
def engine():
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def repo_id(session_factory) -> str:
    """Create a repository and return its ID."""
    sess = session_factory()
    repo = RepositoryModel(
        id=uuid.uuid4().hex[:36],
        name="test-repo",
        root_path=str(Path("/tmp/test-repo")),
        default_branch="main",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    sess.add(repo)
    sess.commit()
    rid = repo.id
    sess.close()
    return rid


@pytest.fixture()
def global_repo_id(session_factory) -> str:
    """Create a 'global' repository with empty root_path (matches _load_history's query)."""
    sess = session_factory()
    repo = RepositoryModel(
        id=uuid.uuid4().hex[:36],
        name="global",
        root_path="",
        default_branch="main",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    sess.add(repo)
    sess.commit()
    rid = repo.id
    sess.close()
    return rid


@pytest.fixture()
def persistence(session_factory) -> PersistenceService:
    return PersistenceService(session_factory)


@pytest.fixture()
def query_service(session_factory) -> RepositoryQueryService:
    return RepositoryQueryService(session_factory)


def _service_with_query(query_service, storage_mock=None):
    """Create TransformationService wired to query_service."""
    from loguru import logger
    mocks = _mock_services(storage_mock)
    return TransformationService(logger=logger, **mocks, query_service=query_service)


def _service_with_storage(storage_mock):
    """Create TransformationService without query_service (legacy)."""
    from loguru import logger
    mocks = _mock_services(storage_mock)
    return TransformationService(logger=logger, **mocks)


def _service_without_query():
    """Create service with default empty mocks, no query_service."""
    from loguru import logger
    mocks = _mock_services()
    return TransformationService(logger=logger, **mocks)


def _applied_entry(
    *,
    history_id: str = "hist-1",
    plan_id: str = "plan-1",
    patch_id: str = "patch-1",
    transformation_type: str = "rename_function",
    files_modified: list[str] | None = None,
    patch_content: str = "diff --git a/x.py",
    rollback_patch: str = "diff --git a/x.py (rollback)",
    validation_status: str = "passed",
    steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a result_data dict matching what _persist_result produces."""
    return {
        "history_id": history_id,
        "plan_id": plan_id,
        "patch_id": patch_id,
        "status": "applied",
        "transformation_type": transformation_type,
        "files_modified": files_modified or ["src/service.py"],
        "patch_content": patch_content,
        "rollback_patch": rollback_patch,
        "validation_status": validation_status,
        "steps": steps or [],
    }


# ===========================================================================
# Backward Compatibility Tests
# ===========================================================================


class TestBackwardCompatibility:
    """Verify TransformationService works identically without query_service."""

    def test_no_query_service_uses_storage(self):
        storage = MagicMock()
        storage.get_analyses.return_value = [
            {"result_data": _applied_entry(), "command": "apply"}
        ]
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_storage(storage)
        assert len(svc._history) == 1
        assert storage.get_analyses.called

    def test_no_query_service_empty_history(self):
        svc = _service_without_query()
        assert svc._history == []

    def test_constructor_without_query_service(self):
        from loguru import logger
        mocks = _mock_services()
        svc = TransformationService(logger=logger, **mocks)
        assert svc._query is None

    def test_constructor_with_query_service(self, query_service):
        from loguru import logger
        mocks = _mock_services()
        svc = TransformationService(logger=logger, **mocks, query_service=query_service)
        assert svc._query is query_service


# ===========================================================================
# QueryService Read Path Tests
# ===========================================================================


class TestQueryServiceReadPath:
    """Test the _read_analyses helper directly."""

    def test_read_analyses_from_query_service(self, persistence, query_service, repo_id):
        persistence.persist_analysis_run(
            repository_id=repo_id,
            command="apply",
            result_type="transformation_applied",
            result_data=_applied_entry(),
        )
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_query(query_service, storage)
        data = svc._read_analyses(str(Path("/tmp/test-repo")), command="apply", limit=50)
        assert len(data) == 1
        assert data[0]["command"] == "apply"
        assert data[0]["result_data"] == _applied_entry()
        assert not storage.get_analyses.called

    def test_read_analyses_preserves_structure(self, persistence, query_service, repo_id):
        entry = _applied_entry(history_id="h-99", plan_id="p-99")
        persistence.persist_analysis_run(
            repository_id=repo_id,
            command="apply",
            result_type="transformation_applied",
            result_data=entry,
            git_commit="a" * 40,
            branch="main",
            duration_ms=1234.5,
        )
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_query(query_service, storage)
        data = svc._read_analyses(str(Path("/tmp/test-repo")), command="apply")
        record = data[0]
        assert "id" in record
        assert "command" in record
        assert "status" in record
        assert "git_commit" in record
        assert "branch" in record
        assert "timestamp" in record
        assert "duration_ms" in record
        assert "result_type" in record
        assert "result_data" in record
        assert record["git_commit"] == "a" * 40
        assert record["branch"] == "main"
        assert record["duration_ms"] == 1234.5

    def test_read_analyses_no_extra_keys(self, persistence, query_service, repo_id):
        persistence.persist_analysis_run(
            repository_id=repo_id,
            command="apply",
            result_type="transformation_applied",
            result_data=_applied_entry(),
        )
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_query(query_service, storage)
        data = svc._read_analyses(str(Path("/tmp/test-repo")), command="apply")
        expected_keys = {"id", "command", "status", "git_commit", "branch",
                         "timestamp", "duration_ms", "result_type", "result_data"}
        assert set(data[0].keys()) == expected_keys

    def test_read_analyses_empty_repo(self, query_service):
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_query(query_service, storage)
        data = svc._read_analyses(str(Path("/nonexistent/repo")), command="apply")
        assert data == []

    def test_read_analyses_fallback_on_failure(self):
        bad_query = MagicMock()
        bad_query.get_repository_by_root.side_effect = RuntimeError("db error")
        storage = MagicMock()
        storage.get_analyses.return_value = [{"result_data": {}, "command": "apply"}]
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_query(bad_query, storage)
        data = svc._read_analyses("/tmp/test-repo", command="apply")
        assert len(data) == 1
        assert storage.get_analyses.called

    def test_read_analyses_command_filter(self, persistence, query_service, repo_id):
        persistence.persist_analysis_run(
            repository_id=repo_id,
            command="apply",
            result_type="transformation_applied",
            result_data=_applied_entry(),
        )
        persistence.persist_analysis_run(
            repository_id=repo_id,
            command="transform",
            result_type="transformation_plan",
            result_data={"plan_id": "p-1"},
        )
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_query(query_service, storage)
        apply_data = svc._read_analyses(str(Path("/tmp/test-repo")), command="apply")
        transform_data = svc._read_analyses(str(Path("/tmp/test-repo")), command="transform")
        assert len(apply_data) == 1
        assert len(transform_data) == 1
        assert apply_data[0]["command"] == "apply"
        assert transform_data[0]["command"] == "transform"


# ===========================================================================
# History Loading Tests
# ===========================================================================


class TestHistoryLoading:
    """Test that _load_history works correctly via QueryService."""

    def test_load_history_from_query_service(self, persistence, query_service, global_repo_id):
        persistence.persist_analysis_run(
            repository_id=global_repo_id,
            command="apply",
            result_type="transformation_applied",
            result_data=_applied_entry(
                history_id="h-1",
                transformation_type="rename_function",
                files_modified=["src/app.py"],
            ),
        )
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_query(query_service, storage)
        assert len(svc._history) == 1
        assert svc._history[0].id == "h-1"
        assert svc._history[0].files_modified == ["src/app.py"]
        assert svc._history[0].status == TransformationStatus.APPLIED

    def test_load_history_multiple_entries(self, persistence, query_service, global_repo_id):
        for i in range(3):
            persistence.persist_analysis_run(
                repository_id=global_repo_id,
                command="apply",
                result_type="transformation_applied",
                result_data=_applied_entry(history_id=f"h-{i}"),
            )
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_query(query_service, storage)
        assert len(svc._history) == 3

    def test_load_history_skips_non_applied(self, persistence, query_service, global_repo_id):
        entry = _applied_entry()
        entry["status"] = "rejected"
        persistence.persist_analysis_run(
            repository_id=global_repo_id,
            command="apply",
            result_type="transformation_applied",
            result_data=entry,
        )
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_query(query_service, storage)
        assert len(svc._history) == 0

    def test_load_history_preserves_transformation_type(self, persistence, query_service, global_repo_id):
        persistence.persist_analysis_run(
            repository_id=global_repo_id,
            command="apply",
            result_type="transformation_applied",
            result_data=_applied_entry(transformation_type="extract_method"),
        )
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_query(query_service, storage)
        assert svc._history[0].transformation_type == TransformationType.EXTRACT_METHOD

    def test_load_history_preserves_rollback_patch(self, persistence, query_service, global_repo_id):
        persistence.persist_analysis_run(
            repository_id=global_repo_id,
            command="apply",
            result_type="transformation_applied",
            result_data=_applied_entry(rollback_patch="--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@"),
        )
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_query(query_service, storage)
        assert "--- a/x.py" in svc._history[0].rollback_patch


# ===========================================================================
# Rollback History Tests
# ===========================================================================


class TestRollbackHistory:
    """Test _apply_rollback_from_history via QueryService."""

    def test_rollback_reads_transform_history(self, persistence, query_service, repo_id, tmp_path):
        steps = [{"file_path": "src/app.py", "original_content": "original code"}]
        persistence.persist_analysis_run(
            repository_id=repo_id,
            command="transform",
            result_type="transformation_plan",
            result_data={"plan_id": "p-1", "steps": steps},
        )
        repo = tmp_path / "test-repo"
        repo.mkdir()
        (repo / "src").mkdir()
        (repo / "src" / "app.py").write_text("modified code")

        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None

        sess = query_service._sf()
        from refactory.db.models import RepositoryModel as RM
        r = sess.get(RM, repo_id)
        r.root_path = str(repo)
        sess.commit()
        sess.close()

        svc = _service_with_query(query_service, storage)
        from refactory.transformation.models import TransformationHistory as TH
        history = TH(
            id="hist-1", plan_id="p-1", patch_id="patch-1",
            status=TransformationStatus.APPLIED,
            transformation_type=TransformationType.RENAME_FUNCTION,
            files_modified=["src/app.py"],
            rollback_patch="diff", validation_status=ValidationStatus.PASSED,
        )
        svc._history = [history]
        svc._apply_rollback_from_history(history, repo)
        assert (repo / "src" / "app.py").read_text() == "original code"

    def test_rollback_no_history_does_nothing(self, query_service, tmp_path):
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_query(query_service, storage)
        from refactory.transformation.models import TransformationHistory as TH
        history = TH(
            id="hist-1", plan_id="p-1", patch_id="patch-1",
            status=TransformationStatus.APPLIED,
            transformation_type=TransformationType.RENAME_FUNCTION,
            files_modified=[], rollback_patch="",
            validation_status=ValidationStatus.PASSED,
        )
        svc._history = [history]
        repo = tmp_path / "repo"
        repo.mkdir()
        svc._apply_rollback_from_history(history, repo)


# ===========================================================================
# Malformed History Tests
# ===========================================================================


class TestMalformedHistory:
    """Test behavior with corrupted or malformed history data."""

    def test_missing_result_data(self, persistence, query_service, repo_id):
        persistence.persist_analysis_run(
            repository_id=repo_id,
            command="apply",
            result_type="transformation_applied",
            result_data=None,
        )
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_query(query_service, storage)
        assert svc._history == []

    def test_missing_status_field(self, persistence, query_service, repo_id):
        persistence.persist_analysis_run(
            repository_id=repo_id,
            command="apply",
            result_type="transformation_applied",
            result_data={"plan_id": "p-1"},
        )
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_query(query_service, storage)
        assert svc._history == []

    def test_empty_result_data(self, persistence, query_service, repo_id):
        persistence.persist_analysis_run(
            repository_id=repo_id,
            command="apply",
            result_type="transformation_applied",
            result_data={},
        )
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_query(query_service, storage)
        assert svc._history == []

    def test_invalid_transformation_type_defaults(self, persistence, query_service, global_repo_id):
        entry = _applied_entry(transformation_type="rename_function")
        del entry["transformation_type"]
        persistence.persist_analysis_run(
            repository_id=global_repo_id,
            command="apply",
            result_type="transformation_applied",
            result_data=entry,
        )
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_query(query_service, storage)
        assert svc._history[0].transformation_type == TransformationType.RENAME_FUNCTION


# ===========================================================================
# Write Path Unchanged Tests
# ===========================================================================


class TestWritePathUnchanged:
    """Verify that writes still go through StorageService."""

    def test_persist_plan_uses_storage(self, query_service, tmp_path):
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_query(query_service, storage)
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="src/x.py",
            parameters={"old_name": "foo", "new_name": "bar"},
        )
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "src").mkdir()
        (repo / "src" / "x.py").write_text("def foo(): pass\n")
        svc.transform(request, repo)
        assert storage.store_analysis.called

    def test_rollback_writes_to_storage(self, query_service):
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_query(query_service, storage)
        from refactory.transformation.models import TransformationHistory as TH
        svc._history = [TH(
            id="h-1", plan_id="p-1", patch_id="patch-1",
            status=TransformationStatus.APPLIED,
            transformation_type=TransformationType.RENAME_FUNCTION,
            files_modified=["x.py"], rollback_patch="",
            validation_status=ValidationStatus.PASSED,
        )]
        from pathlib import Path
        svc.rollback(Path("/tmp/test-repo"))
        assert storage.store_analysis.called

    def test_apply_writes_to_storage(self, query_service, tmp_path):
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_query(query_service, storage)
        request = TransformationRequest(
            transformation_type=TransformationType.RENAME_FUNCTION,
            target_file="src/x.py",
            parameters={"old_name": "foo", "new_name": "bar"},
        )
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "src").mkdir()
        (repo / "src" / "x.py").write_text("def foo(): pass\n")
        svc.apply(request, repo)
        assert storage.store_analysis.called
        assert storage.store_metric.called


# ===========================================================================
# Migration Equivalence Tests
# ===========================================================================


class TestMigrationEquivalence:
    """Verify QueryService and StorageService produce identical results."""

    def test_identical_history_loading(self, persistence, query_service, global_repo_id):
        entry = _applied_entry(
            history_id="h-42", plan_id="p-42",
            transformation_type="rename_function",
            files_modified=["lib/core.py", "lib/utils.py"],
            patch_content="patch content here",
            rollback_patch="rollback patch here",
        )
        persistence.persist_analysis_run(
            repository_id=global_repo_id,
            command="apply",
            result_type="transformation_applied",
            result_data=entry,
        )
        storage_qs = MagicMock()
        storage_qs.get_analyses.return_value = []
        storage_qs.store_analysis.return_value = "id"
        storage_qs.store_metric.return_value = None
        svc_qs = _service_with_query(query_service, storage_qs)

        storage_st = MagicMock()
        storage_st.get_analyses.return_value = [
            {"result_data": entry, "command": "apply", "id": "x"}
        ]
        storage_st.store_analysis.return_value = "id"
        storage_st.store_metric.return_value = None
        svc_st = _service_with_storage(storage_st)

        assert len(svc_qs._history) == len(svc_st._history) == 1
        h_qs = svc_qs._history[0]
        h_st = svc_st._history[0]
        assert h_qs.id == h_st.id == "h-42"
        assert h_qs.plan_id == h_st.plan_id == "p-42"
        assert h_qs.files_modified == h_st.files_modified
        assert h_qs.patch_content == h_st.patch_content
        assert h_qs.rollback_patch == h_st.rollback_patch
        assert h_qs.transformation_type == h_st.transformation_type

    def test_result_data_byte_for_byte(self, persistence, query_service, repo_id):
        complex_data = {
            "history_id": "h-deep",
            "plan_id": "p-deep",
            "patch_id": "patch-deep",
            "status": "applied",
            "transformation_type": "extract_method",
            "files_modified": ["a.py", "b.py"],
            "patch_content": "--- a/a.py\n+++ b/a.py\n@@ -1,3 +1,5 @@",
            "rollback_patch": "+++ a/a.py\n--- b/a.py",
            "validation_status": "passed",
            "steps": [
                {
                    "file_path": "a.py",
                    "original_content": "def big():\n    pass\n",
                    "new_content": "def small():\n    pass\n\ndef big():\n    small()\n",
                    "description": "Extract method",
                }
            ],
        }
        persistence.persist_analysis_run(
            repository_id=repo_id,
            command="apply",
            result_type="transformation_applied",
            result_data=complex_data,
        )
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_query(query_service, storage)
        data = svc._read_analyses(str(Path("/tmp/test-repo")), command="apply")
        assert data[0]["result_data"] == complex_data

    def test_get_history_identical(self, persistence, query_service, global_repo_id):
        persistence.persist_analysis_run(
            repository_id=global_repo_id,
            command="apply",
            result_type="transformation_applied",
            result_data=_applied_entry(),
        )
        storage = MagicMock()
        storage.get_analyses.return_value = []
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        svc = _service_with_query(query_service, storage)
        history = svc.get_history()
        assert len(history) == 1
        assert history[0].status == TransformationStatus.APPLIED
