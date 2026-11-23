"""Tests for RepositoryQueryService — read-only query layer.

Verifies that:
  - All public query methods work correctly
  - Missing entities return None or empty lists
  - Multiple entities are handled
  - Results are plain dicts independent from ORM models
  - No writes are performed
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from refactory.core.logger import get_service_logger
from refactory.db.database import DatabaseManager
from refactory.db.persistence import PersistenceService
from refactory.db.query_service import RepositoryQueryService
from refactory.db.session import SessionFactory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_path(tmp_path):
    """Create an in-memory-style temp DB using a file for persistence across sessions."""
    return tmp_path / "test.db"


@pytest.fixture()
def session_factory(db_path):
    """Create a fresh database and session factory."""
    from sqlalchemy import create_engine

    from refactory.db.base import Base

    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)
    return SessionFactory(engine)


@pytest.fixture()
def persistence(session_factory):
    """PersistenceService for seeding test data."""
    return PersistenceService(session_factory, logger=get_service_logger("test.persist"))


@pytest.fixture()
def query(session_factory):
    """The query service under test."""
    return RepositoryQueryService(session_factory, logger=get_service_logger("test.query"))


@pytest.fixture()
def seeded_repo(persistence):
    """Create a repository and return its data."""
    return persistence.get_or_create_repository(
        name="demo-repo",
        root_path="/tmp/demo",
        default_branch="main",
        remote_url="https://github.com/test/demo",
    )


@pytest.fixture()
def seeded_file(persistence, seeded_repo):
    """Create a file record and return its data."""
    return persistence.persist_file(
        repository_id=seeded_repo["id"],
        path="src/auth.py",
        language="python",
        sha256="deadbeef",
        size=1024,
    )


@pytest.fixture()
def seeded_review(persistence, seeded_repo):
    """Create a review with suggestions and return its data."""
    return persistence.persist_review(
        repository_id=seeded_repo["id"],
        pr_number=42,
        provider="gemini",
        model="gemini-2.0-flash",
        risk="medium",
        confidence=0.85,
        summary="Found 3 issues",
        suggestions=[
            {
                "file": "src/auth.py",
                "line": 15,
                "severity": "high",
                "category": "security",
                "title": "SQL injection",
                "explanation": "User input not sanitized",
                "suggested_fix": "Use parameterized queries",
                "confidence": 0.9,
                "estimated_impact": "critical",
            },
            {
                "file": "src/util.py",
                "line": 42,
                "severity": "medium",
                "category": "performance",
                "title": "N+1 query",
                "explanation": "Loop queries DB",
                "suggested_fix": "Use bulk query",
                "confidence": 0.75,
                "estimated_impact": "high",
            },
        ],
    )


# ---------------------------------------------------------------------------
# Tests: Repository queries
# ---------------------------------------------------------------------------


class TestRepositoryQueries:

    def test_get_repository(self, query, seeded_repo):
        result = query.get_repository(seeded_repo["id"])
        assert result is not None
        assert result["id"] == seeded_repo["id"]
        assert result["name"] == "demo-repo"
        assert result["root_path"] == "/tmp/demo"

    def test_get_repository_not_found(self, query):
        result = query.get_repository("nonexistent-id")
        assert result is None

    def test_get_repository_by_name(self, query, seeded_repo):
        result = query.get_repository_by_name("demo-repo")
        assert result is not None
        assert result["id"] == seeded_repo["id"]

    def test_get_repository_by_name_not_found(self, query):
        result = query.get_repository_by_name("not-a-repo")
        assert result is None

    def test_get_repository_by_root(self, query, seeded_repo):
        result = query.get_repository_by_root("/tmp/demo")
        assert result is not None
        assert result["name"] == "demo-repo"

    def test_get_repository_by_root_not_found(self, query):
        result = query.get_repository_by_root("/nonexistent")
        assert result is None

    def test_list_repositories_empty(self, query):
        result = query.list_repositories()
        assert result == []

    def test_list_repositories(self, query, seeded_repo):
        result = query.list_repositories()
        assert len(result) == 1
        assert result[0]["id"] == seeded_repo["id"]

    def test_list_repositories_multiple(self, query, persistence):
        persistence.get_or_create_repository(name="repo-a", root_path="/a")
        persistence.get_or_create_repository(name="repo-b", root_path="/b")
        persistence.get_or_create_repository(name="repo-c", root_path="/c")
        result = query.list_repositories()
        assert len(result) == 3

    def test_repository_dict_fields(self, query, seeded_repo):
        result = query.get_repository(seeded_repo["id"])
        expected_keys = {"id", "name", "root_path", "default_branch", "remote_url", "created_at", "updated_at"}
        assert set(result.keys()) == expected_keys

    def test_repository_default_branch(self, query, seeded_repo):
        result = query.get_repository(seeded_repo["id"])
        assert result["default_branch"] == "main"

    def test_repository_remote_url(self, query, seeded_repo):
        result = query.get_repository(seeded_repo["id"])
        assert result["remote_url"] == "https://github.com/test/demo"


# ---------------------------------------------------------------------------
# Tests: File queries
# ---------------------------------------------------------------------------


class TestFileQueries:

    def test_get_files(self, query, seeded_repo, seeded_file):
        result = query.get_files(seeded_repo["id"])
        assert len(result) == 1
        assert result[0]["path"] == "src/auth.py"

    def test_get_files_empty(self, query, seeded_repo):
        result = query.get_files(seeded_repo["id"])
        assert result == []

    def test_get_files_multiple(self, query, persistence, seeded_repo):
        for i in range(5):
            persistence.persist_file(
                repository_id=seeded_repo["id"],
                path=f"mod_{i}.py",
                language="python",
            )
        result = query.get_files(seeded_repo["id"])
        assert len(result) == 5

    def test_get_files_language_filter(self, query, persistence, seeded_repo):
        persistence.persist_file(repository_id=seeded_repo["id"], path="a.py", language="python")
        persistence.persist_file(repository_id=seeded_repo["id"], path="b.ts", language="typescript")
        result = query.get_files(seeded_repo["id"], language="python")
        assert len(result) == 1
        assert result[0]["path"] == "a.py"

    def test_get_file(self, query, seeded_repo, seeded_file):
        result = query.get_file(seeded_repo["id"], "src/auth.py")
        assert result is not None
        assert result["language"] == "python"
        assert result["sha256"] == "deadbeef"
        assert result["size"] == 1024

    def test_get_file_not_found(self, query, seeded_repo):
        result = query.get_file(seeded_repo["id"], "nonexistent.py")
        assert result is None

    def test_file_dict_fields(self, query, seeded_repo, seeded_file):
        result = query.get_file(seeded_repo["id"], "src/auth.py")
        expected_keys = {"id", "repository_id", "path", "language", "sha256", "size", "last_indexed"}
        assert set(result.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Tests: Symbol & Import queries
# ---------------------------------------------------------------------------


class TestSymbolImportQueries:

    def test_get_symbols(self, query, persistence, seeded_repo, seeded_file):
        persistence.persist_symbols(
            seeded_file["id"],
            [
                {"name": "login", "type": "function", "line": 10},
                {"name": "User", "type": "class", "line": 25},
            ],
        )
        result = query.get_symbols(seeded_file["id"])
        assert len(result) == 2
        names = {s["name"] for s in result}
        assert names == {"login", "User"}

    def test_get_symbols_empty(self, query, seeded_file):
        result = query.get_symbols(seeded_file["id"])
        assert result == []

    def test_get_symbols_dict_fields(self, query, persistence, seeded_file):
        persistence.persist_symbols(seeded_file["id"], [{"name": "fn", "type": "function", "line": 1}])
        result = query.get_symbols(seeded_file["id"])
        expected_keys = {"id", "file_id", "name", "type", "line"}
        assert set(result[0].keys()) == expected_keys

    def test_get_imports(self, query, persistence, seeded_repo, seeded_file):
        persistence.persist_imports(
            seeded_file["id"],
            [
                {"module": "os", "symbol": "path"},
                {"module": "datetime", "symbol": "datetime"},
            ],
        )
        result = query.get_imports(seeded_file["id"])
        assert len(result) == 2
        modules = {i["module"] for i in result}
        assert modules == {"os", "datetime"}

    def test_get_imports_empty(self, query, seeded_file):
        result = query.get_imports(seeded_file["id"])
        assert result == []

    def test_get_imports_dict_fields(self, query, persistence, seeded_file):
        persistence.persist_imports(seeded_file["id"], [{"module": "sys", "symbol": "argv"}])
        result = query.get_imports(seeded_file["id"])
        expected_keys = {"id", "file_id", "module", "symbol"}
        assert set(result[0].keys()) == expected_keys


# ---------------------------------------------------------------------------
# Tests: Review queries
# ---------------------------------------------------------------------------


class TestReviewQueries:

    def test_get_latest_review(self, query, seeded_repo, seeded_review):
        result = query.get_latest_review(seeded_repo["id"])
        assert result is not None
        assert result["pr_number"] == 42
        assert result["risk"] == "medium"

    def test_get_latest_review_none(self, query, seeded_repo):
        result = query.get_latest_review(seeded_repo["id"])
        assert result is None

    def test_get_review(self, query, seeded_review):
        result = query.get_review(seeded_review["id"])
        assert result is not None
        assert result["provider"] == "gemini"
        assert result["model"] == "gemini-2.0-flash"
        assert result["confidence"] == 0.85

    def test_get_review_not_found(self, query):
        result = query.get_review("nonexistent")
        assert result is None

    def test_get_reviews(self, query, seeded_repo, seeded_review):
        result = query.get_reviews(seeded_repo["id"])
        assert len(result) == 1
        assert result[0]["id"] == seeded_review["id"]

    def test_get_reviews_empty(self, query, seeded_repo):
        result = query.get_reviews(seeded_repo["id"])
        assert result == []

    def test_get_reviews_multiple(self, query, persistence, seeded_repo):
        for i in range(3):
            persistence.persist_review(
                repository_id=seeded_repo["id"],
                pr_number=i + 1,
                risk="low",
                summary=f"Review {i}",
            )
        result = query.get_reviews(seeded_repo["id"])
        assert len(result) == 3

    def test_get_review_suggestions(self, query, seeded_review):
        result = query.get_review_suggestions(seeded_review["id"])
        assert len(result) == 2
        severities = {s["severity"] for s in result}
        assert "high" in severities
        assert "medium" in severities

    def test_get_review_suggestions_empty(self, query):
        result = query.get_review_suggestions("nonexistent")
        assert result == []

    def test_suggestion_dict_fields(self, query, seeded_review):
        result = query.get_review_suggestions(seeded_review["id"])
        expected_keys = {
            "id", "review_id", "file", "line", "severity",
            "category", "title", "explanation", "suggested_fix",
            "confidence", "estimated_impact",
            "status", "updated_at", "resolved_at", "ignored_at",
            "updated_by", "recommendation_id",
        }
        assert set(result[0].keys()) == expected_keys
        assert result[0]["status"] == "pending"

    def test_review_dict_fields(self, query, seeded_review):
        result = query.get_review(seeded_review["id"])
        expected_keys = {
            "id", "repository_id", "pr_number", "provider",
            "model", "risk", "confidence", "summary", "created_at",
            "suggestion_count", "file_count", "critical_count", "warning_count",
        }
        assert set(result.keys()) == expected_keys
        assert result["suggestion_count"] == 2
        assert result["file_count"] >= 1
        assert result["critical_count"] == 1
        assert result["warning_count"] == 1


# ---------------------------------------------------------------------------
# Tests: Recommendation queries
# ---------------------------------------------------------------------------


class TestRecommendationQueries:

    def test_get_recommendations(self, query, persistence, seeded_repo):
        persistence.persist_recommendations(
            seeded_repo["id"],
            [
                {"type": "refactor", "priority": "high", "title": "Extract method", "description": "..."},
                {"type": "test", "priority": "medium", "title": "Add unit tests", "description": "..."},
            ],
        )
        result = query.get_recommendations(seeded_repo["id"])
        assert len(result) == 2

    def test_get_recommendations_empty(self, query, seeded_repo):
        result = query.get_recommendations(seeded_repo["id"])
        assert result == []

    def test_get_recommendations_status_filter(self, query, persistence, seeded_repo):
        persistence.persist_recommendations(
            seeded_repo["id"],
            [
                {"type": "refactor", "priority": "high", "title": "A", "description": "", "status": "pending"},
                {"type": "test", "priority": "low", "title": "B", "description": "", "status": "completed"},
            ],
        )
        result = query.get_recommendations(seeded_repo["id"], status="pending")
        assert len(result) == 1
        assert result[0]["title"] == "A"

    def test_recommendation_dict_fields(self, query, persistence, seeded_repo):
        persistence.persist_recommendations(
            seeded_repo["id"],
            [{"type": "refactor", "priority": "high", "title": "Test", "description": "Desc"}],
        )
        result = query.get_recommendations(seeded_repo["id"])
        expected_keys = {"id", "repository_id", "type", "priority", "status", "title", "description", "created_at"}
        assert set(result[0].keys()) == expected_keys


# ---------------------------------------------------------------------------
# Tests: Graph queries
# ---------------------------------------------------------------------------


class TestGraphQueries:

    def test_get_graph(self, query, persistence, seeded_repo):
        persistence.persist_graph(
            seeded_repo["id"],
            nodes=[
                {"name": "auth.py", "type": "file"},
                {"name": "User", "type": "class"},
            ],
            edges=[
                {"source_name": "auth.py", "target_name": "User", "relationship_": "CONTAINS"},
            ],
        )
        result = query.get_graph(seeded_repo["id"])
        assert result["node_count"] == 2
        assert result["edge_count"] == 1
        assert result["repository_id"] == seeded_repo["id"]

    def test_get_graph_empty(self, query, seeded_repo):
        result = query.get_graph(seeded_repo["id"])
        assert result["node_count"] == 0
        assert result["edge_count"] == 0
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_get_graph_nodes(self, query, persistence, seeded_repo):
        persistence.persist_graph(
            seeded_repo["id"],
            nodes=[
                {"name": "a.py", "type": "file"},
                {"name": "Foo", "type": "class"},
                {"name": "bar", "type": "function"},
            ],
            edges=[],
        )
        result = query.get_graph_nodes(seeded_repo["id"])
        assert len(result) == 3
        types = {n["type"] for n in result}
        assert types == {"file", "class", "function"}

    def test_get_graph_nodes_type_filter(self, query, persistence, seeded_repo):
        persistence.persist_graph(
            seeded_repo["id"],
            nodes=[
                {"name": "a.py", "type": "file"},
                {"name": "Foo", "type": "class"},
            ],
            edges=[],
        )
        result = query.get_graph_nodes(seeded_repo["id"], node_type="class")
        assert len(result) == 1
        assert result[0]["name"] == "Foo"

    def test_get_graph_edges(self, query, persistence, seeded_repo):
        persistence.persist_graph(
            seeded_repo["id"],
            nodes=[
                {"name": "a.py", "type": "file"},
                {"name": "b.py", "type": "file"},
            ],
            edges=[
                {"source_name": "a.py", "target_name": "b.py", "relationship_": "IMPORTS"},
            ],
        )
        result = query.get_graph_edges(seeded_repo["id"])
        assert len(result) == 1
        assert result[0]["relationship"] == "IMPORTS"

    def test_graph_node_dict_fields(self, query, persistence, seeded_repo):
        persistence.persist_graph(
            seeded_repo["id"],
            nodes=[{"name": "test", "type": "file"}],
            edges=[],
        )
        result = query.get_graph_nodes(seeded_repo["id"])
        expected_keys = {"id", "repository_id", "name", "type"}
        assert set(result[0].keys()) == expected_keys

    def test_graph_edge_dict_fields(self, query, persistence, seeded_repo):
        persistence.persist_graph(
            seeded_repo["id"],
            nodes=[{"name": "a", "type": "file"}, {"name": "b", "type": "file"}],
            edges=[{"source_name": "a", "target_name": "b", "relationship_": "IMPORTS"}],
        )
        result = query.get_graph_edges(seeded_repo["id"])
        expected_keys = {"id", "source_node", "target_node", "relationship"}
        assert set(result[0].keys()) == expected_keys


# ---------------------------------------------------------------------------
# Tests: Embedding queries
# ---------------------------------------------------------------------------


class TestEmbeddingQueries:

    def test_get_embeddings(self, query, persistence, seeded_repo, seeded_file):
        persistence.persist_embeddings(
            seeded_file["id"],
            [
                {"chunk_id": "auth.py::file", "provider": "st", "model": "all-MiniLM", "vector_reference": "chroma:auth::file"},
                {"chunk_id": "auth.py::module", "provider": "st", "model": "all-MiniLM", "vector_reference": "chroma:auth::module"},
            ],
        )
        result = query.get_embeddings(seeded_file["id"])
        assert len(result) == 2
        chunk_ids = {e["chunk_id"] for e in result}
        assert chunk_ids == {"auth.py::file", "auth.py::module"}

    def test_get_embeddings_empty(self, query, seeded_file):
        result = query.get_embeddings(seeded_file["id"])
        assert result == []

    def test_embedding_dict_fields(self, query, persistence, seeded_file):
        persistence.persist_embeddings(
            seeded_file["id"],
            [{"chunk_id": "test", "provider": "p", "model": "m", "vector_reference": "ref"}],
        )
        result = query.get_embeddings(seeded_file["id"])
        expected_keys = {"id", "file_id", "chunk_id", "provider", "model", "vector_reference"}
        assert set(result[0].keys()) == expected_keys

    def test_embeddings_no_vectors_in_result(self, query, persistence, seeded_file):
        """Confirm no vector data leaks into the query response."""
        persistence.persist_embeddings(
            seeded_file["id"],
            [{"chunk_id": "test", "provider": "p", "model": "m", "vector_reference": "ref"}],
        )
        result = query.get_embeddings(seeded_file["id"])
        for emb in result:
            for value in emb.values():
                assert not isinstance(value, list), "Vector data should not be in result"


# ---------------------------------------------------------------------------
# Tests: Cross-entity scenarios
# ---------------------------------------------------------------------------


class TestCrossEntity:

    def test_full_read_pipeline(self, query, persistence, seeded_repo):
        """End-to-end: create data via PersistenceService, read via QueryService."""
        file_data = persistence.persist_file(
            repository_id=seeded_repo["id"],
            path="main.py",
            language="python",
        )
        persistence.persist_symbols(file_data["id"], [{"name": "main", "type": "function", "line": 1}])
        persistence.persist_imports(file_data["id"], [{"module": "sys", "symbol": "argv"}])
        persistence.persist_review(
            repository_id=seeded_repo["id"],
            pr_number=1,
            risk="low",
            summary="OK",
        )
        persistence.persist_graph(
            seeded_repo["id"],
            nodes=[{"name": "main.py", "type": "file"}],
            edges=[],
        )
        persistence.persist_embeddings(
            file_data["id"],
            [{"chunk_id": "main::file", "provider": "st", "model": "m", "vector_reference": "ref"}],
        )

        repo = query.get_repository(seeded_repo["id"])
        assert repo is not None

        files = query.get_files(seeded_repo["id"])
        assert len(files) == 1

        symbols = query.get_symbols(file_data["id"])
        assert len(symbols) == 1

        imports = query.get_imports(file_data["id"])
        assert len(imports) == 1

        review = query.get_latest_review(seeded_repo["id"])
        assert review is not None

        graph = query.get_graph(seeded_repo["id"])
        assert graph["node_count"] == 1

        embeddings = query.get_embeddings(file_data["id"])
        assert len(embeddings) == 1

    def test_multiple_repositories_isolated(self, query, persistence):
        """Data for one repository does not leak into another's queries."""
        repo_a = persistence.get_or_create_repository(name="a", root_path="/a")
        repo_b = persistence.get_or_create_repository(name="b", root_path="/b")
        persistence.persist_file(repository_id=repo_a["id"], path="a.py", language="python")
        persistence.persist_file(repository_id=repo_b["id"], path="b.py", language="python")

        files_a = query.get_files(repo_a["id"])
        files_b = query.get_files(repo_b["id"])
        assert len(files_a) == 1
        assert len(files_b) == 1
        assert files_a[0]["path"] == "a.py"
        assert files_b[0]["path"] == "b.py"


# ---------------------------------------------------------------------------
# Tests: Backward compatibility & no-write guarantee
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:

    def test_instantiates_with_session_factory_only(self, session_factory):
        service = RepositoryQueryService(session_factory)
        assert service is not None

    def test_instantiates_with_logger(self, session_factory):
        service = RepositoryQueryService(session_factory, logger=get_service_logger("test"))
        assert service is not None

    def test_returns_plain_dicts(self, query, seeded_repo):
        result = query.get_repository(seeded_repo["id"])
        assert isinstance(result, dict)

    def test_no_sqlalchemy_objects_in_result(self, query, seeded_repo, seeded_file):
        result = query.get_file(seeded_repo["id"], "src/auth.py")
        for value in result.values():
            assert not hasattr(value, "_sa_instance_state")
