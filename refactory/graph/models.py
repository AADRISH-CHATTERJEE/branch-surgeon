"""Typed models for the deterministic repository knowledge graph."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RelationshipType(str, Enum):
    FILE_CONTAINS_MODULE = "FILE_CONTAINS_MODULE"
    MODULE_CONTAINS_CLASS = "MODULE_CONTAINS_CLASS"
    MODULE_CONTAINS_FUNCTION = "MODULE_CONTAINS_FUNCTION"
    CLASS_CONTAINS_METHOD = "CLASS_CONTAINS_METHOD"
    MODULE_IMPORTS_MODULE = "MODULE_IMPORTS_MODULE"
    FUNCTION_DEFINED_IN_FILE = "FUNCTION_DEFINED_IN_FILE"
    CLASS_DEFINED_IN_FILE = "CLASS_DEFINED_IN_FILE"
    FUNCTION_DEFINED_IN_MODULE = "FUNCTION_DEFINED_IN_MODULE"
    CLASS_DEFINED_IN_MODULE = "CLASS_DEFINED_IN_MODULE"
    FILE_IMPORTS_FILE = "FILE_IMPORTS_FILE"
    SYMBOL_DEFINED_IN_FILE = "SYMBOL_DEFINED_IN_FILE"
    SYMBOL_DEFINED_IN_MODULE = "SYMBOL_DEFINED_IN_MODULE"
    PARENT_FUNCTION = "PARENT_FUNCTION"
    NESTED_FUNCTION = "NESTED_FUNCTION"
    REFERENCES_SYMBOL = "REFERENCES_SYMBOL"
    CALLS = "CALLS"
    INHERITS_FROM = "INHERITS_FROM"
    MODULE_CHILD_OF = "MODULE_CHILD_OF"


class NodeKind(str, Enum):
    FILE = "file"
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    NESTED_FUNCTION = "nested_function"
    PACKAGE = "package"


class Node(BaseModel):
    """Base graph node."""

    id: str
    kind: NodeKind
    name: str
    file_path: str | None = None
    module_name: str | None = None
    parent_id: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    decorators: list[str] = Field(default_factory=list)
    is_async: bool = False
    is_generator: bool = False


class FileNode(Node):
    language: str = ""
    content_hash: str = ""
    import_count: int = 0
    symbol_count: int = 0
    ownership: str = ""
    business_domain: str = ""
    is_entry_point: bool = False
    is_external_api: bool = False
    service_name: str = ""


class ModuleNode(Node):
    pass


class PackageNode(Node):
    """Directory / package hierarchy node (deterministic from file paths)."""

    pass


class ClassNode(Node):
    bases: list[str] = Field(default_factory=list)


class FunctionNode(Node):
    """Top-level function, method, or nested function."""

    pass


class Edge(BaseModel):
    """Base directed edge."""

    id: str
    source_id: str
    target_id: str
    relationship: RelationshipType


class ImportEdge(Edge):
    imported_symbol: str | None = None
    target_module: str | None = None


class DefinitionEdge(Edge):
    pass


class ReferenceEdge(Edge):
    symbol_name: str | None = None


class DependencyEdge(Edge):
    pass


class CallEdge(Edge):
    """Call relationship from import evidence or AST call sites."""

    callee_name: str | None = None


class InheritanceEdge(Edge):
    base_name: str | None = None


class GraphStatistics(BaseModel):
    """Aggregate counts for the constructed graph."""

    files: int = 0
    modules: int = 0
    packages: int = 0
    classes: int = 0
    functions: int = 0
    methods: int = 0
    nested_functions: int = 0
    import_edges: int = 0
    definition_edges: int = 0
    dependency_edges: int = 0
    reference_edges: int = 0
    call_edges: int = 0
    inheritance_edges: int = 0
    hierarchy_edges: int = 0
    total_nodes: int = 0
    total_edges: int = 0
    average_imports_per_file: float = 0.0
    average_symbols_per_file: float = 0.0
    cyclic_dependency_count: int = 0
    orphan_module_count: int = 0
    unused_symbol_count: int = 0


class SymbolMatch(BaseModel):
    """A symbol table hit with enough context for CLI / impact queries."""

    name: str
    kind: NodeKind
    node_id: str
    file_path: str | None = None
    module_name: str | None = None
    parent_name: str | None = None
    start_line: int | None = None
    end_line: int | None = None


class DependencyCycle(BaseModel):
    """One strongly connected component of file-level imports (size >= 2)."""

    files: list[str] = Field(default_factory=list)


class OrphanModule(BaseModel):
    """Module/file with no inbound or outbound import edges."""

    module_name: str
    file_path: str


class UnusedSymbol(BaseModel):
    """Defined symbol with no REFERENCES_SYMBOL / CALLS / INHERITS inbound edges."""

    name: str
    kind: NodeKind
    file_path: str | None = None
    node_id: str


class DeadCodeCandidate(BaseModel):
    """Heuristic dead-code hint (unused + not entrypoint-like)."""

    name: str
    kind: NodeKind
    file_path: str | None = None
    reason: str


_NODE_BY_KIND: dict[NodeKind, type[Node]] = {
    NodeKind.FILE: FileNode,
    NodeKind.MODULE: ModuleNode,
    NodeKind.PACKAGE: PackageNode,
    NodeKind.CLASS: ClassNode,
    NodeKind.FUNCTION: FunctionNode,
    NodeKind.METHOD: FunctionNode,
    NodeKind.NESTED_FUNCTION: FunctionNode,
}

_EDGE_BY_RELATIONSHIP: dict[RelationshipType, type[Edge]] = {
    RelationshipType.MODULE_IMPORTS_MODULE: ImportEdge,
    RelationshipType.FILE_IMPORTS_FILE: ImportEdge,
    RelationshipType.REFERENCES_SYMBOL: ReferenceEdge,
    RelationshipType.CALLS: CallEdge,
    RelationshipType.INHERITS_FROM: InheritanceEdge,
    RelationshipType.FILE_CONTAINS_MODULE: DefinitionEdge,
    RelationshipType.MODULE_CONTAINS_CLASS: DefinitionEdge,
    RelationshipType.MODULE_CONTAINS_FUNCTION: DefinitionEdge,
    RelationshipType.CLASS_CONTAINS_METHOD: DefinitionEdge,
    RelationshipType.FUNCTION_DEFINED_IN_FILE: DefinitionEdge,
    RelationshipType.CLASS_DEFINED_IN_FILE: DefinitionEdge,
    RelationshipType.FUNCTION_DEFINED_IN_MODULE: DefinitionEdge,
    RelationshipType.CLASS_DEFINED_IN_MODULE: DefinitionEdge,
    RelationshipType.SYMBOL_DEFINED_IN_FILE: DefinitionEdge,
    RelationshipType.SYMBOL_DEFINED_IN_MODULE: DefinitionEdge,
    RelationshipType.PARENT_FUNCTION: DefinitionEdge,
    RelationshipType.NESTED_FUNCTION: DefinitionEdge,
    RelationshipType.MODULE_CHILD_OF: DefinitionEdge,
}


def _coerce_kind(value: Any) -> NodeKind | None:
    if isinstance(value, NodeKind):
        return value
    if value is None:
        return None
    try:
        return NodeKind(str(value))
    except ValueError:
        return None


def _coerce_relationship(value: Any) -> RelationshipType | None:
    if isinstance(value, RelationshipType):
        return value
    if value is None:
        return None
    try:
        return RelationshipType(str(value))
    except ValueError:
        return None


def _rehydrate_node(payload: Any) -> Node:
    if isinstance(payload, Node) and type(payload) is not Node:
        return payload
    data = payload.model_dump(mode="python") if isinstance(payload, Node) else dict(payload)
    kind = _coerce_kind(data.get("kind"))
    cls = _NODE_BY_KIND.get(kind or NodeKind.FILE, Node)
    return cls.model_validate(data)


def _rehydrate_edge(payload: Any) -> Edge:
    if isinstance(payload, Edge) and type(payload) is not Edge:
        return payload
    data = payload.model_dump(mode="python") if isinstance(payload, Edge) else dict(payload)
    rel = _coerce_relationship(data.get("relationship"))
    cls = _EDGE_BY_RELATIONSHIP.get(rel or RelationshipType.FILE_IMPORTS_FILE, Edge)
    return cls.model_validate(data)


class RepositoryGraph(BaseModel):
    """In-memory knowledge graph derived from a RepositoryIndex."""

    repository_name: str
    repository_root: str
    nodes: dict[str, Node] = Field(default_factory=dict)
    edges: list[Edge] = Field(default_factory=list)
    statistics: GraphStatistics = Field(default_factory=GraphStatistics)
    symbol_table: dict[str, list[str]] = Field(default_factory=dict)
    module_index: dict[str, str] = Field(default_factory=dict)
    file_index: dict[str, str] = Field(default_factory=dict)
    package_index: dict[str, str] = Field(default_factory=dict)

    @field_validator("nodes", mode="before")
    @classmethod
    def _rehydrate_nodes(cls, value: Any) -> dict[str, Node]:
        if not isinstance(value, dict):
            return value
        return {str(key): _rehydrate_node(node) for key, node in value.items()}

    @field_validator("edges", mode="before")
    @classmethod
    def _rehydrate_edges(cls, value: Any) -> list[Edge]:
        if not isinstance(value, list):
            return value
        return [_rehydrate_edge(edge) for edge in value]
