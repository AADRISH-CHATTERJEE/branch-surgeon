"""Repository pattern implementation for GraphNode and GraphEdge entities."""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select

from refactory.db.models import GraphEdgeModel, GraphNodeModel
from refactory.db.repositories.base import BaseRepository


class GraphNodeRepository(BaseRepository[GraphNodeModel]):
    """CRUD operations for graph nodes."""

    model_class = GraphNodeModel

    def list_by_repository(
        self, repository_id: str, *, node_type: str | None = None, limit: int = 1000
    ) -> Sequence[GraphNodeModel]:
        """List nodes in a repository, optionally filtered by type."""
        stmt = select(GraphNodeModel).where(GraphNodeModel.repository_id == repository_id)
        if node_type:
            stmt = stmt.where(GraphNodeModel.type == node_type)
        stmt = stmt.limit(limit)
        return self._session.execute(stmt).scalars().all()

    def find_by_name(self, repository_id: str, name: str) -> Sequence[GraphNodeModel]:
        """Find nodes by name within a repository."""
        stmt = select(GraphNodeModel).where(
            GraphNodeModel.repository_id == repository_id,
            GraphNodeModel.name == name,
        )
        return self._session.execute(stmt).scalars().all()

    def delete_by_repository(self, repository_id: str) -> int:
        """Delete all nodes (and cascade edges) for a repository."""
        nodes = self.list_by_repository(repository_id, limit=100000)
        count = len(nodes)
        for n in nodes:
            self._session.delete(n)
        self._session.flush()
        return count


class GraphEdgeRepository(BaseRepository[GraphEdgeModel]):
    """CRUD operations for graph edges."""

    model_class = GraphEdgeModel

    def list_outgoing(self, node_id: str) -> Sequence[GraphEdgeModel]:
        """List edges originating from a node."""
        stmt = select(GraphEdgeModel).where(GraphEdgeModel.source_node == node_id)
        return self._session.execute(stmt).scalars().all()

    def list_incoming(self, node_id: str) -> Sequence[GraphEdgeModel]:
        """List edges pointing to a node."""
        stmt = select(GraphEdgeModel).where(GraphEdgeModel.target_node == node_id)
        return self._session.execute(stmt).scalars().all()

    def find_by_relationship(self, relationship: str) -> Sequence[GraphEdgeModel]:
        """Find edges by relationship type."""
        stmt = select(GraphEdgeModel).where(GraphEdgeModel.relationship_ == relationship)
        return self._session.execute(stmt).scalars().all()


class GraphRepository:
    """Composite repository for graph nodes and edges."""

    def __init__(self, session) -> None:
        self.nodes = GraphNodeRepository(session)
        self.edges = GraphEdgeRepository(session)
        self._session = session

    def create_node(self, **kwargs) -> GraphNodeModel:
        return self.nodes.create(**kwargs)

    def create_edge(self, **kwargs) -> GraphEdgeModel:
        return self.edges.create(**kwargs)

    def get_node_by_id(self, node_id: str) -> GraphNodeModel | None:
        return self.nodes.get_by_id(node_id)

    def get_edge_by_id(self, edge_id: str) -> GraphEdgeModel | None:
        return self.edges.get_by_id(edge_id)

    def list_nodes(self, repository_id: str, **kwargs) -> Sequence[GraphNodeModel]:
        return self.nodes.list_by_repository(repository_id, **kwargs)

    def list_edges_outgoing(self, node_id: str) -> Sequence[GraphEdgeModel]:
        return self.edges.list_outgoing(node_id)

    def list_edges_incoming(self, node_id: str) -> Sequence[GraphEdgeModel]:
        return self.edges.list_incoming(node_id)

    def delete_graph(self, repository_id: str) -> int:
        """Delete all graph data for a repository."""
        return self.nodes.delete_by_repository(repository_id)

    def bulk_insert_nodes(self, nodes: list[dict]) -> list[GraphNodeModel]:
        return self.nodes.bulk_insert(nodes)

    def bulk_insert_edges(self, edges: list[dict]) -> list[GraphEdgeModel]:
        return self.edges.bulk_insert(edges)
