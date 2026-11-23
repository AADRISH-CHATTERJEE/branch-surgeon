"""Hybrid ranking: semantic similarity + repository graph signals.

Deterministic. No AI. Optional graph service — semantic-only when absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from refactory.github.models import PullRequest
from refactory.retrieval.models import (
    EntityKind,
    RankedContext,
    RankedContextEntry,
    RetrievedFile,
    RetrievedSymbol,
    SearchResult,
)

if TYPE_CHECKING:
    from refactory.graph.service import RepositoryGraphService
    from refactory.retrieval.service import RetrievalService


@dataclass
class _Accumulator:
    file_path: str
    module_name: str = ""
    semantic: float = 0.0
    graph: float = 0.0
    reasons: list[str] = field(default_factory=list)
    best_symbol: str | None = None
    kind: EntityKind | None = None

    def add_reason(self, reason: str) -> None:
        if reason not in self.reasons:
            self.reasons.append(reason)


class HybridRanker:
    """Combine embedding similarity with graph/import/package proximity."""

    def __init__(
        self,
        retrieval: "RetrievalService",
        graph: "RepositoryGraphService | None" = None,
    ) -> None:
        self._retrieval = retrieval
        self._graph = graph

    def rank(
        self,
        pull_request: PullRequest,
        *,
        query: str,
        root: Path | str | None = None,
        top_k: int = 12,
        max_symbols: int = 16,
        max_graph_depth: int = 3,
        changed_paths: list[str] | None = None,
    ) -> RankedContext:
        changed = [
            p.replace("\\", "/")
            for p in (changed_paths or [f.path for f in pull_request.changed_files])
            if p
        ]
        acc: dict[str, _Accumulator] = {}

        def bucket(path: str) -> _Accumulator:
            key = path.replace("\\", "/")
            item = acc.get(key)
            if item is None:
                item = _Accumulator(file_path=key, module_name=Path(key).stem)
                acc[key] = item
            return item

        for path in changed:
            item = bucket(path)
            item.graph = max(item.graph, 1.0)
            item.add_reason("changed")

        semantic: SearchResult | None = None
        if query.strip():
            try:
                semantic = self._retrieval.search(query, top_k=top_k, root=root)
            except Exception:  # noqa: BLE001
                semantic = None

        symbols: list[RetrievedSymbol] = []
        if semantic is not None:
            symbols = list(semantic.hits[:max_symbols])
            for hit in symbols:
                item = bucket(hit.file_path)
                item.semantic = max(item.semantic, hit.score)
                item.module_name = hit.module_name or item.module_name
                item.best_symbol = hit.symbol or item.best_symbol
                item.kind = hit.kind
                item.add_reason("semantic")

        for seed in changed:
            try:
                related = self._retrieval.related_files(seed, top_k=top_k, root=root)
            except Exception:  # noqa: BLE001
                related = []
            for rel in related:
                if not isinstance(rel, RetrievedFile):
                    continue
                item = bucket(rel.file_path)
                item.semantic = max(item.semantic, rel.score)
                item.module_name = rel.module_name or item.module_name
                item.best_symbol = rel.best_symbol or item.best_symbol
                item.kind = rel.best_kind or item.kind
                item.add_reason("related_embedding")

        if self._graph is not None:
            try:
                self._graph.graph()
            except Exception:  # noqa: BLE001
                pass
            else:
                self._apply_graph_signals(
                    acc,
                    changed,
                    max_depth=max_graph_depth,
                    bucket=bucket,
                )

        entries: list[RankedContextEntry] = []
        for item in acc.values():
            if item.file_path in changed and len(item.reasons) == 1:
                # Keep changed files even without extra signals
                pass
            score = round(0.55 * item.semantic + 0.45 * item.graph, 6)
            if score <= 0 and "changed" not in item.reasons:
                continue
            if "changed" in item.reasons:
                score = max(score, 0.99)
            entries.append(
                RankedContextEntry(
                    file_path=item.file_path,
                    module_name=item.module_name,
                    score=score,
                    semantic_score=round(item.semantic, 6),
                    graph_score=round(item.graph, 6),
                    reasons=sorted(item.reasons),
                    best_symbol=item.best_symbol,
                    kind=item.kind,
                )
            )

        entries.sort(key=lambda e: (-e.score, e.file_path))
        return RankedContext(
            query=query,
            entries=entries[:top_k],
            symbols=symbols[:max_symbols],
        )

    def _apply_graph_signals(
        self,
        acc: dict[str, _Accumulator],
        changed: list[str],
        *,
        max_depth: int,
        bucket,
    ) -> None:
        assert self._graph is not None
        g = self._graph.graph()

        for seed in changed:
            seed_norm = seed.replace("\\", "/")
            seed_mod = Path(seed_norm).stem
            seed_pkg = "/".join(seed_norm.split("/")[:-1])

            # Import / reverse-import proximity
            try:
                deps = self._graph.dependencies_of(seed_norm)
                rev = self._graph.reverse_dependencies(seed_norm)
                affected = self._graph.affected_files(seed_norm)
            except Exception:  # noqa: BLE001
                deps, rev, affected = [], [], []

            for path in deps:
                item = bucket(path)
                item.graph = max(item.graph, 0.85)
                item.add_reason("imports")
            for path in rev:
                item = bucket(path)
                item.graph = max(item.graph, 0.8)
                item.add_reason("imported_by")
            for path in affected[: max(1, max_depth * 3)]:
                item = bucket(path)
                dist = self._graph.graph_distance(seed_norm, path, max_depth=max_depth)
                if dist is None:
                    boost = 0.35
                else:
                    boost = max(0.2, 0.9 - 0.15 * dist)
                    item.add_reason(f"graph_dist:{dist}")
                item.graph = max(item.graph, boost)
                item.add_reason("impact")

            # Same package / module proximity over indexed files
            for path, file_id in g.file_index.items():
                if path == seed_norm:
                    continue
                item = bucket(path)
                node = g.nodes.get(file_id)
                mod = (node.module_name if node else Path(path).stem) or ""
                pkg = "/".join(path.split("/")[:-1])
                if mod == seed_mod:
                    item.graph = max(item.graph, 0.7)
                    item.add_reason("same_module")
                if seed_pkg and pkg == seed_pkg:
                    item.graph = max(item.graph, 0.55)
                    item.add_reason("same_package")

            # Same class ownership: symbols defined in changed file referenced elsewhere
            try:
                defined = self._graph.defined_symbols_in_file(seed_norm)
            except Exception:  # noqa: BLE001
                defined = []
            for sym in defined:
                if sym.kind.value not in {"class", "function", "method"}:
                    continue
                for ref_path in self._graph.files_referencing_symbol(sym.name):
                    if ref_path == seed_norm:
                        continue
                    item = bucket(ref_path)
                    item.graph = max(item.graph, 0.65)
                    item.add_reason("same_class" if sym.kind.value == "class" else "symbol_ref")
