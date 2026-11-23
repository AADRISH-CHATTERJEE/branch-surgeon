"""POST /graph, GET /graph, GET /graph/full, GET /graph/nodes/{node_id}."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from refactory.api.deps import ContainerDep, RepoRootDep
from refactory.api.routes._helpers import not_found, resolve_repository_record
from refactory.api.schemas import ApiResponse, GraphBuildRequest, ok
from refactory.api.serialize import to_data

router = APIRouter(prefix="/graph", tags=["graph"])


def _ensure_index(container, root: Path, name: str):
    existing = container.indexer_service.load_index(root)
    if existing is not None:
        return existing
    return container.indexer_service.build_index(root, repository_name=name)


@router.post(
    "",
    response_model=ApiResponse,
    summary="Build (or rebuild) the repository graph",
    description="Delegates to RepositoryGraphService.build_graph.",
)
def build_graph(
    body: GraphBuildRequest,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse:
    from refactory.api.routes._activity import persist_repo_activity
    from refactory.history.helpers import timed

    meta = container.git_service.get_repository_metadata()
    root = Path(meta.root_path)
    with timed() as t:
        index = _ensure_index(container, root, meta.name)
        graph = container.graph_service.build_graph(index, force=body.force)
    stats = graph.statistics if hasattr(graph, "statistics") else None
    nodes = getattr(stats, "total_nodes", None) if stats else None
    edges = getattr(stats, "total_edges", None) if stats else None
    payload = {
        "nodes": nodes,
        "edges": edges,
        "statistics": to_data(stats) if stats else None,
        "force": body.force,
    }
    persist_repo_activity(
        container,
        command="graph",
        result_type="repository_graph",
        summary=f"Graph: {nodes or 0} nodes, {edges or 0} edges",
        duration_ms=t.duration_ms,
        result_data=payload,
    )
    return ok(
        payload,
        message="Graph built",
        meta={"repo_root": str(repo_root)},
    )


@router.get(
    "",
    response_model=ApiResponse,
    summary="Get current repository graph summary",
    description="Builds from cached index/graph when available (force=False).",
)
def get_graph(container: ContainerDep, repo_root: RepoRootDep) -> ApiResponse:
    meta = container.git_service.get_repository_metadata()
    root = Path(meta.root_path)
    index = _ensure_index(container, root, meta.name)
    graph = container.graph_service.build_graph(index, force=False)
    stats = graph.statistics if hasattr(graph, "statistics") else None
    return ok(
        {
            "nodes": getattr(stats, "total_nodes", None) if stats else None,
            "edges": getattr(stats, "total_edges", None) if stats else None,
            "statistics": to_data(stats) if stats else None,
        },
        meta={"repo_root": str(repo_root)},
    )


@router.get(
    "/full",
    response_model=ApiResponse,
    summary="Get persisted graph nodes and edges",
    description="Thin read over RepositoryQueryService.get_graph (no rebuild).",
    responses={404: {"model": ApiResponse}},
)
def get_graph_full(container: ContainerDep, repo_root: RepoRootDep):
    repo = resolve_repository_record(container)
    if repo is None:
        return not_found("Not found", "Repository not found in persistence DB")
    data = container.query_service.get_graph(repo["id"])
    return ok(data, meta={"repo_root": str(repo_root)})


@router.get(
    "/nodes/{node_id}",
    response_model=ApiResponse,
    summary="Get a graph node with adjacent edges",
    description="Thin read over RepositoryQueryService.get_graph_node.",
    responses={404: {"model": ApiResponse}},
)
def get_graph_node(node_id: str, container: ContainerDep, repo_root: RepoRootDep):
    repo = resolve_repository_record(container)
    if repo is None:
        return not_found("Not found", "Repository not found in persistence DB")
    node = container.query_service.get_graph_node(node_id)
    if node is None:
        return not_found("Not found", f"Graph node '{node_id}' not found")
    if str(node.get("repository_id") or "") != str(repo["id"]):
        return not_found(
            "Not found",
            f"Graph node '{node_id}' does not belong to the configured repository",
        )
    return ok(node, meta={"repo_root": str(repo_root)})
