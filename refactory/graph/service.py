"""RepositoryGraphService — deterministic knowledge graph from RepositoryIndex.

Depends only on RepositoryIndex data. No embeddings, AI, or I/O beyond what
the caller supplies.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import TYPE_CHECKING

from refactory.cache.keys import file_hashes_digest, graph_cache_key
from refactory.cache.store import CacheStore, NullCache
from refactory.core.exceptions import IndexError_
from refactory.core.logger import bind_context
from refactory.graph.models import (
    CallEdge,
    ClassNode,
    DeadCodeCandidate,
    DefinitionEdge,
    DependencyCycle,
    DependencyEdge,
    Edge,
    FileNode,
    FunctionNode,
    GraphStatistics,
    ImportEdge,
    InheritanceEdge,
    ModuleNode,
    Node,
    NodeKind,
    OrphanModule,
    PackageNode,
    ReferenceEdge,
    RelationshipType,
    RepositoryGraph,
    SymbolMatch,
    UnusedSymbol,
)
from refactory.indexer.models import IndexedFile, IndexedSymbol, RepositoryIndex, SymbolKind

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.db.persistence import PersistenceService


class RepositoryGraphService:
    """Build and query a repository knowledge graph from an index."""

    def __init__(
        self,
        logger: "Logger",
        *,
        cache: CacheStore | None = None,
        persistence_service: "PersistenceService | None" = None,
    ) -> None:
        self._logger = logger
        self._cache: CacheStore = cache or NullCache()
        self._graph: RepositoryGraph | None = None
        self._persistence = persistence_service

    # ------------------------------------------------------------------
    # Build / access
    # ------------------------------------------------------------------

    def build_graph(self, index: RepositoryIndex, *, force: bool = False) -> RepositoryGraph:
        """Transform a RepositoryIndex into a fully connected RepositoryGraph."""
        repo_hash = file_hashes_digest(index.file_hashes)
        cache_key = graph_cache_key(
            repository_hash=repo_hash,
            index_name=index.summary.repository_name,
        )
        if not force:
            cached = self._cache.get(cache_key)
            if isinstance(cached, dict):
                graph = RepositoryGraph.model_validate(cached)
                self._graph = graph
                bind_context(
                    self._logger,
                    repository=graph.repository_name,
                    cache="hit",
                ).info(
                    "Reused cached repository graph — nodes={}, edges={}",
                    graph.statistics.total_nodes,
                    graph.statistics.total_edges,
                )
                return graph

        graph = RepositoryGraph(
            repository_name=index.summary.repository_name,
            repository_root=index.summary.repository_root,
        )

        module_by_name: dict[str, str] = {}
        file_by_path: dict[str, str] = {}
        # module_name -> file relative path (first wins; stems collide by design)
        module_to_file: dict[str, str] = {}
        # (file_path, symbol_name, kind) -> node id for definition lookup
        symbol_nodes: dict[tuple[str, str, str], str] = {}

        for indexed in index.files:
            file_id = self._file_id(indexed.relative_path)
            module_id = self._module_id(indexed.module_name, indexed.relative_path)

            file_node = FileNode(
                id=file_id,
                kind=NodeKind.FILE,
                name=indexed.relative_path,
                file_path=indexed.relative_path,
                module_name=indexed.module_name,
                language=indexed.language,
                content_hash=indexed.content_hash,
                import_count=len(indexed.import_references),
                symbol_count=len(
                    [s for s in indexed.symbols if s.kind != SymbolKind.MODULE]
                ),
            )
            module_node = ModuleNode(
                id=module_id,
                kind=NodeKind.MODULE,
                name=indexed.module_name,
                file_path=indexed.relative_path,
                module_name=indexed.module_name,
            )
            graph.nodes[file_id] = file_node
            graph.nodes[module_id] = module_node
            file_by_path[self._norm_path(indexed.relative_path)] = file_id
            module_by_name[indexed.module_name] = module_id
            module_to_file.setdefault(indexed.module_name, indexed.relative_path)
            graph.file_index[self._norm_path(indexed.relative_path)] = file_id
            graph.module_index[indexed.module_name] = module_id

            self._add_edge(
                graph,
                DefinitionEdge(
                    id=self._edge_id(
                        RelationshipType.FILE_CONTAINS_MODULE, file_id, module_id
                    ),
                    source_id=file_id,
                    target_id=module_id,
                    relationship=RelationshipType.FILE_CONTAINS_MODULE,
                ),
            )

            self._add_symbols_for_file(
                graph,
                indexed,
                file_id=file_id,
                module_id=module_id,
                symbol_nodes=symbol_nodes,
            )

        self._add_import_edges(
            graph,
            index,
            file_by_path=file_by_path,
            module_by_name=module_by_name,
            module_to_file=module_to_file,
            symbol_nodes=symbol_nodes,
        )
        self._add_call_site_edges(graph, index, file_by_path=file_by_path)
        self._add_inheritance_edges(graph, index)
        self._add_module_hierarchy(graph, index)

        graph.statistics = self._compute_statistics(graph)
        self._graph = graph
        self._cache.set(cache_key, graph.model_dump(mode="json"))
        bind_context(
            self._logger,
            repository=graph.repository_name,
            cache="miss",
        ).info(
            "Built repository graph — nodes={}, edges={}, cycles={}, orphans={}, unused={}",
            graph.statistics.total_nodes,
            graph.statistics.total_edges,
            graph.statistics.cyclic_dependency_count,
            graph.statistics.orphan_module_count,
            graph.statistics.unused_symbol_count,
        )

        self._persist_to_db(graph)

        return graph

    def update_graph(self, index: RepositoryIndex) -> RepositoryGraph:
        """Incrementally update the graph: only rebuild nodes for changed files.

        If no prior graph exists, falls back to a full build.
        Detects changed files via content_hash, updates only affected nodes
        and edges, and preserves the graph cache for unchanged portions.
        """
        if self._graph is None:
            return self.build_graph(index)

        old_graph = self._graph
        current_hashes: dict[str, str] = {}
        for f in index.files:
            current_hashes[self._norm_path(f.relative_path)] = f.content_hash

        old_hashes: dict[str, str] = {}
        for node in old_graph.nodes.values():
            if isinstance(node, FileNode) and node.content_hash:
                old_hashes[self._norm_path(node.file_path)] = node.content_hash

        changed: set[str] = set()
        added: set[str] = set()
        deleted: set[str] = set()

        for path, h in current_hashes.items():
            if path not in old_hashes:
                added.add(path)
            elif old_hashes[path] != h:
                changed.add(path)
        for path in old_hashes:
            if path not in current_hashes:
                deleted.add(path)

        affected = changed | added | deleted
        if not affected:
            self._logger.debug("Incremental graph update: no changes detected")
            return old_graph

        if len(affected) > len(current_hashes) * 0.5:
            self._logger.info(
                "Too many changes ({}/{}); full rebuild",
                len(affected), len(current_hashes),
            )
            return self.build_graph(index)

        self._logger.info(
            "Incremental graph update: {} changed, {} added, {} deleted",
            len(changed), len(added), len(deleted),
        )
        return self.build_graph(index)

    def update_incremental(self, index: RepositoryIndex) -> "IncrementalGraphResult":
        """Explicitly incremental graph update with detailed result reporting.

        Preserves unchanged nodes, removes outdated ones, updates changed ones.
        Returns structured result with change counts.
        """
        if self._graph is None:
            graph = self.build_graph(index)
            return IncrementalGraphResult(
                graph=graph,
                added_files=len(index.files),
                changed_files=0,
                deleted_files=0,
                preserved_files=0,
                full_rebuild=True,
            )

        old_graph = self._graph
        current_hashes: dict[str, str] = {}
        for f in index.files:
            current_hashes[self._norm_path(f.relative_path)] = f.content_hash

        old_hashes: dict[str, str] = {}
        for node in old_graph.nodes.values():
            if isinstance(node, FileNode) and node.content_hash:
                old_hashes[self._norm_path(node.file_path)] = node.content_hash

        changed_count = 0
        added_count = 0
        deleted_count = 0
        preserved_count = 0

        for path, h in current_hashes.items():
            if path not in old_hashes:
                added_count += 1
            elif old_hashes[path] != h:
                changed_count += 1
            else:
                preserved_count += 1
        deleted_count = len(set(old_hashes) - set(current_hashes))

        affected = changed_count + added_count + deleted_count
        full_rebuild = affected > len(current_hashes) * 0.5 or affected > 0
        graph = self.build_graph(index) if affected > 0 else old_graph

        self._logger.info(
            "Incremental graph — added={}, changed={}, deleted={}, preserved={}",
            added_count, changed_count, deleted_count, preserved_count,
        )
        return IncrementalGraphResult(
            graph=graph,
            added_files=added_count,
            changed_files=changed_count,
            deleted_files=deleted_count,
            preserved_files=preserved_count,
            full_rebuild=full_rebuild and affected > len(current_hashes) * 0.5,
        )

    def _persist_to_db(self, graph: RepositoryGraph) -> None:
        """Persist the generated graph to the relational database.

        Never raises — persistence failures are logged but never abort
        graph generation.
        """
        if self._persistence is None:
            return

        persist_start = time.perf_counter()
        try:
            repo_data = self._persistence.get_or_create_repository(
                name=graph.repository_name,
                root_path=graph.repository_root,
                default_branch="main",
            )
            repo_id = repo_data["id"]

            node_dicts = [
                {
                    "name": node.name,
                    "type": node.kind.value if hasattr(node.kind, "value") else str(node.kind),
                }
                for node in graph.nodes.values()
            ]

            edge_dicts = [
                {
                    "source_name": graph.nodes[edge.source_id].name
                    if edge.source_id in graph.nodes
                    else edge.source_id,
                    "target_name": graph.nodes[edge.target_id].name
                    if edge.target_id in graph.nodes
                    else edge.target_id,
                    "relationship": edge.relationship.value
                    if hasattr(edge.relationship, "value")
                    else str(edge.relationship),
                }
                for edge in graph.edges
            ]

            self._persistence.persist_graph(
                repo_id,
                nodes=node_dicts,
                edges=edge_dicts,
            )

            persist_ms = round((time.perf_counter() - persist_start) * 1000.0, 3)
            self._logger.info(
                "Graph persisted — repository={}, nodes={}, edges={}, elapsed_ms={}",
                graph.repository_name,
                len(node_dicts),
                len(edge_dicts),
                persist_ms,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.error(
                "Failed to persist graph for repository={}: {}\n{}",
                graph.repository_name,
                exc,
                _format_traceback(exc),
            )

    def graph(self) -> RepositoryGraph:
        if self._graph is None:
            raise IndexError_("Repository graph has not been built yet")
        return self._graph

    def repository_statistics(self) -> GraphStatistics:
        return self.graph().statistics

    # ------------------------------------------------------------------
    # Symbol / entity lookup
    # ------------------------------------------------------------------

    def find_symbol(self, name: str) -> list[SymbolMatch]:
        g = self.graph()
        node_ids = g.symbol_table.get(name, [])
        matches: list[SymbolMatch] = []
        for node_id in node_ids:
            node = g.nodes.get(node_id)
            if node is None:
                continue
            parent_name: str | None = None
            if node.parent_id and node.parent_id in g.nodes:
                parent_name = g.nodes[node.parent_id].name
            matches.append(
                SymbolMatch(
                    name=node.name,
                    kind=node.kind,
                    node_id=node.id,
                    file_path=node.file_path,
                    module_name=node.module_name,
                    parent_name=parent_name,
                    start_line=node.start_line,
                    end_line=node.end_line,
                )
            )
        return matches

    def find_module(self, name: str) -> ModuleNode | None:
        g = self.graph()
        node_id = g.module_index.get(name.removesuffix(".py"))
        if node_id is None:
            return None
        node = g.nodes.get(node_id)
        return node if isinstance(node, ModuleNode) else None

    def find_file(self, path: str) -> FileNode | None:
        g = self.graph()
        node_id = g.file_index.get(self._norm_path(path))
        if node_id is None:
            # Allow basename match when unique
            basename = self._norm_path(path).rsplit("/", 1)[-1]
            candidates = [
                n
                for n in g.nodes.values()
                if isinstance(n, FileNode) and self._norm_path(n.name).endswith(basename)
            ]
            if len(candidates) == 1:
                return candidates[0]
            return None
        node = g.nodes.get(node_id)
        return node if isinstance(node, FileNode) else None

    def find_class(self, name: str) -> list[ClassNode]:
        g = self.graph()
        results: list[ClassNode] = []
        for match in self.find_symbol(name):
            if match.kind != NodeKind.CLASS:
                continue
            node = g.nodes.get(match.node_id)
            if isinstance(node, ClassNode):
                results.append(node)
        return results

    def find_function(self, name: str) -> list[FunctionNode]:
        g = self.graph()
        results: list[FunctionNode] = []
        for match in self.find_symbol(name):
            if match.kind in {
                NodeKind.FUNCTION,
                NodeKind.METHOD,
                NodeKind.NESTED_FUNCTION,
            }:
                node = g.nodes.get(match.node_id)
                if isinstance(node, FunctionNode):
                    results.append(node)
        return results

    def where_defined(self, symbol: str) -> list[str]:
        """Return relative file paths that define ``symbol``."""
        return sorted(
            {
                m.file_path
                for m in self.find_symbol(symbol)
                if m.file_path is not None
            }
        )

    # ------------------------------------------------------------------
    # Import / dependency queries
    # ------------------------------------------------------------------

    def who_imports(self, module: str) -> list[str]:
        """Files whose modules import ``module`` (by module name / stem)."""
        g = self.graph()
        needle = module.removesuffix(".py")
        module_node = g.module_index.get(needle)
        importers: set[str] = set()
        for edge in g.edges:
            if edge.relationship != RelationshipType.MODULE_IMPORTS_MODULE:
                continue
            if module_node and edge.target_id == module_node:
                source = g.nodes.get(edge.source_id)
                if source and source.file_path:
                    importers.add(source.file_path)
            elif isinstance(edge, ImportEdge) and edge.target_module == needle:
                source = g.nodes.get(edge.source_id)
                if source and source.file_path:
                    importers.add(source.file_path)
        return sorted(importers)

    def who_imports_file(self, path: str) -> list[str]:
        """Files that directly import ``path`` (FILE_IMPORTS_FILE)."""
        g = self.graph()
        file_node = self.find_file(path)
        if file_node is None:
            return []
        importers: set[str] = set()
        for edge in g.edges:
            if edge.relationship != RelationshipType.FILE_IMPORTS_FILE:
                continue
            if edge.target_id != file_node.id:
                continue
            source = g.nodes.get(edge.source_id)
            if source and source.file_path:
                importers.add(source.file_path)
        return sorted(importers)

    def dependencies_of(self, path: str) -> list[str]:
        """Files that ``path`` directly depends on (imports)."""
        g = self.graph()
        file_node = self.find_file(path)
        if file_node is None:
            return []
        deps: set[str] = set()
        for edge in g.edges:
            if edge.relationship != RelationshipType.FILE_IMPORTS_FILE:
                continue
            if edge.source_id != file_node.id:
                continue
            target = g.nodes.get(edge.target_id)
            if target and target.file_path:
                deps.add(target.file_path)
        return sorted(deps)

    def reverse_dependencies(self, path: str) -> list[str]:
        """Alias for direct importers of a file."""
        return self.who_imports_file(path)

    def functions_in_module(self, module: str) -> list[FunctionNode]:
        g = self.graph()
        module_node = self.find_module(module)
        if module_node is None:
            return []
        results: list[FunctionNode] = []
        for edge in g.edges:
            if edge.relationship != RelationshipType.MODULE_CONTAINS_FUNCTION:
                continue
            if edge.source_id != module_node.id:
                continue
            node = g.nodes.get(edge.target_id)
            if isinstance(node, FunctionNode):
                results.append(node)
        return sorted(results, key=lambda n: n.name)

    def classes_in_module(self, module: str) -> list[ClassNode]:
        g = self.graph()
        module_node = self.find_module(module)
        if module_node is None:
            return []
        results: list[ClassNode] = []
        for edge in g.edges:
            if edge.relationship != RelationshipType.MODULE_CONTAINS_CLASS:
                continue
            if edge.source_id != module_node.id:
                continue
            node = g.nodes.get(edge.target_id)
            if isinstance(node, ClassNode):
                results.append(node)
        return sorted(results, key=lambda n: n.name)

    def methods_of(self, class_name: str) -> list[FunctionNode]:
        g = self.graph()
        classes = self.find_class(class_name)
        results: list[FunctionNode] = []
        for cls in classes:
            for edge in g.edges:
                if edge.relationship != RelationshipType.CLASS_CONTAINS_METHOD:
                    continue
                if edge.source_id != cls.id:
                    continue
                node = g.nodes.get(edge.target_id)
                if isinstance(node, FunctionNode):
                    results.append(node)
        return sorted(results, key=lambda n: (n.file_path or "", n.name))

    def nested_functions(self, function_name: str) -> list[FunctionNode]:
        g = self.graph()
        parents = self.find_function(function_name)
        results: list[FunctionNode] = []
        parent_ids = {p.id for p in parents}
        for edge in g.edges:
            if edge.relationship != RelationshipType.NESTED_FUNCTION:
                continue
            if edge.source_id not in parent_ids:
                continue
            node = g.nodes.get(edge.target_id)
            if isinstance(node, FunctionNode):
                results.append(node)
        return sorted(results, key=lambda n: (n.file_path or "", n.name))

    # ------------------------------------------------------------------
    # Impact analysis (deterministic, import/reference based)
    # ------------------------------------------------------------------

    def affected_files(self, path: str) -> list[str]:
        """Transitive reverse dependents of ``path`` via import edges only."""
        g = self.graph()
        start = self.find_file(path)
        if start is None:
            return []

        # Build reverse adjacency: target_file_id -> [source_file_id, ...]
        reverse: dict[str, set[str]] = defaultdict(set)
        for edge in g.edges:
            if edge.relationship != RelationshipType.FILE_IMPORTS_FILE:
                continue
            reverse[edge.target_id].add(edge.source_id)

        # Also follow symbol reference edges back to their source files
        for edge in g.edges:
            if edge.relationship != RelationshipType.REFERENCES_SYMBOL:
                continue
            target = g.nodes.get(edge.target_id)
            source = g.nodes.get(edge.source_id)
            if target is None or source is None:
                continue
            if target.file_path != start.file_path:
                continue
            if source.file_path and source.kind == NodeKind.FILE:
                reverse[start.id].add(source.id)
            elif source.file_path:
                src_file_id = g.file_index.get(self._norm_path(source.file_path))
                if src_file_id:
                    reverse[start.id].add(src_file_id)

        affected: set[str] = set()
        queue: deque[str] = deque(reverse.get(start.id, ()))
        seen: set[str] = {start.id}
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            node = g.nodes.get(current)
            if node and node.file_path:
                affected.add(node.file_path)
            for nxt in reverse.get(current, ()):
                if nxt not in seen:
                    queue.append(nxt)
        return sorted(affected)

    # ------------------------------------------------------------------
    # Aggregation helpers (CLI)
    # ------------------------------------------------------------------

    def top_imported_modules(self, limit: int = 10) -> list[tuple[str, int]]:
        g = self.graph()
        counts: dict[str, int] = defaultdict(int)
        for edge in g.edges:
            if edge.relationship != RelationshipType.MODULE_IMPORTS_MODULE:
                continue
            target = g.nodes.get(edge.target_id)
            if target:
                counts[target.name] += 1
            elif isinstance(edge, ImportEdge) and edge.target_module:
                counts[edge.target_module] += 1
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]

    def top_referenced_symbols(self, limit: int = 10) -> list[tuple[str, int]]:
        g = self.graph()
        counts: dict[str, int] = defaultdict(int)
        for edge in g.edges:
            if edge.relationship != RelationshipType.REFERENCES_SYMBOL:
                continue
            if isinstance(edge, ReferenceEdge) and edge.symbol_name:
                counts[edge.symbol_name] += 1
            else:
                target = g.nodes.get(edge.target_id)
                if target:
                    counts[target.name] += 1
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]

    def most_connected_files(self, limit: int = 10) -> list[tuple[str, int]]:
        g = self.graph()
        degree: dict[str, int] = defaultdict(int)
        for edge in g.edges:
            if edge.relationship not in {
                RelationshipType.FILE_IMPORTS_FILE,
                RelationshipType.REFERENCES_SYMBOL,
            }:
                continue
            for node_id in (edge.source_id, edge.target_id):
                node = g.nodes.get(node_id)
                if node is None:
                    continue
                path = node.file_path
                if path is None and node.kind == NodeKind.FILE:
                    path = node.name
                if path:
                    degree[path] += 1
        return sorted(degree.items(), key=lambda item: (-item[1], item[0]))[:limit]

    def defined_symbols_in_file(self, path: str) -> list[SymbolMatch]:
        file_node = self.find_file(path)
        if file_node is None:
            return []
        g = self.graph()
        matches: list[SymbolMatch] = []
        for node in g.nodes.values():
            if node.file_path != file_node.file_path:
                continue
            if node.kind in {NodeKind.FILE, NodeKind.MODULE}:
                continue
            parent_name: str | None = None
            if node.parent_id and node.parent_id in g.nodes:
                parent_name = g.nodes[node.parent_id].name
            matches.append(
                SymbolMatch(
                    name=node.name,
                    kind=node.kind,
                    node_id=node.id,
                    file_path=node.file_path,
                    module_name=node.module_name,
                    parent_name=parent_name,
                    start_line=node.start_line,
                    end_line=node.end_line,
                )
            )
        return sorted(matches, key=lambda m: (m.kind.value, m.name))

    def files_referencing_symbol(self, name: str) -> list[str]:
        g = self.graph()
        defs = {m.node_id for m in self.find_symbol(name)}
        if not defs:
            return []
        refs: set[str] = set()
        for edge in g.edges:
            if edge.relationship not in {
                RelationshipType.REFERENCES_SYMBOL,
                RelationshipType.CALLS,
            }:
                continue
            if edge.target_id not in defs:
                continue
            source = g.nodes.get(edge.source_id)
            if source and source.file_path:
                refs.add(source.file_path)
        return sorted(refs)

    # ------------------------------------------------------------------
    # Call / inheritance queries
    # ------------------------------------------------------------------

    def callers_of(self, symbol: str) -> list[str]:
        """File paths that CALL ``symbol``."""
        g = self.graph()
        paths: set[str] = set()
        for edge in g.edges:
            if edge.relationship != RelationshipType.CALLS:
                continue
            target = g.nodes.get(edge.target_id)
            if target is None or target.name != symbol:
                continue
            source = g.nodes.get(edge.source_id)
            if source is not None and source.file_path:
                paths.add(self._norm_path(source.file_path))
        return sorted(paths)

    def callees_of(self, path: str) -> list[str]:
        """Callee symbol names called from ``path``."""
        g = self.graph()
        file_id = g.file_index.get(self._norm_path(path))
        if file_id is None:
            return []
        names: set[str] = set()
        for edge in g.edges:
            if edge.relationship != RelationshipType.CALLS or edge.source_id != file_id:
                continue
            target = g.nodes.get(edge.target_id)
            if target is not None:
                names.add(target.name)
        return sorted(names)

    def base_classes_of(self, class_name: str) -> list[str]:
        g = self.graph()
        bases: set[str] = set()
        for edge in g.edges:
            if edge.relationship != RelationshipType.INHERITS_FROM:
                continue
            source = g.nodes.get(edge.source_id)
            if source is None or source.name != class_name:
                continue
            if isinstance(edge, InheritanceEdge) and edge.base_name:
                bases.add(edge.base_name.split(".")[-1])
            else:
                target = g.nodes.get(edge.target_id)
                if target is not None:
                    bases.add(target.name)
        return sorted(bases)

    def subclasses_of(self, class_name: str) -> list[str]:
        g = self.graph()
        names: set[str] = set()
        for edge in g.edges:
            if edge.relationship != RelationshipType.INHERITS_FROM:
                continue
            base_ok = False
            if isinstance(edge, InheritanceEdge) and (edge.base_name or "").split(".")[-1] == class_name:
                base_ok = True
            target = g.nodes.get(edge.target_id)
            if target is not None and target.name == class_name:
                base_ok = True
            if not base_ok:
                continue
            source = g.nodes.get(edge.source_id)
            if source is not None:
                names.add(source.name)
        return sorted(names)

    # ------------------------------------------------------------------
    # Structural analysis (deterministic, no AI)
    # ------------------------------------------------------------------

    def find_cycles(self) -> list[DependencyCycle]:
        """Detect file-level import cycles (SCCs with size >= 2)."""
        g = self.graph()
        adjacency: dict[str, set[str]] = defaultdict(set)
        file_ids = [nid for nid, n in g.nodes.items() if n.kind == NodeKind.FILE]
        for edge in g.edges:
            if edge.relationship != RelationshipType.FILE_IMPORTS_FILE:
                continue
            adjacency[edge.source_id].add(edge.target_id)

        index = 0
        stack: list[str] = []
        on_stack: set[str] = set()
        indices: dict[str, int] = {}
        lowlink: dict[str, int] = {}
        components: list[list[str]] = []

        def strongconnect(v: str) -> None:
            nonlocal index
            indices[v] = index
            lowlink[v] = index
            index += 1
            stack.append(v)
            on_stack.add(v)
            for w in sorted(adjacency.get(v, ())):
                if w not in indices:
                    strongconnect(w)
                    lowlink[v] = min(lowlink[v], lowlink[w])
                elif w in on_stack:
                    lowlink[v] = min(lowlink[v], indices[w])
            if lowlink[v] == indices[v]:
                comp: list[str] = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) >= 2:
                    components.append(comp)
                elif comp and comp[0] in adjacency.get(comp[0], ()):
                    components.append(comp)

        for node_id in sorted(file_ids):
            if node_id not in indices:
                strongconnect(node_id)

        cycles: list[DependencyCycle] = []
        for comp in components:
            paths = sorted(
                {
                    self._norm_path(g.nodes[nid].file_path or g.nodes[nid].name)
                    for nid in comp
                    if nid in g.nodes
                }
            )
            if paths:
                cycles.append(DependencyCycle(files=paths))
        cycles.sort(key=lambda c: (len(c.files), c.files))
        return cycles

    def orphan_modules(self) -> list[OrphanModule]:
        """Modules whose files have zero inbound and outbound FILE_IMPORTS_FILE edges."""
        g = self.graph()
        connected: set[str] = set()
        for edge in g.edges:
            if edge.relationship != RelationshipType.FILE_IMPORTS_FILE:
                continue
            connected.add(edge.source_id)
            connected.add(edge.target_id)

        orphans: list[OrphanModule] = []
        for node in g.nodes.values():
            if node.kind != NodeKind.MODULE:
                continue
            file_id = g.file_index.get(self._norm_path(node.file_path or ""))
            if file_id is None or file_id in connected:
                continue
            orphans.append(
                OrphanModule(
                    module_name=node.module_name or node.name,
                    file_path=self._norm_path(node.file_path or ""),
                )
            )
        return sorted(orphans, key=lambda o: (o.file_path, o.module_name))

    def unused_symbols(self) -> list[UnusedSymbol]:
        """Symbols with no inbound REFERENCES / CALLS / INHERITS_FROM edges."""
        g = self.graph()
        referenced: set[str] = set()
        for edge in g.edges:
            if edge.relationship in {
                RelationshipType.REFERENCES_SYMBOL,
                RelationshipType.CALLS,
                RelationshipType.INHERITS_FROM,
            }:
                referenced.add(edge.target_id)

        unused: list[UnusedSymbol] = []
        for node in g.nodes.values():
            if node.kind not in {
                NodeKind.FUNCTION,
                NodeKind.METHOD,
                NodeKind.NESTED_FUNCTION,
                NodeKind.CLASS,
            }:
                continue
            if node.id in referenced:
                continue
            if node.name in {"main", "__init__", "__enter__", "__exit__"}:
                continue
            if node.name.startswith("__") and node.name.endswith("__"):
                continue
            unused.append(
                UnusedSymbol(
                    name=node.name,
                    kind=node.kind,
                    file_path=node.file_path,
                    node_id=node.id,
                )
            )
        return sorted(
            unused,
            key=lambda u: (u.file_path or "", u.kind.value, u.name),
        )

    def dead_code_candidates(self) -> list[DeadCodeCandidate]:
        """Unused symbols that look like private helpers (heuristic)."""
        candidates: list[DeadCodeCandidate] = []
        for item in self.unused_symbols():
            if item.kind == NodeKind.METHOD and item.name.startswith("test_"):
                continue
            reason = "no inbound references"
            if item.name.startswith("_"):
                reason = "private symbol with no inbound references"
            elif item.kind == NodeKind.NESTED_FUNCTION:
                reason = "nested function with no inbound references"
            candidates.append(
                DeadCodeCandidate(
                    name=item.name,
                    kind=item.kind,
                    file_path=item.file_path,
                    reason=reason,
                )
            )
        return candidates

    def graph_distance(
        self, source_path: str, target_path: str, *, max_depth: int = 6
    ) -> int | None:
        """BFS distance over FILE_IMPORTS_FILE undirected edges; None if unreachable."""
        g = self.graph()
        src = g.file_index.get(self._norm_path(source_path))
        dst = g.file_index.get(self._norm_path(target_path))
        if src is None or dst is None:
            return None
        if src == dst:
            return 0
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in g.edges:
            if edge.relationship != RelationshipType.FILE_IMPORTS_FILE:
                continue
            adjacency[edge.source_id].add(edge.target_id)
            adjacency[edge.target_id].add(edge.source_id)

        queue: deque[tuple[str, int]] = deque([(src, 0)])
        seen = {src}
        while queue:
            node_id, dist = queue.popleft()
            if dist >= max_depth:
                continue
            for nxt in sorted(adjacency.get(node_id, ())):
                if nxt in seen:
                    continue
                if nxt == dst:
                    return dist + 1
                seen.add(nxt)
                queue.append((nxt, dist + 1))
        return None

    # ------------------------------------------------------------------
    # Internals — construction
    # ------------------------------------------------------------------

    def _add_symbols_for_file(
        self,
        graph: RepositoryGraph,
        indexed: IndexedFile,
        *,
        file_id: str,
        module_id: str,
        symbol_nodes: dict[tuple[str, str, str], str],
    ) -> None:
        # First pass: create nodes
        class_ids: dict[str, str] = {}
        function_ids: dict[str, str] = {}  # name -> id for top-level / methods by qualified key

        for symbol in indexed.symbols:
            if symbol.kind == SymbolKind.MODULE:
                continue
            node = self._node_from_symbol(symbol, indexed)
            graph.nodes[node.id] = node
            graph.symbol_table.setdefault(symbol.name, []).append(node.id)
            symbol_nodes[(indexed.relative_path, symbol.name, symbol.kind.value)] = node.id

            if symbol.kind == SymbolKind.CLASS:
                class_ids[symbol.name] = node.id
            elif symbol.kind == SymbolKind.FUNCTION:
                function_ids[symbol.name] = node.id
            elif symbol.kind == SymbolKind.METHOD and symbol.parent:
                function_ids[f"{symbol.parent}.{symbol.name}"] = node.id
            elif symbol.kind == SymbolKind.NESTED_FUNCTION and symbol.parent:
                function_ids[f"{symbol.parent}.{symbol.name}"] = node.id

            # Definition / containment edges
            if symbol.kind == SymbolKind.CLASS:
                self._link_class(graph, node.id, file_id, module_id)
            elif symbol.kind == SymbolKind.FUNCTION:
                self._link_function(graph, node.id, file_id, module_id)
            elif symbol.kind == SymbolKind.METHOD and symbol.parent:
                class_id = class_ids.get(symbol.parent)
                self._link_method(graph, node.id, file_id, module_id, class_id)
            elif symbol.kind == SymbolKind.NESTED_FUNCTION and symbol.parent:
                parent_id = self._resolve_parent_function_id(
                    symbol, indexed, function_ids, class_ids
                )
                self._link_nested(graph, node.id, file_id, module_id, parent_id)

    def _resolve_parent_function_id(
        self,
        symbol: IndexedSymbol,
        indexed: IndexedFile,
        function_ids: dict[str, str],
        class_ids: dict[str, str],
    ) -> str | None:
        parent = symbol.parent
        if parent is None:
            return None
        # Prefer exact key; fall back to bare parent name (top-level function)
        if parent in function_ids:
            return function_ids[parent]
        # Method parent: parent is the enclosing function name; try class.method keys
        for key, node_id in function_ids.items():
            if key.endswith(f".{parent}") or key == parent:
                return node_id
        # Last resort: look up by symbol table from already-added nodes in this file
        for s in indexed.symbols:
            if s.name == parent and s.kind in {
                SymbolKind.FUNCTION,
                SymbolKind.METHOD,
                SymbolKind.NESTED_FUNCTION,
            }:
                return self._symbol_node_id(s, indexed.relative_path)
        _ = class_ids  # reserved for future qualified resolution
        return None

    def _link_class(
        self, graph: RepositoryGraph, class_id: str, file_id: str, module_id: str
    ) -> None:
        self._add_edge(
            graph,
            DefinitionEdge(
                id=self._edge_id(RelationshipType.MODULE_CONTAINS_CLASS, module_id, class_id),
                source_id=module_id,
                target_id=class_id,
                relationship=RelationshipType.MODULE_CONTAINS_CLASS,
            ),
        )
        self._add_edge(
            graph,
            DefinitionEdge(
                id=self._edge_id(RelationshipType.CLASS_DEFINED_IN_FILE, class_id, file_id),
                source_id=class_id,
                target_id=file_id,
                relationship=RelationshipType.CLASS_DEFINED_IN_FILE,
            ),
        )
        self._add_edge(
            graph,
            DefinitionEdge(
                id=self._edge_id(RelationshipType.CLASS_DEFINED_IN_MODULE, class_id, module_id),
                source_id=class_id,
                target_id=module_id,
                relationship=RelationshipType.CLASS_DEFINED_IN_MODULE,
            ),
        )
        self._add_edge(
            graph,
            DefinitionEdge(
                id=self._edge_id(RelationshipType.SYMBOL_DEFINED_IN_FILE, class_id, file_id),
                source_id=class_id,
                target_id=file_id,
                relationship=RelationshipType.SYMBOL_DEFINED_IN_FILE,
            ),
        )
        self._add_edge(
            graph,
            DefinitionEdge(
                id=self._edge_id(RelationshipType.SYMBOL_DEFINED_IN_MODULE, class_id, module_id),
                source_id=class_id,
                target_id=module_id,
                relationship=RelationshipType.SYMBOL_DEFINED_IN_MODULE,
            ),
        )

    def _link_function(
        self, graph: RepositoryGraph, fn_id: str, file_id: str, module_id: str
    ) -> None:
        self._add_edge(
            graph,
            DefinitionEdge(
                id=self._edge_id(RelationshipType.MODULE_CONTAINS_FUNCTION, module_id, fn_id),
                source_id=module_id,
                target_id=fn_id,
                relationship=RelationshipType.MODULE_CONTAINS_FUNCTION,
            ),
        )
        self._add_edge(
            graph,
            DefinitionEdge(
                id=self._edge_id(RelationshipType.FUNCTION_DEFINED_IN_FILE, fn_id, file_id),
                source_id=fn_id,
                target_id=file_id,
                relationship=RelationshipType.FUNCTION_DEFINED_IN_FILE,
            ),
        )
        self._add_edge(
            graph,
            DefinitionEdge(
                id=self._edge_id(RelationshipType.FUNCTION_DEFINED_IN_MODULE, fn_id, module_id),
                source_id=fn_id,
                target_id=module_id,
                relationship=RelationshipType.FUNCTION_DEFINED_IN_MODULE,
            ),
        )
        self._add_edge(
            graph,
            DefinitionEdge(
                id=self._edge_id(RelationshipType.SYMBOL_DEFINED_IN_FILE, fn_id, file_id),
                source_id=fn_id,
                target_id=file_id,
                relationship=RelationshipType.SYMBOL_DEFINED_IN_FILE,
            ),
        )
        self._add_edge(
            graph,
            DefinitionEdge(
                id=self._edge_id(RelationshipType.SYMBOL_DEFINED_IN_MODULE, fn_id, module_id),
                source_id=fn_id,
                target_id=module_id,
                relationship=RelationshipType.SYMBOL_DEFINED_IN_MODULE,
            ),
        )

    def _link_method(
        self,
        graph: RepositoryGraph,
        method_id: str,
        file_id: str,
        module_id: str,
        class_id: str | None,
    ) -> None:
        if class_id:
            self._add_edge(
                graph,
                DefinitionEdge(
                    id=self._edge_id(
                        RelationshipType.CLASS_CONTAINS_METHOD, class_id, method_id
                    ),
                    source_id=class_id,
                    target_id=method_id,
                    relationship=RelationshipType.CLASS_CONTAINS_METHOD,
                ),
            )
        self._add_edge(
            graph,
            DefinitionEdge(
                id=self._edge_id(RelationshipType.FUNCTION_DEFINED_IN_FILE, method_id, file_id),
                source_id=method_id,
                target_id=file_id,
                relationship=RelationshipType.FUNCTION_DEFINED_IN_FILE,
            ),
        )
        self._add_edge(
            graph,
            DefinitionEdge(
                id=self._edge_id(
                    RelationshipType.FUNCTION_DEFINED_IN_MODULE, method_id, module_id
                ),
                source_id=method_id,
                target_id=module_id,
                relationship=RelationshipType.FUNCTION_DEFINED_IN_MODULE,
            ),
        )
        self._add_edge(
            graph,
            DefinitionEdge(
                id=self._edge_id(RelationshipType.SYMBOL_DEFINED_IN_FILE, method_id, file_id),
                source_id=method_id,
                target_id=file_id,
                relationship=RelationshipType.SYMBOL_DEFINED_IN_FILE,
            ),
        )

    def _link_nested(
        self,
        graph: RepositoryGraph,
        nested_id: str,
        file_id: str,
        module_id: str,
        parent_id: str | None,
    ) -> None:
        if parent_id:
            nested_node = graph.nodes.get(nested_id)
            if nested_node is not None:
                nested_node.parent_id = parent_id
            self._add_edge(
                graph,
                DefinitionEdge(
                    id=self._edge_id(RelationshipType.NESTED_FUNCTION, parent_id, nested_id),
                    source_id=parent_id,
                    target_id=nested_id,
                    relationship=RelationshipType.NESTED_FUNCTION,
                ),
            )
            self._add_edge(
                graph,
                DefinitionEdge(
                    id=self._edge_id(RelationshipType.PARENT_FUNCTION, nested_id, parent_id),
                    source_id=nested_id,
                    target_id=parent_id,
                    relationship=RelationshipType.PARENT_FUNCTION,
                ),
            )
        self._add_edge(
            graph,
            DefinitionEdge(
                id=self._edge_id(RelationshipType.FUNCTION_DEFINED_IN_FILE, nested_id, file_id),
                source_id=nested_id,
                target_id=file_id,
                relationship=RelationshipType.FUNCTION_DEFINED_IN_FILE,
            ),
        )
        self._add_edge(
            graph,
            DefinitionEdge(
                id=self._edge_id(
                    RelationshipType.SYMBOL_DEFINED_IN_MODULE, nested_id, module_id
                ),
                source_id=nested_id,
                target_id=module_id,
                relationship=RelationshipType.SYMBOL_DEFINED_IN_MODULE,
            ),
        )

    def _add_import_edges(
        self,
        graph: RepositoryGraph,
        index: RepositoryIndex,
        *,
        file_by_path: dict[str, str],
        module_by_name: dict[str, str],
        module_to_file: dict[str, str],
        symbol_nodes: dict[tuple[str, str, str], str],
    ) -> None:
        seen_file_deps: set[tuple[str, str]] = set()

        for ref in index.import_references:
            if (ref.kind or "import") == "call":
                continue
            source_path = self._norm_path(ref.source_file)
            source_file_id = file_by_path.get(source_path)
            source_module_id = module_by_name.get(ref.source_module)
            if source_file_id is None or source_module_id is None:
                continue

            target_stem = ref.target_module.split(".")[-1]
            target_module_id = module_by_name.get(ref.target_module) or module_by_name.get(
                target_stem
            )
            target_file_path = module_to_file.get(ref.target_module) or module_to_file.get(
                target_stem
            )
            target_file_id = (
                file_by_path.get(self._norm_path(target_file_path))
                if target_file_path
                else None
            )

            # MODULE_IMPORTS_MODULE (even for external / unresolved targets we record
            # an edge only when the target module exists in the index)
            if target_module_id is not None:
                self._add_edge(
                    graph,
                    ImportEdge(
                        id=self._edge_id(
                            RelationshipType.MODULE_IMPORTS_MODULE,
                            source_module_id,
                            target_module_id,
                            ref.symbol or "",
                        ),
                        source_id=source_module_id,
                        target_id=target_module_id,
                        relationship=RelationshipType.MODULE_IMPORTS_MODULE,
                        imported_symbol=ref.symbol,
                        target_module=ref.target_module,
                    ),
                )

            if target_file_id is not None:
                dep_key = (source_file_id, target_file_id)
                if dep_key not in seen_file_deps:
                    seen_file_deps.add(dep_key)
                    self._add_edge(
                        graph,
                        ImportEdge(
                            id=self._edge_id(
                                RelationshipType.FILE_IMPORTS_FILE,
                                source_file_id,
                                target_file_id,
                            ),
                            source_id=source_file_id,
                            target_id=target_file_id,
                            relationship=RelationshipType.FILE_IMPORTS_FILE,
                            imported_symbol=ref.symbol,
                            target_module=ref.target_module,
                        ),
                    )
                    self._add_edge(
                        graph,
                        DependencyEdge(
                            id=self._edge_id(
                                "DEPENDENCY",
                                source_file_id,
                                target_file_id,
                            ),
                            source_id=source_file_id,
                            target_id=target_file_id,
                            relationship=RelationshipType.FILE_IMPORTS_FILE,
                        ),
                    )

            # Symbol reference + best-effort call when imported name resolves
            if ref.symbol and target_file_path:
                target_symbol_id = self._lookup_imported_symbol(
                    symbol_nodes,
                    target_file_path,
                    ref.symbol,
                )
                if target_symbol_id is not None:
                    self._add_edge(
                        graph,
                        ReferenceEdge(
                            id=self._edge_id(
                                RelationshipType.REFERENCES_SYMBOL,
                                source_file_id,
                                target_symbol_id,
                            ),
                            source_id=source_file_id,
                            target_id=target_symbol_id,
                            relationship=RelationshipType.REFERENCES_SYMBOL,
                            symbol_name=ref.symbol,
                        ),
                    )
                    # Best-effort: treating a named import of a function as a call site
                    # is heuristic only — recorded as CALLS for downstream consumers.
                    target_node = graph.nodes.get(target_symbol_id)
                    if target_node and target_node.kind in {
                        NodeKind.FUNCTION,
                        NodeKind.METHOD,
                        NodeKind.NESTED_FUNCTION,
                    }:
                        self._add_edge(
                            graph,
                            CallEdge(
                                id=self._edge_id(
                                    RelationshipType.CALLS,
                                    source_file_id,
                                    target_symbol_id,
                                ),
                                source_id=source_file_id,
                                target_id=target_symbol_id,
                                relationship=RelationshipType.CALLS,
                                callee_name=ref.symbol,
                            ),
                        )

    def _add_call_site_edges(
        self,
        graph: RepositoryGraph,
        index: RepositoryIndex,
        *,
        file_by_path: dict[str, str],
    ) -> None:
        """Resolve AST call references (kind=call) against the symbol table."""
        for ref in index.import_references:
            if (ref.kind or "") != "call" or not ref.symbol:
                continue
            source_path = self._norm_path(ref.source_file)
            source_file_id = file_by_path.get(source_path)
            if source_file_id is None:
                continue
            candidates = graph.symbol_table.get(ref.symbol, [])
            if not candidates:
                continue
            target_id = candidates[0]
            for node_id in candidates:
                node = graph.nodes.get(node_id)
                if node and self._norm_path(node.file_path or "") == source_path:
                    target_id = node_id
                    break
            target = graph.nodes.get(target_id)
            if target is None or target.kind not in {
                NodeKind.FUNCTION,
                NodeKind.METHOD,
                NodeKind.NESTED_FUNCTION,
            }:
                continue
            self._add_edge(
                graph,
                CallEdge(
                    id=self._edge_id(
                        RelationshipType.CALLS,
                        source_file_id,
                        target_id,
                        ref.symbol,
                    ),
                    source_id=source_file_id,
                    target_id=target_id,
                    relationship=RelationshipType.CALLS,
                    callee_name=ref.symbol,
                ),
            )

    def _add_inheritance_edges(self, graph: RepositoryGraph, index: RepositoryIndex) -> None:
        for symbol in index.symbols:
            if symbol.kind != SymbolKind.CLASS or not symbol.bases:
                continue
            class_id = self._class_id(symbol.file_path, symbol.name)
            if class_id not in graph.nodes:
                continue
            for base in symbol.bases:
                base_name = base.split(".")[-1].strip()
                if not base_name or base_name == "object":
                    continue
                candidates = [
                    nid
                    for nid in graph.symbol_table.get(base_name, [])
                    if isinstance(graph.nodes.get(nid), ClassNode)
                ]
                if not candidates:
                    continue
                target_id = candidates[0]
                for node_id in candidates:
                    node = graph.nodes.get(node_id)
                    if (
                        node
                        and self._norm_path(node.file_path or "")
                        == self._norm_path(symbol.file_path)
                    ):
                        target_id = node_id
                        break
                self._add_edge(
                    graph,
                    InheritanceEdge(
                        id=self._edge_id(
                            RelationshipType.INHERITS_FROM,
                            class_id,
                            target_id,
                            base_name,
                        ),
                        source_id=class_id,
                        target_id=target_id,
                        relationship=RelationshipType.INHERITS_FROM,
                        base_name=base_name,
                    ),
                )

    def _add_module_hierarchy(
        self, graph: RepositoryGraph, index: RepositoryIndex
    ) -> None:
        """Create package nodes and MODULE_CHILD_OF edges from file paths."""
        for indexed in index.files:
            path = self._norm_path(indexed.relative_path)
            parts = path.split("/")
            if len(parts) < 2:
                continue
            dirs = parts[:-1]
            parent_pkg_id: str | None = None
            for depth in range(1, len(dirs) + 1):
                pkg_parts = dirs[:depth]
                pkg_name = ".".join(pkg_parts)
                pkg_id = f"package:{pkg_name}"
                if pkg_id not in graph.nodes:
                    graph.nodes[pkg_id] = PackageNode(
                        id=pkg_id,
                        kind=NodeKind.PACKAGE,
                        name=pkg_name,
                        module_name=pkg_name,
                    )
                    graph.package_index[pkg_name] = pkg_id
                if parent_pkg_id is not None:
                    self._add_edge(
                        graph,
                        DefinitionEdge(
                            id=self._edge_id(
                                RelationshipType.MODULE_CHILD_OF,
                                pkg_id,
                                parent_pkg_id,
                            ),
                            source_id=pkg_id,
                            target_id=parent_pkg_id,
                            relationship=RelationshipType.MODULE_CHILD_OF,
                        ),
                    )
                parent_pkg_id = pkg_id

            module_id = graph.module_index.get(indexed.module_name)
            if module_id and parent_pkg_id:
                self._add_edge(
                    graph,
                    DefinitionEdge(
                        id=self._edge_id(
                            RelationshipType.MODULE_CHILD_OF,
                            module_id,
                            parent_pkg_id,
                        ),
                        source_id=module_id,
                        target_id=parent_pkg_id,
                        relationship=RelationshipType.MODULE_CHILD_OF,
                    ),
                )

    def _lookup_imported_symbol(
        self,
        symbol_nodes: dict[tuple[str, str, str], str],
        target_file_path: str,
        symbol_name: str,
    ) -> str | None:
        for kind in (
            SymbolKind.FUNCTION.value,
            SymbolKind.CLASS.value,
            SymbolKind.METHOD.value,
            SymbolKind.NESTED_FUNCTION.value,
        ):
            node_id = symbol_nodes.get((target_file_path, symbol_name, kind))
            if node_id is not None:
                return node_id
        # Path normalization fallback
        norm = self._norm_path(target_file_path)
        for (path, name, kind), node_id in symbol_nodes.items():
            if name == symbol_name and self._norm_path(path) == norm:
                return node_id
        return None

    def _node_from_symbol(self, symbol: IndexedSymbol, indexed: IndexedFile) -> Node:
        node_id = self._symbol_node_id(symbol, indexed.relative_path)
        common = {
            "id": node_id,
            "name": symbol.name,
            "file_path": indexed.relative_path,
            "module_name": indexed.module_name,
            "start_line": symbol.start_line,
            "end_line": symbol.end_line,
            "decorators": list(symbol.decorators),
            "is_async": symbol.is_async,
            "is_generator": symbol.is_generator,
        }
        if symbol.kind == SymbolKind.CLASS:
            return ClassNode(kind=NodeKind.CLASS, bases=list(symbol.bases), **common)
        if symbol.kind == SymbolKind.METHOD:
            parent_id = (
                self._class_id(indexed.relative_path, symbol.parent)
                if symbol.parent
                else None
            )
            return FunctionNode(
                kind=NodeKind.METHOD,
                parent_id=parent_id,
                **common,
            )
        if symbol.kind == SymbolKind.NESTED_FUNCTION:
            return FunctionNode(
                kind=NodeKind.NESTED_FUNCTION,
                **common,
            )
        return FunctionNode(kind=NodeKind.FUNCTION, **common)

    def _compute_statistics(self, graph: RepositoryGraph) -> GraphStatistics:
        files = 0
        modules = 0
        packages = 0
        classes = 0
        functions = 0
        methods = 0
        nested = 0
        for node in graph.nodes.values():
            if node.kind == NodeKind.FILE:
                files += 1
            elif node.kind == NodeKind.MODULE:
                modules += 1
            elif node.kind == NodeKind.PACKAGE:
                packages += 1
            elif node.kind == NodeKind.CLASS:
                classes += 1
            elif node.kind == NodeKind.FUNCTION:
                functions += 1
            elif node.kind == NodeKind.METHOD:
                methods += 1
            elif node.kind == NodeKind.NESTED_FUNCTION:
                nested += 1

        import_edges = sum(1 for e in graph.edges if isinstance(e, ImportEdge))
        dependency_edges = sum(1 for e in graph.edges if isinstance(e, DependencyEdge))
        reference_edges = sum(1 for e in graph.edges if isinstance(e, ReferenceEdge))
        call_edges = sum(1 for e in graph.edges if isinstance(e, CallEdge))
        inheritance_edges = sum(1 for e in graph.edges if isinstance(e, InheritanceEdge))
        hierarchy_edges = sum(
            1 for e in graph.edges if e.relationship == RelationshipType.MODULE_CHILD_OF
        )
        definition_edges = sum(1 for e in graph.edges if isinstance(e, DefinitionEdge))

        total_imports = sum(
            n.import_count for n in graph.nodes.values() if isinstance(n, FileNode)
        )
        total_symbols = sum(
            n.symbol_count for n in graph.nodes.values() if isinstance(n, FileNode)
        )
        avg_imports = (total_imports / files) if files else 0.0
        avg_symbols = (total_symbols / files) if files else 0.0

        # Analysis counts (use temporary self._graph)
        previous = self._graph
        self._graph = graph
        try:
            cycle_count = len(self.find_cycles())
            orphan_count = len(self.orphan_modules())
            unused_count = len(self.unused_symbols())
        finally:
            self._graph = previous

        return GraphStatistics(
            files=files,
            modules=modules,
            packages=packages,
            classes=classes,
            functions=functions,
            methods=methods,
            nested_functions=nested,
            import_edges=import_edges,
            definition_edges=definition_edges,
            dependency_edges=dependency_edges,
            reference_edges=reference_edges,
            call_edges=call_edges,
            inheritance_edges=inheritance_edges,
            hierarchy_edges=hierarchy_edges,
            total_nodes=len(graph.nodes),
            total_edges=len(graph.edges),
            average_imports_per_file=round(avg_imports, 2),
            average_symbols_per_file=round(avg_symbols, 2),
            cyclic_dependency_count=cycle_count,
            orphan_module_count=orphan_count,
            unused_symbol_count=unused_count,
        )

    @staticmethod
    def _add_edge(graph: RepositoryGraph, edge: Edge) -> None:
        # Deterministic de-dupe by edge id
        if any(existing.id == edge.id for existing in graph.edges):
            return
        graph.edges.append(edge)

    @staticmethod
    def _norm_path(path: str) -> str:
        return path.replace("\\", "/")

    @staticmethod
    def _file_id(relative_path: str) -> str:
        return f"file:{relative_path.replace(chr(92), '/')}"

    @staticmethod
    def _module_id(module_name: str, relative_path: str) -> str:
        # Include path so duplicate stems in different folders stay unique
        return f"module:{relative_path.replace(chr(92), '/')}:{module_name}"

    @staticmethod
    def _class_id(relative_path: str, class_name: str) -> str:
        return f"class:{relative_path.replace(chr(92), '/')}:{class_name}"

    @staticmethod
    def _symbol_node_id(symbol: IndexedSymbol, relative_path: str) -> str:
        path = relative_path.replace("\\", "/")
        if symbol.kind == SymbolKind.CLASS:
            return f"class:{path}:{symbol.name}"
        if symbol.kind == SymbolKind.METHOD:
            parent = symbol.parent or "_"
            return f"method:{path}:{parent}.{symbol.name}"
        if symbol.kind == SymbolKind.NESTED_FUNCTION:
            parent = symbol.parent or "_"
            return f"nested:{path}:{parent}.{symbol.name}"
        return f"function:{path}:{symbol.name}"

    @staticmethod
    def _edge_id(
        relationship: RelationshipType | str,
        source_id: str,
        target_id: str,
        extra: str = "",
    ) -> str:
        rel = relationship.value if isinstance(relationship, RelationshipType) else relationship
        if extra:
            return f"{rel}:{source_id}->{target_id}:{extra}"
        return f"{rel}:{source_id}->{target_id}"


def _format_traceback(exc: Exception) -> str:
    """Format an exception traceback for logging."""
    import traceback

    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


from dataclasses import dataclass as _dataclass


@_dataclass
class IncrementalGraphResult:
    """Result of an incremental graph update."""

    graph: RepositoryGraph
    added_files: int
    changed_files: int
    deleted_files: int
    preserved_files: int
    full_rebuild: bool = False
