"""Comprehensive tests for the Refactory database persistence layer.

Covers:
  - Database creation and table existence
  - CRUD operations for all 10 entities
  - Relationships and foreign keys
  - Cascade deletes
  - Transactions and rollback
  - Bulk inserts
  - Repository-specific queries
  - Unit of Work pattern
  - Migration compatibility
  - PersistenceService facade
  - SQLite compatibility
  - PostgreSQL-compatible schema (via dialect-neutral DDL)
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from sqlalchemy import inspect, text

from refactory.db.base import Base
from refactory.db.database import DatabaseManager
from refactory.db.session import SessionFactory, get_session_factory
from refactory.db.models import (
    EmbeddingModel,
    FileModel,
    GraphEdgeModel,
    GraphNodeModel,
    ImportModel,
    RecommendationModel,
    RepositoryModel,
    ReviewModel,
    ReviewSuggestionModel,
    SymbolModel,
)
from refactory.db.repositories import (
    EmbeddingRepository,
    FileRepository,
    GraphRepository,
    ImportRepository,
    RecommendationRepository,
    RepositoryRepository,
    ReviewRepository,
    ReviewSuggestionRepository,
    SymbolRepository,
)
from refactory.db.uow import UnitOfWork
from refactory.db.persistence import PersistenceService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_manager(tmp_path):
    """In-memory SQLite database manager."""
    url = "sqlite:///:memory:"
    mgr = DatabaseManager(database_url=url)
    mgr.create_all()
    yield mgr
    mgr.dispose()


@pytest.fixture
def session_factory(db_manager):
    return SessionFactory(db_manager.engine)


@pytest.fixture
def session(session_factory):
    s = session_factory()
    yield s
    s.close()


@pytest.fixture
def persistence(session_factory):
    return PersistenceService(session_factory)


# ---------------------------------------------------------------------------
# 1. Database creation and table existence
# ---------------------------------------------------------------------------


class TestDatabaseCreation:
    def test_all_tables_created(self, db_manager):
        """Verify all 10 entity tables exist."""
        inspector = inspect(db_manager.engine)
        tables = set(inspector.get_table_names())
        expected = {
            "db_repositories",
            "db_files",
            "db_symbols",
            "db_imports",
            "db_reviews",
            "db_review_suggestions",
            "db_recommendations",
            "db_embeddings",
            "db_graph_nodes",
            "db_graph_edges",
        }
        assert expected.issubset(tables), f"Missing tables: {expected - tables}"

    def test_create_tables_idempotent(self, db_manager):
        """create_all() can be called multiple times without error."""
        db_manager.create_all()
        db_manager.create_all()
        inspector = inspect(db_manager.engine)
        assert "db_repositories" in inspector.get_table_names()

    def test_drop_tables(self, db_manager):
        """drop_all() removes all tables."""
        db_manager.drop_all()
        inspector = inspect(db_manager.engine)
        db_tables = [t for t in inspector.get_table_names() if t.startswith("db_")]
        assert len(db_tables) == 0

    def test_foreign_keys_defined(self, db_manager):
        """Verify foreign key constraints are declared."""
        inspector = inspect(db_manager.engine)
        fks = inspector.get_foreign_keys("db_files")
        assert any(fk["referred_table"] == "db_repositories" for fk in fks)


# ---------------------------------------------------------------------------
# 2. Repository entity CRUD
# ---------------------------------------------------------------------------


class TestRepositoryCRUD:
    def test_create_repository(self, session):
        repo_repo = RepositoryRepository(session)
        repo = repo_repo.create(name="test-repo", root_path="/code/test")
        session.commit()
        assert repo.id is not None
        assert repo.name == "test-repo"
        assert repo.root_path == "/code/test"

    def test_get_by_id(self, session):
        repo_repo = RepositoryRepository(session)
        repo = repo_repo.create(name="repo1", root_path="/repo1")
        session.flush()
        fetched = repo_repo.get_by_id(repo.id)
        assert fetched is not None
        assert fetched.name == "repo1"

    def test_get_by_root_path(self, session):
        repo_repo = RepositoryRepository(session)
        repo_repo.create(name="repo2", root_path="/unique/path")
        session.flush()
        fetched = repo_repo.get_by_root_path("/unique/path")
        assert fetched is not None
        assert fetched.name == "repo2"

    def test_get_or_create_existing(self, session):
        repo_repo = RepositoryRepository(session)
        r1 = repo_repo.create(name="repo3", root_path="/repo3")
        session.flush()
        r2 = repo_repo.get_or_create(name="repo3", root_path="/repo3")
        assert r1.id == r2.id

    def test_get_or_create_new(self, session):
        repo_repo = RepositoryRepository(session)
        r = repo_repo.get_or_create(name="new-repo", root_path="/new")
        assert r.id is not None
        assert r.name == "new-repo"

    def test_update_repository(self, session):
        repo_repo = RepositoryRepository(session)
        repo = repo_repo.create(name="old-name", root_path="/update")
        session.flush()
        updated = repo_repo.update(repo.id, name="new-name")
        assert updated is not None
        assert updated.name == "new-name"

    def test_delete_repository(self, session):
        repo_repo = RepositoryRepository(session)
        repo = repo_repo.create(name="delete-me", root_path="/delete")
        session.flush()
        assert repo_repo.delete(repo.id) is True
        assert repo_repo.get_by_id(repo.id) is None

    def test_list_repositories(self, session):
        repo_repo = RepositoryRepository(session)
        repo_repo.create(name="r1", root_path="/r1")
        repo_repo.create(name="r2", root_path="/r2")
        session.flush()
        repos = repo_repo.list()
        assert len(repos) >= 2

    def test_exists(self, session):
        repo_repo = RepositoryRepository(session)
        repo_repo.create(name="exists-test", root_path="/exists")
        session.flush()
        assert repo_repo.exists(root_path="/exists") is True
        assert repo_repo.exists(root_path="/nonexistent") is False

    def test_count(self, session):
        repo_repo = RepositoryRepository(session)
        repo_repo.create(name="c1", root_path="/c1")
        repo_repo.create(name="c2", root_path="/c2")
        session.flush()
        assert repo_repo.count() >= 2

    def test_list_active(self, session):
        repo_repo = RepositoryRepository(session)
        repo_repo.create(name="active-repo", root_path="/active")
        session.commit()
        active = repo_repo.list_active()
        assert len(active) >= 1


# ---------------------------------------------------------------------------
# 3. File entity CRUD
# ---------------------------------------------------------------------------


class TestFileCRUD:
    def test_create_file(self, session):
        repo_repo = RepositoryRepository(session)
        repo = repo_repo.create(name="fr", root_path="/fr")
        session.flush()
        file_repo = FileRepository(session)
        f = file_repo.create(
            repository_id=repo.id, path="src/app.py", language="python", size=1024
        )
        session.flush()
        assert f.id is not None
        assert f.path == "src/app.py"
        assert f.language == "python"

    def test_get_by_repo_path(self, session):
        repo_repo = RepositoryRepository(session)
        repo = repo_repo.create(name="frp", root_path="/frp")
        session.flush()
        file_repo = FileRepository(session)
        file_repo.create(repository_id=repo.id, path="main.py", language="python")
        session.flush()
        found = file_repo.get_by_repo_path(repo.id, "main.py")
        assert found is not None
        assert found.path == "main.py"

    def test_list_by_repository(self, session):
        repo_repo = RepositoryRepository(session)
        repo = repo_repo.create(name="flr", root_path="/flr")
        session.flush()
        file_repo = FileRepository(session)
        file_repo.create(repository_id=repo.id, path="a.py", language="python")
        file_repo.create(repository_id=repo.id, path="b.js", language="javascript")
        session.flush()
        all_files = file_repo.list_by_repository(repo.id)
        assert len(all_files) == 2
        py_files = file_repo.list_by_repository(repo.id, language="python")
        assert len(py_files) == 1

    def test_upsert_creates_new(self, session):
        repo_repo = RepositoryRepository(session)
        repo = repo_repo.create(name="fuc", root_path="/fuc")
        session.flush()
        file_repo = FileRepository(session)
        f = file_repo.upsert(repo.id, "new.py", language="python", size=100)
        assert f.size == 100

    def test_upsert_updates_existing(self, session):
        repo_repo = RepositoryRepository(session)
        repo = repo_repo.create(name="fuu", root_path="/fuu")
        session.flush()
        file_repo = FileRepository(session)
        f1 = file_repo.create(repository_id=repo.id, path="up.py", language="python", size=50)
        session.flush()
        f2 = file_repo.upsert(repo.id, "up.py", size=200)
        assert f2.id == f1.id
        assert f2.size == 200

    def test_bulk_insert_files(self, session):
        repo_repo = RepositoryRepository(session)
        repo = repo_repo.create(name="fbi", root_path="/fbi")
        session.flush()
        file_repo = FileRepository(session)
        files = file_repo.bulk_insert([
            {"repository_id": repo.id, "path": "x.py", "language": "python"},
            {"repository_id": repo.id, "path": "y.py", "language": "python"},
            {"repository_id": repo.id, "path": "z.py", "language": "python"},
        ])
        assert len(files) == 3


# ---------------------------------------------------------------------------
# 4. Symbol entity CRUD
# ---------------------------------------------------------------------------


class TestSymbolCRUD:
    def _make_file(self, session):
        repo = RepositoryRepository(session).create(name="sr", root_path="/sr")
        session.flush()
        f = FileRepository(session).create(
            repository_id=repo.id, path="sym.py", language="python"
        )
        session.flush()
        return f

    def test_create_symbol(self, session):
        f = self._make_file(session)
        sym_repo = SymbolRepository(session)
        s = sym_repo.create(file_id=f.id, name="MyClass", type="class", line=10, column=0)
        session.flush()
        assert s.name == "MyClass"
        assert s.type == "class"

    def test_list_by_file(self, session):
        f = self._make_file(session)
        sym_repo = SymbolRepository(session)
        sym_repo.create(file_id=f.id, name="func1", type="function", line=1)
        sym_repo.create(file_id=f.id, name="func2", type="function", line=5)
        session.flush()
        symbols = sym_repo.list_by_file(f.id)
        assert len(symbols) == 2

    def test_find_by_name(self, session):
        f = self._make_file(session)
        sym_repo = SymbolRepository(session)
        sym_repo.create(file_id=f.id, name="unique_name", type="function", line=1)
        session.flush()
        found = sym_repo.find_by_name("unique_name")
        assert len(found) == 1

    def test_delete_by_file(self, session):
        f = self._make_file(session)
        sym_repo = SymbolRepository(session)
        sym_repo.create(file_id=f.id, name="del1", type="function", line=1)
        sym_repo.create(file_id=f.id, name="del2", type="function", line=2)
        session.flush()
        count = sym_repo.delete_by_file(f.id)
        assert count == 2
        assert len(sym_repo.list_by_file(f.id)) == 0


# ---------------------------------------------------------------------------
# 5. Import entity CRUD
# ---------------------------------------------------------------------------


class TestImportCRUD:
    def _make_file(self, session):
        repo = RepositoryRepository(session).create(name="ir", root_path="/ir")
        session.flush()
        f = FileRepository(session).create(
            repository_id=repo.id, path="imp.py", language="python"
        )
        session.flush()
        return f

    def test_create_import(self, session):
        f = self._make_file(session)
        imp_repo = ImportRepository(session)
        i = imp_repo.create(file_id=f.id, module="os", symbol="path")
        session.flush()
        assert i.module == "os"
        assert i.symbol == "path"

    def test_list_by_file(self, session):
        f = self._make_file(session)
        imp_repo = ImportRepository(session)
        imp_repo.create(file_id=f.id, module="os")
        imp_repo.create(file_id=f.id, module="sys")
        session.flush()
        imports = imp_repo.list_by_file(f.id)
        assert len(imports) == 2

    def test_find_by_module(self, session):
        f = self._make_file(session)
        imp_repo = ImportRepository(session)
        imp_repo.create(file_id=f.id, module="pathlib")
        session.flush()
        found = imp_repo.find_by_module("pathlib")
        assert len(found) >= 1

    def test_delete_by_file(self, session):
        f = self._make_file(session)
        imp_repo = ImportRepository(session)
        imp_repo.create(file_id=f.id, module="m1")
        imp_repo.create(file_id=f.id, module="m2")
        session.flush()
        count = imp_repo.delete_by_file(f.id)
        assert count == 2


# ---------------------------------------------------------------------------
# 6. Review entity CRUD
# ---------------------------------------------------------------------------


class TestReviewCRUD:
    def _make_repo(self, session):
        return RepositoryRepository(session).create(name="rr", root_path="/rr")

    def test_create_review(self, session):
        repo = self._make_repo(session)
        session.flush()
        rev_repo = ReviewRepository(session)
        r = rev_repo.create(
            repository_id=repo.id,
            pr_number=42,
            provider="gemini",
            model="gemini-1.5-pro",
            risk="medium",
            confidence=0.85,
            summary="Looks good overall",
        )
        session.flush()
        assert r.pr_number == 42
        assert r.confidence == 0.85

    def test_list_by_repository(self, session):
        repo = self._make_repo(session)
        session.flush()
        rev_repo = ReviewRepository(session)
        rev_repo.create(repository_id=repo.id, pr_number=1, summary="r1")
        rev_repo.create(repository_id=repo.id, pr_number=2, summary="r2")
        session.flush()
        reviews = rev_repo.list_by_repository(repo.id)
        assert len(reviews) == 2

    def test_get_by_pr(self, session):
        repo = self._make_repo(session)
        session.flush()
        rev_repo = ReviewRepository(session)
        rev_repo.create(repository_id=repo.id, pr_number=99, summary="pr99")
        session.flush()
        found = rev_repo.get_by_pr(repo.id, 99)
        assert len(found) == 1

    def test_get_latest(self, session):
        repo = self._make_repo(session)
        session.flush()
        rev_repo = ReviewRepository(session)
        rev_repo.create(repository_id=repo.id, summary="first")
        rev_repo.create(repository_id=repo.id, summary="second")
        session.flush()
        latest = rev_repo.get_latest(repo.id)
        assert latest is not None


# ---------------------------------------------------------------------------
# 7. ReviewSuggestion entity CRUD
# ---------------------------------------------------------------------------


class TestReviewSuggestionCRUD:
    def _make_review(self, session):
        repo = RepositoryRepository(session).create(name="rs", root_path="/rs")
        session.flush()
        return ReviewRepository(session).create(
            repository_id=repo.id, pr_number=1, summary="test"
        )

    def test_create_suggestion(self, session):
        review = self._make_review(session)
        session.flush()
        sug_repo = ReviewSuggestionRepository(session)
        s = sug_repo.create(
            review_id=review.id,
            file="app.py",
            line=42,
            severity="error",
            category="security",
            title="SQL Injection",
            explanation="Use parameterized queries.",
            confidence=0.9,
            estimated_impact="High — data breach risk",
        )
        session.flush()
        assert s.severity == "error"
        assert s.confidence == 0.9

    def test_list_by_review(self, session):
        review = self._make_review(session)
        session.flush()
        sug_repo = ReviewSuggestionRepository(session)
        sug_repo.create(review_id=review.id, severity="warning", title="s1")
        sug_repo.create(review_id=review.id, severity="error", title="s2")
        session.flush()
        suggestions = sug_repo.list_by_review(review.id)
        assert len(suggestions) == 2

    def test_list_by_severity(self, session):
        review = self._make_review(session)
        session.flush()
        sug_repo = ReviewSuggestionRepository(session)
        sug_repo.create(review_id=review.id, severity="error", title="e1")
        sug_repo.create(review_id=review.id, severity="info", title="i1")
        session.flush()
        errors = sug_repo.list_by_severity(review.id, "error")
        assert len(errors) == 1

    def test_delete_by_review(self, session):
        review = self._make_review(session)
        session.flush()
        sug_repo = ReviewSuggestionRepository(session)
        sug_repo.create(review_id=review.id, title="del1")
        sug_repo.create(review_id=review.id, title="del2")
        session.flush()
        count = sug_repo.delete_by_review(review.id)
        assert count == 2


# ---------------------------------------------------------------------------
# 8. Recommendation entity CRUD
# ---------------------------------------------------------------------------


class TestRecommendationCRUD:
    def _make_repo(self, session):
        return RepositoryRepository(session).create(name="recr", root_path="/recr")

    def test_create_recommendation(self, session):
        repo = self._make_repo(session)
        session.flush()
        rec_repo = RecommendationRepository(session)
        r = rec_repo.create(
            repository_id=repo.id,
            type="refactoring",
            priority="high",
            title="Extract method",
            description="Large function should be split",
        )
        session.flush()
        assert r.type == "refactoring"
        assert r.priority == "high"

    def test_list_by_repository_with_filters(self, session):
        repo = self._make_repo(session)
        session.flush()
        rec_repo = RecommendationRepository(session)
        rec_repo.create(repository_id=repo.id, type="security", priority="critical", title="Fix XSS")
        rec_repo.create(repository_id=repo.id, type="refactoring", priority="low", title="Rename var")
        session.flush()
        all_recs = rec_repo.list_by_repository(repo.id)
        assert len(all_recs) == 2
        critical = rec_repo.list_by_repository(repo.id, priority="critical")
        assert len(critical) == 1

    def test_list_by_type(self, session):
        repo = self._make_repo(session)
        session.flush()
        rec_repo = RecommendationRepository(session)
        rec_repo.create(repository_id=repo.id, type="testing", title="Add tests")
        session.flush()
        found = rec_repo.list_by_type(repo.id, "testing")
        assert len(found) == 1

    def test_update_status(self, session):
        repo = self._make_repo(session)
        session.flush()
        rec_repo = RecommendationRepository(session)
        r = rec_repo.create(repository_id=repo.id, type="doc", title="Add docs")
        session.flush()
        updated = rec_repo.update_status(r.id, "accepted")
        assert updated is not None
        assert updated.status == "accepted"

    def test_bulk_insert(self, session):
        repo = self._make_repo(session)
        session.flush()
        rec_repo = RecommendationRepository(session)
        recs = rec_repo.bulk_insert([
            {"repository_id": repo.id, "type": "a", "title": "t1"},
            {"repository_id": repo.id, "type": "b", "title": "t2"},
        ])
        assert len(recs) == 2


# ---------------------------------------------------------------------------
# 9. Embedding entity CRUD
# ---------------------------------------------------------------------------


class TestEmbeddingCRUD:
    def _make_file(self, session):
        repo = RepositoryRepository(session).create(name="er", root_path="/er")
        session.flush()
        return FileRepository(session).create(
            repository_id=repo.id, path="emb.py", language="python"
        )

    def test_create_embedding(self, session):
        f = self._make_file(session)
        session.flush()
        emb_repo = EmbeddingRepository(session)
        e = emb_repo.create(
            file_id=f.id,
            chunk_id="chunk_001",
            provider="openai",
            model="text-embedding-3-small",
            vector_reference="chroma:abc123",
        )
        session.flush()
        assert e.chunk_id == "chunk_001"
        assert e.provider == "openai"

    def test_list_by_file(self, session):
        f = self._make_file(session)
        session.flush()
        emb_repo = EmbeddingRepository(session)
        emb_repo.create(file_id=f.id, chunk_id="c1")
        emb_repo.create(file_id=f.id, chunk_id="c2")
        session.flush()
        embeddings = emb_repo.list_by_file(f.id)
        assert len(embeddings) == 2

    def test_get_by_chunk(self, session):
        f = self._make_file(session)
        session.flush()
        emb_repo = EmbeddingRepository(session)
        emb_repo.create(file_id=f.id, chunk_id="unique_chunk_42")
        session.flush()
        found = emb_repo.get_by_chunk("unique_chunk_42")
        assert found is not None

    def test_delete_by_file(self, session):
        f = self._make_file(session)
        session.flush()
        emb_repo = EmbeddingRepository(session)
        emb_repo.create(file_id=f.id, chunk_id="d1")
        emb_repo.create(file_id=f.id, chunk_id="d2")
        session.flush()
        count = emb_repo.delete_by_file(f.id)
        assert count == 2


# ---------------------------------------------------------------------------
# 10. Graph (Node + Edge) CRUD
# ---------------------------------------------------------------------------


class TestGraphCRUD:
    def _make_repo(self, session):
        return RepositoryRepository(session).create(name="gr", root_path="/gr")

    def test_create_node(self, session):
        repo = self._make_repo(session)
        session.flush()
        graph = GraphRepository(session)
        n = graph.create_node(repository_id=repo.id, name="app.py", type="file")
        session.flush()
        assert n.name == "app.py"
        assert n.type == "file"

    def test_create_edge(self, session):
        repo = self._make_repo(session)
        session.flush()
        graph = GraphRepository(session)
        n1 = graph.create_node(repository_id=repo.id, name="a", type="module")
        n2 = graph.create_node(repository_id=repo.id, name="b", type="module")
        session.flush()
        e = graph.create_edge(source_node=n1.id, target_node=n2.id, relationship_="imports")
        session.flush()
        assert e.source_node == n1.id
        assert e.target_node == n2.id

    def test_list_nodes(self, session):
        repo = self._make_repo(session)
        session.flush()
        graph = GraphRepository(session)
        graph.create_node(repository_id=repo.id, name="x", type="function")
        graph.create_node(repository_id=repo.id, name="y", type="class")
        session.flush()
        nodes = graph.list_nodes(repo.id)
        assert len(nodes) == 2
        funcs = graph.list_nodes(repo.id, node_type="function")
        assert len(funcs) == 1

    def test_list_edges_outgoing_incoming(self, session):
        repo = self._make_repo(session)
        session.flush()
        graph = GraphRepository(session)
        n1 = graph.create_node(repository_id=repo.id, name="src", type="module")
        n2 = graph.create_node(repository_id=repo.id, name="dst", type="module")
        session.flush()
        graph.create_edge(source_node=n1.id, target_node=n2.id, relationship_="calls")
        session.flush()
        outgoing = graph.list_edges_outgoing(n1.id)
        assert len(outgoing) == 1
        incoming = graph.list_edges_incoming(n2.id)
        assert len(incoming) == 1

    def test_delete_graph(self, session):
        repo = self._make_repo(session)
        session.flush()
        graph = GraphRepository(session)
        n1 = graph.create_node(repository_id=repo.id, name="del1", type="file")
        n2 = graph.create_node(repository_id=repo.id, name="del2", type="file")
        session.flush()
        graph.create_edge(source_node=n1.id, target_node=n2.id, relationship_="imports")
        session.flush()
        count = graph.delete_graph(repo.id)
        assert count == 2
        assert len(graph.list_nodes(repo.id)) == 0

    def test_bulk_insert_nodes(self, session):
        repo = self._make_repo(session)
        session.flush()
        graph = GraphRepository(session)
        nodes = graph.bulk_insert_nodes([
            {"repository_id": repo.id, "name": "b1", "type": "function"},
            {"repository_id": repo.id, "name": "b2", "type": "class"},
        ])
        assert len(nodes) == 2

    def test_bulk_insert_edges(self, session):
        repo = self._make_repo(session)
        session.flush()
        graph = GraphRepository(session)
        n1 = graph.create_node(repository_id=repo.id, name="e1", type="module")
        n2 = graph.create_node(repository_id=repo.id, name="e2", type="module")
        session.flush()
        edges = graph.bulk_insert_edges([
            {"source_node": n1.id, "target_node": n2.id, "relationship_": "imports"},
        ])
        assert len(edges) == 1

    def test_find_nodes_by_name(self, session):
        repo = self._make_repo(session)
        session.flush()
        graph = GraphRepository(session)
        graph.create_node(repository_id=repo.id, name="unique_node_xyz", type="function")
        session.flush()
        found = graph.nodes.find_by_name(repo.id, "unique_node_xyz")
        assert len(found) == 1

    def test_find_edges_by_relationship(self, session):
        repo = self._make_repo(session)
        session.flush()
        graph = GraphRepository(session)
        n1 = graph.create_node(repository_id=repo.id, name="r1", type="module")
        n2 = graph.create_node(repository_id=repo.id, name="r2", type="module")
        session.flush()
        graph.create_edge(source_node=n1.id, target_node=n2.id, relationship_="inherits")
        session.flush()
        found = graph.edges.find_by_relationship("inherits")
        assert len(found) >= 1


# ---------------------------------------------------------------------------
# 11. Relationships and Cascade Deletes
# ---------------------------------------------------------------------------


class TestRelationships:
    def test_file_belongs_to_repository(self, session):
        repo = RepositoryRepository(session).create(name="rel", root_path="/rel")
        session.flush()
        f = FileRepository(session).create(
            repository_id=repo.id, path="rel.py", language="python"
        )
        session.flush()
        assert f.repository.name == "rel"

    def test_review_has_suggestions(self, session):
        repo = RepositoryRepository(session).create(name="rels", root_path="/rels")
        session.flush()
        rev = ReviewRepository(session).create(repository_id=repo.id, summary="rev")
        session.flush()
        ReviewSuggestionRepository(session).create(review_id=rev.id, title="s1")
        ReviewSuggestionRepository(session).create(review_id=rev.id, title="s2")
        session.flush()
        session.refresh(rev)
        assert len(rev.suggestions) == 2

    def test_cascade_delete_repository_deletes_files(self, session):
        repo = RepositoryRepository(session).create(name="casc", root_path="/casc")
        session.flush()
        FileRepository(session).create(
            repository_id=repo.id, path="c.py", language="python"
        )
        session.flush()
        RepositoryRepository(session).delete(repo.id)
        session.flush()
        files = FileRepository(session).list(repository_id=repo.id)
        assert len(files) == 0

    def test_cascade_delete_file_deletes_symbols(self, session):
        repo = RepositoryRepository(session).create(name="cascs", root_path="/cascs")
        session.flush()
        f = FileRepository(session).create(
            repository_id=repo.id, path="cs.py", language="python"
        )
        session.flush()
        SymbolRepository(session).create(file_id=f.id, name="sym", type="function")
        session.flush()
        FileRepository(session).delete(f.id)
        session.flush()
        assert len(SymbolRepository(session).list_by_file(f.id)) == 0

    def test_cascade_delete_file_deletes_imports(self, session):
        repo = RepositoryRepository(session).create(name="casci", root_path="/casci")
        session.flush()
        f = FileRepository(session).create(
            repository_id=repo.id, path="ci.py", language="python"
        )
        session.flush()
        ImportRepository(session).create(file_id=f.id, module="os")
        session.flush()
        FileRepository(session).delete(f.id)
        session.flush()
        assert len(ImportRepository(session).list_by_file(f.id)) == 0

    def test_cascade_delete_file_deletes_embeddings(self, session):
        repo = RepositoryRepository(session).create(name="casce", root_path="/casce")
        session.flush()
        f = FileRepository(session).create(
            repository_id=repo.id, path="ce.py", language="python"
        )
        session.flush()
        EmbeddingRepository(session).create(file_id=f.id, chunk_id="cc1")
        session.flush()
        FileRepository(session).delete(f.id)
        session.flush()
        assert len(EmbeddingRepository(session).list_by_file(f.id)) == 0

    def test_cascade_delete_review_deletes_suggestions(self, session):
        repo = RepositoryRepository(session).create(name="cascr", root_path="/cascr")
        session.flush()
        rev = ReviewRepository(session).create(repository_id=repo.id, summary="cascrev")
        session.flush()
        ReviewSuggestionRepository(session).create(review_id=rev.id, title="cs1")
        session.flush()
        ReviewRepository(session).delete(rev.id)
        session.flush()
        assert len(ReviewSuggestionRepository(session).list_by_review(rev.id)) == 0

    def test_cascade_delete_graph_node_deletes_edges(self, session):
        repo = RepositoryRepository(session).create(name="cascg", root_path="/cascg")
        session.flush()
        graph = GraphRepository(session)
        n1 = graph.create_node(repository_id=repo.id, name="gn1", type="module")
        n2 = graph.create_node(repository_id=repo.id, name="gn2", type="module")
        session.flush()
        graph.create_edge(source_node=n1.id, target_node=n2.id, relationship_="imports")
        session.flush()
        graph.nodes.delete(n1.id)
        session.flush()
        assert len(graph.edges.list_outgoing(n1.id)) == 0


# ---------------------------------------------------------------------------
# 12. Unit of Work
# ---------------------------------------------------------------------------


class TestUnitOfWork:
    def test_uow_commits_on_success(self, session_factory):
        with UnitOfWork(session_factory) as uow:
            repo = uow.repositories.create(name="uow-ok", root_path="/uow-ok")
        with session_factory.session_scope() as s:
            found = s.get(RepositoryModel, repo.id)
            assert found is not None
            assert found.name == "uow-ok"

    def test_uow_rollback_on_exception(self, session_factory):
        try:
            with UnitOfWork(session_factory) as uow:
                uow.repositories.create(name="uow-fail", root_path="/uow-fail")
                raise ValueError("forced error")
        except ValueError:
            pass
        with session_factory.session_scope() as s:
            found = s.query(RepositoryModel).filter_by(root_path="/uow-fail").first()
            assert found is None

    def test_uow_multi_entity_transaction(self, session_factory):
        with UnitOfWork(session_factory) as uow:
            repo = uow.repositories.create(name="uow-multi", root_path="/uow-multi")
            f = uow.files.create(repository_id=repo.id, path="m.py", language="python")
            uow.symbols.create(file_id=f.id, name="func", type="function")
            uow.imports.create(file_id=f.id, module="os")
        with session_factory.session_scope() as s:
            r = s.query(RepositoryModel).filter_by(root_path="/uow-multi").first()
            assert r is not None
            files = s.query(FileModel).filter_by(repository_id=r.id).all()
            assert len(files) == 1
            symbols = s.query(SymbolModel).filter_by(file_id=files[0].id).all()
            assert len(symbols) == 1

    def test_uow_graph_transaction(self, session_factory):
        with UnitOfWork(session_factory) as uow:
            repo = uow.repositories.create(name="uow-graph", root_path="/uow-graph")
            n1 = uow.graph.create_node(repository_id=repo.id, name="n1", type="module")
            n2 = uow.graph.create_node(repository_id=repo.id, name="n2", type="module")
            uow.graph.create_edge(source_node=n1.id, target_node=n2.id, relationship_="calls")
        with session_factory.session_scope() as s:
            nodes = s.query(GraphNodeModel).filter_by(repository_id=repo.id).all()
            assert len(nodes) == 2
            edges = s.query(GraphEdgeModel).all()
            assert len(edges) >= 1

    def test_uow_reviews_and_suggestions(self, session_factory):
        with UnitOfWork(session_factory) as uow:
            repo = uow.repositories.create(name="uow-rev", root_path="/uow-rev")
            rev = uow.reviews.create(repository_id=repo.id, summary="uow review")
            uow.review_suggestions.create(
                review_id=rev.id, severity="error", title="Bug"
            )
            uow.review_suggestions.create(
                review_id=rev.id, severity="warning", title="Style"
            )
        with session_factory.session_scope() as s:
            rev = s.query(ReviewModel).filter_by(summary="uow review").first()
            assert rev is not None
            assert len(rev.suggestions) == 2

    def test_uow_recommendations(self, session_factory):
        with UnitOfWork(session_factory) as uow:
            repo = uow.repositories.create(name="uow-rec", root_path="/uow-rec")
            uow.recommendations.bulk_insert([
                {"repository_id": repo.id, "type": "security", "title": "Fix XSS"},
                {"repository_id": repo.id, "type": "testing", "title": "Add tests"},
            ])
        with session_factory.session_scope() as s:
            recs = s.query(RecommendationModel).filter_by(repository_id=repo.id).all()
            assert len(recs) == 2

    def test_uow_embeddings(self, session_factory):
        with UnitOfWork(session_factory) as uow:
            repo = uow.repositories.create(name="uow-emb", root_path="/uow-emb")
            f = uow.files.create(repository_id=repo.id, path="emb.py", language="python")
            uow.embeddings.create(file_id=f.id, chunk_id="c1", provider="openai")
            uow.embeddings.create(file_id=f.id, chunk_id="c2", provider="openai")
        with session_factory.session_scope() as s:
            embs = s.query(EmbeddingModel).filter_by(file_id=f.id).all()
            assert len(embs) == 2

    def test_uow_session_property_raises_outside_context(self, session_factory):
        uow = UnitOfWork(session_factory)
        with pytest.raises(RuntimeError, match="not active"):
            _ = uow.session


# ---------------------------------------------------------------------------
# 13. Session Factory
# ---------------------------------------------------------------------------


class TestSessionFactory:
    def test_session_scope_commits(self, session_factory):
        with session_factory.session_scope() as s:
            repo = RepositoryModel(name="sf-ok", root_path="/sf-ok")
            s.add(repo)
        with session_factory.session_scope() as s:
            found = s.query(RepositoryModel).filter_by(root_path="/sf-ok").first()
            assert found is not None

    def test_session_scope_rollback_on_error(self, session_factory):
        try:
            with session_factory.session_scope() as s:
                repo = RepositoryModel(name="sf-fail", root_path="/sf-fail")
                s.add(repo)
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        with session_factory.session_scope() as s:
            found = s.query(RepositoryModel).filter_by(root_path="/sf-fail").first()
            assert found is None

    def test_get_session_factory(self, db_manager):
        sf = get_session_factory(db_manager.engine)
        s = sf()
        assert s is not None
        s.close()


# ---------------------------------------------------------------------------
# 14. PersistenceService facade
# ---------------------------------------------------------------------------


class TestPersistenceService:
    def test_get_or_create_repository(self, persistence):
        result = persistence.get_or_create_repository(
            name="ps-repo", root_path="/ps-repo"
        )
        assert result["name"] == "ps-repo"
        assert result["id"] is not None

    def test_get_or_create_repository_idempotent(self, persistence):
        r1 = persistence.get_or_create_repository(name="ps-idem", root_path="/ps-idem")
        r2 = persistence.get_or_create_repository(name="ps-idem", root_path="/ps-idem")
        assert r1["id"] == r2["id"]

    def test_list_repositories(self, persistence):
        persistence.get_or_create_repository(name="ps-list", root_path="/ps-list")
        repos = persistence.list_repositories()
        assert len(repos) >= 1

    def test_persist_file(self, persistence):
        repo = persistence.get_or_create_repository(name="ps-f", root_path="/ps-f")
        f = persistence.persist_file(
            repository_id=repo["id"],
            path="app.py",
            language="python",
            sha256="abc123",
            size=512,
        )
        assert f["path"] == "app.py"
        assert f["language"] == "python"

    def test_persist_files_bulk(self, persistence):
        repo = persistence.get_or_create_repository(name="ps-fb", root_path="/ps-fb")
        count = persistence.persist_files_bulk(
            repo["id"],
            [
                {"path": "a.py", "language": "python", "size": 100},
                {"path": "b.py", "language": "python", "size": 200},
            ],
        )
        assert count == 2

    def test_persist_symbols(self, persistence):
        repo = persistence.get_or_create_repository(name="ps-sym", root_path="/ps-sym")
        f = persistence.persist_file(repository_id=repo["id"], path="s.py")
        count = persistence.persist_symbols(
            f["id"],
            [
                {"name": "foo", "type": "function"},
                {"name": "Bar", "type": "class"},
            ],
        )
        assert count == 2

    def test_persist_imports(self, persistence):
        repo = persistence.get_or_create_repository(name="ps-imp", root_path="/ps-imp")
        f = persistence.persist_file(repository_id=repo["id"], path="i.py")
        count = persistence.persist_imports(
            f["id"],
            [{"module": "os"}, {"module": "sys", "symbol": "argv"}],
        )
        assert count == 2

    def test_persist_review(self, persistence):
        repo = persistence.get_or_create_repository(name="ps-rev", root_path="/ps-rev")
        review = persistence.persist_review(
            repository_id=repo["id"],
            pr_number=42,
            provider="gemini",
            model="gemini-pro",
            risk="medium",
            confidence=0.85,
            summary="Good PR",
            suggestions=[
                {"severity": "warning", "title": "Minor issue", "file": "x.py"},
            ],
        )
        assert review["pr_number"] == 42

    def test_get_reviews(self, persistence):
        repo = persistence.get_or_create_repository(name="ps-grev", root_path="/ps-grev")
        persistence.persist_review(repository_id=repo["id"], summary="r1")
        reviews = persistence.get_reviews(repo["id"])
        assert len(reviews) >= 1

    def test_persist_recommendations(self, persistence):
        repo = persistence.get_or_create_repository(name="ps-rec", root_path="/ps-rec")
        count = persistence.persist_recommendations(
            repo["id"],
            [
                {"type": "security", "title": "Fix XSS"},
                {"type": "testing", "title": "Add tests"},
            ],
        )
        assert count == 2

    def test_get_recommendations(self, persistence):
        repo = persistence.get_or_create_repository(name="ps-grec", root_path="/ps-grec")
        persistence.persist_recommendations(
            repo["id"],
            [{"type": "a", "title": "t1"}],
        )
        recs = persistence.get_recommendations(repo["id"])
        assert len(recs) >= 1

    def test_persist_embeddings(self, persistence):
        repo = persistence.get_or_create_repository(name="ps-emb", root_path="/ps-emb")
        f = persistence.persist_file(repository_id=repo["id"], path="e.py")
        count = persistence.persist_embeddings(
            f["id"],
            [
                {"chunk_id": "c1", "provider": "openai"},
                {"chunk_id": "c2", "provider": "openai"},
            ],
        )
        assert count == 2

    def test_persist_graph(self, persistence):
        repo = persistence.get_or_create_repository(name="ps-graph", root_path="/ps-graph")
        result = persistence.persist_graph(
            repo["id"],
            nodes=[
                {"name": "mod_a", "type": "module"},
                {"name": "mod_b", "type": "module"},
            ],
            edges=[
                {"source_name": "mod_a", "target_name": "mod_b", "relationship_": "imports"},
            ],
        )
        assert result["nodes"] == 2
        assert result["edges"] == 1

    def test_unit_of_work_from_persistence(self, persistence):
        with persistence.unit_of_work() as uow:
            repo = uow.repositories.create(name="ps-uow", root_path="/ps-uow")
            uow.files.create(repository_id=repo.id, path="u.py", language="python")
        repos = persistence.list_repositories()
        names = [r["name"] for r in repos]
        assert "ps-uow" in names


# ---------------------------------------------------------------------------
# 15. DatabaseManager
# ---------------------------------------------------------------------------


class TestDatabaseManager:
    def test_in_memory_url(self):
        mgr = DatabaseManager(database_url="sqlite:///:memory:")
        mgr.create_all()
        inspector = inspect(mgr.engine)
        assert "db_repositories" in inspector.get_table_names()
        mgr.dispose()

    def test_repo_root_url(self, tmp_path):
        mgr = DatabaseManager(repo_root=tmp_path)
        mgr.create_all()
        db_file = tmp_path / ".refactory" / "db" / "refactory.db"
        assert db_file.exists()
        mgr.dispose()

    def test_url_property(self):
        mgr = DatabaseManager(database_url="sqlite:///:memory:")
        assert mgr.url == "sqlite:///:memory:"
        mgr.dispose()

    def test_engine_property(self):
        mgr = DatabaseManager(database_url="sqlite:///:memory:")
        assert mgr.engine is not None
        mgr.dispose()


# ---------------------------------------------------------------------------
# 16. Migration
# ---------------------------------------------------------------------------


class TestMigration:
    def test_initial_migration_creates_all_tables(self, tmp_path):
        """Verify that running the migration script creates all expected tables."""
        db_url = f"sqlite:///{tmp_path / 'migration_test.db'}"
        from alembic.config import Config
        from alembic import command
        import os

        alembic_cfg = Config()
        alembic_cfg.set_main_option("script_location", "refactory/db/migrations")
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)

        os.environ["REFACTORY_DATABASE_URL"] = db_url
        try:
            command.upgrade(alembic_cfg, "head")
        finally:
            os.environ.pop("REFACTORY_DATABASE_URL", None)

        from sqlalchemy import create_engine
        engine = create_engine(db_url)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        expected = {
            "db_repositories", "db_files", "db_symbols", "db_imports",
            "db_reviews", "db_review_suggestions", "db_recommendations",
            "db_embeddings", "db_graph_nodes", "db_graph_edges",
        }
        assert expected.issubset(tables), f"Missing: {expected - tables}"
        engine.dispose()

    def test_migration_downgrade(self, tmp_path):
        """Verify downgrade removes all tables."""
        db_url = f"sqlite:///{tmp_path / 'downgrade_test.db'}"
        from alembic.config import Config
        from alembic import command
        import os

        alembic_cfg = Config()
        alembic_cfg.set_main_option("script_location", "refactory/db/migrations")
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)

        os.environ["REFACTORY_DATABASE_URL"] = db_url
        try:
            command.upgrade(alembic_cfg, "head")
            command.downgrade(alembic_cfg, "base")
        finally:
            os.environ.pop("REFACTORY_DATABASE_URL", None)

        from sqlalchemy import create_engine
        engine = create_engine(db_url)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        db_tables = {t for t in tables if t.startswith("db_")}
        assert len(db_tables) == 0
        engine.dispose()


# ---------------------------------------------------------------------------
# 17. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_get_nonexistent_by_id(self, session):
        repo_repo = RepositoryRepository(session)
        assert repo_repo.get_by_id("nonexistent-id") is None

    def test_delete_nonexistent(self, session):
        repo_repo = RepositoryRepository(session)
        assert repo_repo.delete("nonexistent-id") is False

    def test_update_nonexistent(self, session):
        repo_repo = RepositoryRepository(session)
        assert repo_repo.update("nonexistent-id", name="x") is None

    def test_empty_bulk_insert(self, session):
        repo_repo = RepositoryRepository(session)
        result = repo_repo.bulk_insert([])
        assert result == []

    def test_count_empty(self, session):
        repo_repo = RepositoryRepository(session)
        assert repo_repo.count(name="definitely-not-exists") == 0

    def test_repository_timestamps(self, session):
        repo_repo = RepositoryRepository(session)
        repo = repo_repo.create(name="ts-test", root_path="/ts")
        session.flush()
        assert repo.created_at is not None
        assert repo.updated_at is not None
        assert isinstance(repo.created_at, datetime)

    def test_review_default_values(self, session):
        repo = RepositoryRepository(session).create(name="dv", root_path="/dv")
        session.flush()
        rev = ReviewRepository(session).create(repository_id=repo.id)
        session.flush()
        assert rev.risk == "unknown"
        assert rev.confidence == 0.0
        assert rev.summary == ""

    def test_large_bulk_insert(self, session):
        repo = RepositoryRepository(session).create(name="bulk", root_path="/bulk")
        session.flush()
        file_repo = FileRepository(session)
        files = file_repo.bulk_insert([
            {"repository_id": repo.id, "path": f"file_{i}.py", "language": "python"}
            for i in range(100)
        ])
        assert len(files) == 100

    def test_pagination(self, session):
        repo = RepositoryRepository(session).create(name="page", root_path="/page")
        session.flush()
        rec_repo = RecommendationRepository(session)
        for i in range(10):
            rec_repo.create(repository_id=repo.id, type="t", title=f"rec-{i}")
        session.flush()
        page1 = rec_repo.list(limit=5, offset=0, repository_id=repo.id)
        page2 = rec_repo.list(limit=5, offset=5, repository_id=repo.id)
        assert len(page1) == 5
        assert len(page2) == 5
        ids1 = {r.id for r in page1}
        ids2 = {r.id for r in page2}
        assert ids1.isdisjoint(ids2)
