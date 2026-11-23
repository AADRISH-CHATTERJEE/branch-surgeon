"""ImpactAnalysisService — local blast-radius estimation.

Reuses IndexerService (load-only), RepositoryGraphService, ParserService,
and RetrievalService. Never rebuilds the repository index. Independent of
ReviewEngine / PromptBuilder / AI Gateway / CommitService /
RepositoryAnalysisService / CodeSearchService.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from refactory.core.exceptions import IndexError_
from refactory.git.service import GitService
from refactory.graph.models import NodeKind
from refactory.graph.service import RepositoryGraphService
from refactory.impact.models import (
    DependencyChain,
    ImpactedLocation,
    ImpactReport,
    ImpactTargetKind,
    RiskLevel,
)
from refactory.indexer.models import RepositoryIndex
from refactory.indexer.service import IndexerService
from refactory.parser.service import ParserService
from refactory.retrieval.service import RetrievalService

if TYPE_CHECKING:
    from loguru import Logger


@dataclass
class _ImpactCache:
    root: Path
    index_stamp: str
    index: RepositoryIndex
    graph_ready: bool = False
    orphan_paths: set[str] = field(default_factory=set)
    cycle_membership: dict[str, tuple[str, ...]] = field(default_factory=dict)


class ImpactAnalysisService:
    """Estimate impacted locations for a file, class, function, or symbol."""

    def __init__(
        self,
        logger: "Logger",
        git_service: GitService,
        indexer_service: IndexerService,
        graph_service: RepositoryGraphService,
        parser_service: ParserService,
        retrieval_service: RetrievalService,
        *,
        max_depth: int = 8,
        semantic_top_k: int = 8,
    ) -> None:
        self._logger = logger
        self._git = git_service
        self._indexer = indexer_service
        self._graph = graph_service
        self._parser = parser_service
        self._retrieval = retrieval_service
        self._max_depth = max(1, max_depth)
        self._semantic_top_k = max(1, semantic_top_k)
        self._cache: _ImpactCache | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, target: str) -> ImpactReport:
        """Analyze impact for a file path or symbol name."""
        cache = self._ensure_ready()
        resolved = self._resolve_target(target, cache)
        report = ImpactReport(
            target=target.strip(),
            target_kind=resolved.kind,
            resolved_paths=list(resolved.paths),
            resolved_symbols=list(resolved.symbols),
        )

        if not resolved.paths and not resolved.symbols:
            report.notes.append(
                f"Target '{target}' was not found in the cached index/graph."
            )
            report.confidence = 0.1
            report.risk_level = RiskLevel.LOW
            return report

        # Touch parser metadata (reuse without reparsing the tree).
        _ = self._parser.supported_languages()

        for path in resolved.paths:
            self._accumulate_file_impact(report, path, cache)

        for symbol in resolved.symbols:
            self._accumulate_symbol_impact(report, symbol, cache)

        self._add_semantic_neighbors(report, resolved.paths, cache.root)
        self._finalize(report, cache)
        return report

    def analyze_file(self, path: str) -> ImpactReport:
        return self.analyze(path)

    def analyze_symbol(self, symbol: str) -> ImpactReport:
        return self.analyze(symbol)

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    @dataclass
    class _Resolved:
        kind: ImpactTargetKind
        paths: list[str] = field(default_factory=list)
        symbols: list[str] = field(default_factory=list)

    def _resolve_target(self, target: str, cache: _ImpactCache) -> "_Resolved":
        text = (target or "").strip()
        if not text:
            return self._Resolved(kind=ImpactTargetKind.UNKNOWN)

        norm = self._norm(text)
        # File-like target.
        if "/" in norm or "\\" in text or norm.endswith(".py"):
            node = self._graph.find_file(norm)
            if node is not None and node.file_path:
                return self._Resolved(
                    kind=ImpactTargetKind.FILE,
                    paths=[self._norm(node.file_path)],
                )
            # Deleted / renamed relative to disk but still in index hashes.
            if any(self._norm(f.relative_path) == norm for f in cache.index.files):
                return self._Resolved(kind=ImpactTargetKind.FILE, paths=[norm])
            # Basename unique match already handled by find_file; try exact index.
            matches = [
                self._norm(f.relative_path)
                for f in cache.index.files
                if self._norm(f.relative_path).endswith("/" + Path(norm).name)
                or self._norm(f.relative_path) == Path(norm).name
            ]
            if len(matches) == 1:
                return self._Resolved(kind=ImpactTargetKind.FILE, paths=matches)
            if matches:
                return self._Resolved(kind=ImpactTargetKind.FILE, paths=sorted(set(matches)))

        parent, name = self._split_qualified(text)
        matches = self._graph.find_symbol(name)
        if parent:
            matches = [m for m in matches if (m.parent_name or "").lower() == parent.lower()]

        if matches:
            kind = ImpactTargetKind.SYMBOL
            kinds = {m.kind for m in matches}
            if kinds == {NodeKind.CLASS}:
                kind = ImpactTargetKind.CLASS
            elif kinds <= {NodeKind.FUNCTION, NodeKind.NESTED_FUNCTION}:
                kind = ImpactTargetKind.FUNCTION
            elif NodeKind.METHOD in kinds:
                kind = ImpactTargetKind.METHOD
            paths = sorted({self._norm(m.file_path) for m in matches if m.file_path})
            symbols = sorted(
                {
                    f"{m.parent_name}.{m.name}" if m.parent_name else m.name
                    for m in matches
                }
            )
            return self._Resolved(kind=kind, paths=paths, symbols=symbols)

        # Index fallback (renames / symbols not yet in graph table).
        index_hits = [
            s
            for s in cache.index.symbols
            if s.name == name and (not parent or (s.parent or "").lower() == parent.lower())
        ]
        if index_hits:
            paths = sorted({self._norm(s.file_path) for s in index_hits})
            return self._Resolved(
                kind=ImpactTargetKind.SYMBOL,
                paths=paths,
                symbols=[name],
            )

        return self._Resolved(kind=ImpactTargetKind.UNKNOWN)

    # ------------------------------------------------------------------
    # Accumulation
    # ------------------------------------------------------------------

    def _accumulate_file_impact(
        self,
        report: ImpactReport,
        path: str,
        cache: _ImpactCache,
    ) -> None:
        path = self._norm(path)
        if path in cache.orphan_paths:
            report.orphan_target = True
            report.notes.append(f"'{path}' appears to be an orphan module (no import edges).")

        if path in cache.cycle_membership:
            report.in_cycle = True
            report.cycle_files = sorted(set(report.cycle_files) | set(cache.cycle_membership[path]))

        try:
            deps = [self._norm(p) for p in self._graph.dependencies_of(path)]
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("dependencies_of failed for {}: {}", path, exc)
            deps = []
        for dep in deps:
            loc = ImpactedLocation(
                path=dep,
                kind="dependency",
                distance=1,
                confidence=0.9,
                reasons=["direct_dependency", "imports"],
            )
            report.direct_dependencies.append(loc)
            report.imports.append(loc.model_copy())

        try:
            importers = [self._norm(p) for p in self._graph.reverse_dependencies(path)]
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("reverse_dependencies failed for {}: {}", path, exc)
            importers = []
        for importer in importers:
            loc = ImpactedLocation(
                path=importer,
                kind="importer",
                distance=1,
                confidence=0.88,
                reasons=[f"imports {path}", "imported_by"],
            )
            report.importers.append(loc)
            report.direct_impact.append(loc.model_copy(update={"kind": "direct"}))

        try:
            affected = [self._norm(p) for p in self._graph.affected_files(path)]
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("affected_files failed for {}: {}", path, exc)
            affected = []
        direct_set = {self._norm(i.path) for i in report.direct_impact} | {path}
        for other in affected:
            if other in direct_set:
                continue
            dist = self._safe_distance(path, other)
            loc = ImpactedLocation(
                path=other,
                kind="transitive",
                distance=dist,
                confidence=max(0.25, 0.85 - 0.1 * (dist or self._max_depth)),
                reasons=["transitive_impact"],
            )
            report.transitive_dependencies.append(loc)
            report.indirect_impact.append(loc.model_copy(update={"kind": "indirect"}))

        try:
            for callee in self._graph.callees_of(path):
                report.callees.append(
                    ImpactedLocation(
                        path=path,
                        symbol=callee,
                        kind="callee",
                        distance=1,
                        confidence=0.8,
                        reasons=["callee"],
                    )
                )
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("callees_of failed for {}: {}", path, exc)

        # Related files via graph neighbors (direct deps + importers).
        for neighbor in sorted(set(deps) | set(importers)):
            report.related_files.append(
                ImpactedLocation(
                    path=neighbor,
                    kind="related",
                    distance=1,
                    confidence=0.75,
                    reasons=["graph_related"],
                )
            )

        # Dependency chains (default depth 3): outbound imports + inbound dependents.
        report.dependency_chains.extend(
            self._dependency_chains(path, direction="imports", max_depth=3)
        )
        report.dependency_chains.extend(
            self._dependency_chains(path, direction="imported_by", max_depth=3)
        )

    def _accumulate_symbol_impact(
        self,
        report: ImpactReport,
        symbol: str,
        cache: _ImpactCache,
    ) -> None:
        bare = symbol.rsplit(".", 1)[-1]
        try:
            callers = [self._norm(p) for p in self._graph.callers_of(bare)]
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("callers_of failed for {}: {}", bare, exc)
            callers = []
        for path in callers:
            loc = ImpactedLocation(
                path=path,
                symbol=bare,
                kind="caller",
                distance=1,
                confidence=0.9,
                reasons=["caller"],
            )
            report.callers.append(loc)
            report.direct_impact.append(loc.model_copy(update={"kind": "direct"}))

        try:
            refs = [self._norm(p) for p in self._graph.files_referencing_symbol(bare)]
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("files_referencing_symbol failed for {}: {}", bare, exc)
            refs = []
        known = {self._norm(i.path) for i in report.direct_impact}
        for path in refs:
            if path in known:
                continue
            report.indirect_impact.append(
                ImpactedLocation(
                    path=path,
                    symbol=bare,
                    kind="reference",
                    distance=1,
                    confidence=0.7,
                    reasons=["symbol_reference"],
                )
            )

        # Inheritance for class-like symbols.
        try:
            bases = self._graph.base_classes_of(bare)
            subs = self._graph.subclasses_of(bare)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("inheritance lookup failed for {}: {}", bare, exc)
            bases, subs = [], []
        for base in bases:
            report.inheritance.append(
                ImpactedLocation(
                    path="",
                    symbol=base,
                    kind="base_class",
                    confidence=0.85,
                    reasons=["inherits_from"],
                )
            )
        for sub in subs:
            report.inheritance.append(
                ImpactedLocation(
                    path="",
                    symbol=sub,
                    kind="subclass",
                    confidence=0.85,
                    reasons=["subclass"],
                )
            )
            # Subclass definitions expand direct impact.
            for match in self._graph.find_symbol(sub):
                if match.file_path:
                    report.direct_impact.append(
                        ImpactedLocation(
                            path=self._norm(match.file_path),
                            symbol=sub,
                            kind="direct",
                            distance=1,
                            confidence=0.8,
                            reasons=["subclass"],
                        )
                    )

    def _add_semantic_neighbors(
        self,
        report: ImpactReport,
        paths: list[str],
        root: Path,
    ) -> None:
        for seed in paths:
            try:
                neighbors = self._retrieval.impacted_files(
                    seed,
                    top_k=self._semantic_top_k,
                    root=root,
                )
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("semantic neighbors skipped for {}: {}", seed, exc)
                neighbors = []
            for item in neighbors:
                path = self._norm(item.file_path)
                if path == seed:
                    continue
                report.semantic_neighbors.append(
                    ImpactedLocation(
                        path=path,
                        symbol=item.best_symbol,
                        kind="semantic",
                        confidence=round(float(item.score), 4),
                        reasons=["semantic_neighbor"],
                    )
                )
                # Semantic neighbors stay in their own bucket — structural
                # Direct/Indirect Impact must not be driven by embeddings.

    def _finalize(self, report: ImpactReport, cache: _ImpactCache) -> None:
        report.direct_impact = self._dedupe_locations(report.direct_impact)
        report.indirect_impact = self._dedupe_locations(
            [loc for loc in report.indirect_impact if loc.path not in {d.path for d in report.direct_impact}]
        )
        report.direct_dependencies = self._dedupe_locations(report.direct_dependencies)
        report.transitive_dependencies = self._dedupe_locations(report.transitive_dependencies)
        report.imports = self._dedupe_locations(report.imports)
        report.importers = self._dedupe_locations(report.importers)
        report.callers = self._dedupe_locations(report.callers)
        report.callees = self._dedupe_locations(report.callees)
        report.related_files = self._dedupe_locations(report.related_files)
        report.semantic_neighbors = self._dedupe_locations(report.semantic_neighbors)
        report.dependency_chains = self._dedupe_chains(report.dependency_chains)

        files: set[str] = set(report.resolved_paths)
        symbols: set[str] = set(report.resolved_symbols)
        for bucket in (
            report.direct_impact,
            report.indirect_impact,
            report.direct_dependencies,
            report.imports,
            report.importers,
            report.callers,
            report.callees,
            report.semantic_neighbors,
        ):
            for loc in bucket:
                if loc.path:
                    files.add(self._norm(loc.path))
                if loc.symbol:
                    symbols.add(loc.symbol)
        for loc in report.inheritance:
            if loc.symbol:
                symbols.add(loc.symbol)

        report.impacted_files = sorted(files)
        report.impacted_symbols = sorted(symbols)
        report.confidence = self._confidence(report)
        report.risk_level = self._risk(report)

    # ------------------------------------------------------------------
    # Cache / load-only index
    # ------------------------------------------------------------------

    def _ensure_ready(self) -> _ImpactCache:
        root = self._git.get_root_path()
        index = self._load_index_only(root)
        stamp = (
            f"{index.summary.timestamp.isoformat()}|"
            f"{index.summary.total_indexed_files}|"
            f"{len(index.symbols)}|"
            f"{len(index.file_hashes)}"
        )
        if (
            self._cache is not None
            and self._cache.root == root
            and self._cache.index_stamp == stamp
            and self._cache.graph_ready
        ):
            return self._cache

        self._graph.build_graph(index)
        orphans = {self._norm(o.file_path) for o in self._graph.orphan_modules()}
        cycles: dict[str, tuple[str, ...]] = {}
        for cycle in self._graph.find_cycles():
            members = tuple(sorted(self._norm(p) for p in cycle.files))
            for path in members:
                cycles[path] = members

        self._cache = _ImpactCache(
            root=root,
            index_stamp=stamp,
            index=index,
            graph_ready=True,
            orphan_paths=orphans,
            cycle_membership=cycles,
        )
        self._logger.info(
            "Impact analysis ready — {} file(s), {} symbol(s) (index load-only)",
            len(index.files),
            len(index.symbols),
        )
        return self._cache

    def _load_index_only(self, root: Path) -> RepositoryIndex:
        existing = self._indexer.load_index(root)
        if existing is not None:
            return existing
        last = self._indexer.get_last_index()
        if last is not None:
            return last
        raise IndexError_(
            "No cached repository index found. Run `refactory index` first "
            "(ImpactAnalysisService never rebuilds the repository)."
        )

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------

    def _confidence(self, report: ImpactReport) -> float:
        if report.target_kind == ImpactTargetKind.UNKNOWN:
            return 0.1
        signals = 0
        if report.direct_impact:
            signals += 2
        if report.indirect_impact:
            signals += 1
        if report.callers or report.callees:
            signals += 1
        if report.semantic_neighbors:
            signals += 1
        if report.inheritance:
            signals += 1
        if report.orphan_target and not report.direct_impact:
            return 0.35
        base = 0.45 + 0.1 * signals
        if report.in_cycle:
            base = min(base + 0.05, 0.95)
        return round(min(base, 0.98), 4)

    def _risk(self, report: ImpactReport) -> RiskLevel:
        """Graph-derived risk: fan-in/out, callers, centrality proxies, domain cues."""
        fan_in = len(report.importers) or len(
            [i for i in report.direct_impact if i.kind in {"direct", "importer"}]
        )
        fan_out = len(report.direct_dependencies) or len(report.imports)
        callers = len(report.callers)
        callees = len(report.callees)
        direct = len(report.direct_impact)
        indirect = len(report.indirect_impact)
        total = len(report.impacted_files)
        # Rough centrality: dependents + callers (inbound) plus fan-out.
        centrality = fan_in + callers + min(fan_out, 5)

        path_blob = " ".join(report.resolved_paths).lower()
        security_sensitive = any(
            token in path_blob
            for token in (
                "auth",
                "security",
                "crypto",
                "jwt",
                "password",
                "oauth",
                "session",
                "token",
                "secret",
                "credential",
            )
        )
        entry_point = any(
            Path(p).stem.lower() in {"main", "app", "cli", "wsgi", "asgi", "__main__"}
            or Path(p).name.lower() in {"__main__.py"}
            for p in report.resolved_paths
        )

        if report.orphan_target and direct == 0 and indirect == 0 and callers == 0:
            return RiskLevel.LOW

        if report.in_cycle and (direct + indirect) >= 3:
            return RiskLevel.CRITICAL
        if security_sensitive and (fan_in >= 2 or callers >= 2 or centrality >= 4):
            return RiskLevel.HIGH
        if entry_point and (fan_in >= 1 or total >= 3):
            return RiskLevel.HIGH
        if total >= 20 or direct >= 10 or centrality >= 12:
            return RiskLevel.CRITICAL
        if total >= 8 or direct >= 4 or fan_in >= 4 or callers >= 4 or centrality >= 6:
            return RiskLevel.HIGH
        if total >= 3 or direct >= 2 or fan_in >= 2 or callers >= 2 or fan_out >= 4:
            return RiskLevel.MEDIUM
        if total <= 1 and fan_in == 0 and callers == 0 and callees <= 1:
            return RiskLevel.LOW
        return RiskLevel.LOW

    def _dependency_chains(
        self,
        seed: str,
        *,
        direction: str,
        max_depth: int = 3,
    ) -> list[DependencyChain]:
        """DFS chains from ``seed``; skips cycles and duplicate node revisits on a path."""
        seed = self._norm(seed)
        depth_limit = max(1, max_depth)
        chains: list[DependencyChain] = []

        def neighbors(path: str) -> list[str]:
            try:
                if direction == "imports":
                    return [self._norm(p) for p in self._graph.dependencies_of(path)]
                return [self._norm(p) for p in self._graph.reverse_dependencies(path)]
            except Exception:  # noqa: BLE001
                return []

        def walk(path: str, trail: list[str]) -> None:
            if len(trail) > depth_limit:
                return
            nxts = neighbors(path)
            if not nxts:
                if len(trail) >= 2:
                    chains.append(
                        DependencyChain(nodes=list(trail), relationship=direction)
                    )
                return
            extended = False
            for nxt in nxts:
                if nxt in trail:
                    continue
                extended = True
                walk(nxt, trail + [nxt])
            if not extended and len(trail) >= 2:
                chains.append(DependencyChain(nodes=list(trail), relationship=direction))

        walk(seed, [seed])
        # Prefer longer informative chains; cap volume.
        chains.sort(key=lambda c: (-len(c.nodes), c.nodes))
        return chains[:12]

    @staticmethod
    def _dedupe_chains(chains: list[DependencyChain]) -> list[DependencyChain]:
        seen: set[tuple[str, ...]] = set()
        unique: list[DependencyChain] = []
        for chain in chains:
            key = tuple(chain.nodes)
            if key in seen or len(key) < 2:
                continue
            seen.add(key)
            unique.append(chain)
        return unique

    def _safe_distance(self, source: str, target: str) -> int | None:
        try:
            return self._graph.graph_distance(source, target, max_depth=self._max_depth)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _dedupe_locations(items: list[ImpactedLocation]) -> list[ImpactedLocation]:
        best: dict[tuple[str, str | None, str], ImpactedLocation] = {}
        for item in items:
            key = (item.path, item.symbol, item.kind)
            existing = best.get(key)
            if existing is None or item.confidence > existing.confidence:
                best[key] = item
        return sorted(best.values(), key=lambda i: (-i.confidence, i.path, i.symbol or ""))

    @staticmethod
    def _split_qualified(symbol: str) -> tuple[str | None, str]:
        text = (symbol or "").strip()
        if not text:
            return None, ""
        if "." in text and not text.endswith(".py"):
            parent, name = text.rsplit(".", 1)
            if parent and name:
                return parent, name
        return None, text

    @staticmethod
    def _norm(path: str) -> str:
        return path.replace("\\", "/").lstrip("./")
