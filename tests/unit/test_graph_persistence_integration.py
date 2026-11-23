"""Integration test: graph persistence through real ORM path.

Verifies that RepositoryGraphService._persist_to_db correctly writes
nodes and edges to the database via PersistenceService, catching
field-name mismatches that unit tests with mocked persistence miss.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from refactory.db.base import Base
from refactory.db.models import GraphEdgeModel, GraphNodeModel, RepositoryModel
from refactory.db.persistence import PersistenceService
from refactory.db.session import SessionFactory


@pytest.fixture()
def engine():
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session_factory(engine):
    return SessionFactory(engine)


@pytest.fixture()
def persistence(session_factory) -> PersistenceService:
    return PersistenceService(session_factory)


@pytest.fixture()
def repo_id(session_factory) -> str:
    sess = session_factory()
    repo = RepositoryModel(
        id=uuid.uuid4().hex[:36],
        name="test-repo",
        root_path="/tmp/graph-test",
        default_branch="main",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    sess.add(repo)
    sess.commit()
    rid = repo.id
    sess.close()
    return rid


class TestGraphPersistenceIntegration:
    """Exercises the real ORM path that RepositoryGraphService uses."""

    def test_persist_graph_with_relationship_field(self, persistence, repo_id):
        """The critical regression test: 'relationship' must map to 'relationship_' on ORM."""
        nodes = [
            {"name": "module_a", "type": "module"},
            {"name": "module_b", "type": "module"},
            {"name": "ClassFoo", "type": "class"},
        ]
        edges = [
            {"source_name": "module_a", "target_name": "module_b", "relationship": "imports"},
            {"source_name": "module_a", "target_name": "ClassFoo", "relationship": "defines"},
        ]
        result = persistence.persist_graph(repo_id, nodes=nodes, edges=edges)
        assert result == {"nodes": 3, "edges": 2}

    def test_persist_graph_nodes_in_db(self, persistence, repo_id, session_factory):
        nodes = [
            {"name": "service.py", "type": "module"},
            {"name": "UserService", "type": "class"},
        ]
        edges = [
            {"source_name": "service.py", "target_name": "UserService", "relationship": "defines"},
        ]
        persistence.persist_graph(repo_id, nodes=nodes, edges=edges)

        sess = session_factory()
        db_nodes = sess.query(GraphNodeModel).filter_by(repository_id=repo_id).all()
        assert len(db_nodes) == 2
        names = {n.name for n in db_nodes}
        assert names == {"service.py", "UserService"}
        sess.close()

    def test_persist_graph_edges_in_db(self, persistence, repo_id, session_factory):
        nodes = [
            {"name": "auth.py", "type": "module"},
            {"name": "db.py", "type": "module"},
        ]
        edges = [
            {"source_name": "auth.py", "target_name": "db.py", "relationship": "imports"},
        ]
        persistence.persist_graph(repo_id, nodes=nodes, edges=edges)

        sess = session_factory()
        db_edges = sess.query(GraphEdgeModel).all()
        assert len(db_edges) == 1
        assert db_edges[0].relationship_ == "imports"
        sess.close()

    def test_persist_graph_edge_relationship_values(self, persistence, repo_id, session_factory):
        """Verify various relationship types persist correctly."""
        nodes = [
            {"name": "A", "type": "module"},
            {"name": "B", "type": "class"},
            {"name": "C", "type": "function"},
        ]
        edges = [
            {"source_name": "A", "target_name": "B", "relationship": "defines"},
            {"source_name": "B", "target_name": "C", "relationship": "calls"},
            {"source_name": "A", "target_name": "C", "relationship": "imports"},
        ]
        persistence.persist_graph(repo_id, nodes=nodes, edges=edges)

        sess = session_factory()
        db_edges = sess.query(GraphEdgeModel).all()
        rels = {e.relationship_ for e in db_edges}
        assert rels == {"defines", "calls", "imports"}
        sess.close()

    def test_persist_graph_replaces_previous(self, persistence, repo_id, session_factory):
        """Re-persisting a graph deletes old data first."""
        nodes = [{"name": "old_node", "type": "module"}]
        persistence.persist_graph(repo_id, nodes=nodes, edges=[])

        new_nodes = [
            {"name": "new_a", "type": "module"},
            {"name": "new_b", "type": "module"},
        ]
        new_edges = [
            {"source_name": "new_a", "target_name": "new_b", "relationship": "imports"},
        ]
        persistence.persist_graph(repo_id, nodes=new_nodes, edges=new_edges)

        sess = session_factory()
        db_nodes = sess.query(GraphNodeModel).filter_by(repository_id=repo_id).all()
        db_edges = sess.query(GraphEdgeModel).all()
        assert len(db_nodes) == 2
        assert len(db_edges) == 1
        assert {n.name for n in db_nodes} == {"new_a", "new_b"}
        sess.close()

    def test_persist_graph_with_relationship_underscore_passthrough(self, persistence, repo_id):
        """If caller already uses 'relationship_', it should pass through without error."""
        nodes = [
            {"name": "X", "type": "module"},
            {"name": "Y", "type": "module"},
        ]
        edges = [
            {"source_name": "X", "target_name": "Y", "relationship_": "calls"},
        ]
        result = persistence.persist_graph(repo_id, nodes=nodes, edges=edges)
        assert result == {"nodes": 2, "edges": 1}

    def test_full_graph_service_dict_format(self, persistence, repo_id, session_factory):
        """Simulate the exact dict format that RepositoryGraphService._persist_to_db produces."""
        nodes = [
            {"name": "refactory.parser.service", "type": "module"},
            {"name": "refactory.indexer.service", "type": "module"},
            {"name": "ParserService", "type": "class"},
            {"name": "IndexerService", "type": "class"},
        ]
        edges = [
            {"source_name": "refactory.indexer.service", "target_name": "refactory.parser.service", "relationship": "imports"},
            {"source_name": "refactory.parser.service", "target_name": "ParserService", "relationship": "defines"},
            {"source_name": "refactory.indexer.service", "target_name": "IndexerService", "relationship": "defines"},
            {"source_name": "IndexerService", "target_name": "ParserService", "relationship": "calls"},
        ]
        persistence.persist_graph(repo_id, nodes=nodes, edges=edges)

        sess = session_factory()
        db_nodes = sess.query(GraphNodeModel).filter_by(repository_id=repo_id).all()
        db_edges = sess.query(GraphEdgeModel).all()
        assert len(db_nodes) == 4
        assert len(db_edges) == 4
        sess.close()

    def test_empty_graph(self, persistence, repo_id, session_factory):
        """Empty graph should succeed without errors."""
        result = persistence.persist_graph(repo_id, nodes=[], edges=[])
        assert result == {"nodes": 0, "edges": 0}

        sess = session_factory()
        assert sess.query(GraphNodeModel).filter_by(repository_id=repo_id).count() == 0
        assert sess.query(GraphEdgeModel).count() == 0
        sess.close()
