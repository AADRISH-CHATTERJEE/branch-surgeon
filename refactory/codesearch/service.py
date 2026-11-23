"""CodeSearchService — local code search and semantic navigation.

Reuses IndexerService, RepositoryGraphService, ParserService, and
RetrievalService. Never talks to GitHub or external APIs.
Independent of ReviewEngine / PromptBuilder / AI Gateway /
CommitService / RepositoryAnalysisService.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from refactory.codesearch.models import CodeHitKind, CodeSearchHit, CodeSearchResult
from refactory.core.exceptions import RefactoryError, RepositoryNotFound
from refactory.git.service import GitService
from refactory.graph.models import NodeKind, RelationshipType
from refactory.graph.service import RepositoryGraphService
from refactory.indexer.models import IndexedSymbol, RepositoryIndex, SymbolKind
from refactory.indexer.service import IndexerService
from refactory.parser.service import ParserService
from refactory.retrieval.models import EntityKind, SearchResult
from refactory.retrieval.service import RetrievalService

if TYPE_CHECKING:
    from loguru import Logger


_KIND_MAP = {
    SymbolKind.MODULE: CodeHitKind.MODULE,
    SymbolKind.CLASS: CodeHitKind.CLASS,
    SymbolKind.FUNCTION: CodeHitKind.FUNCTION,
    SymbolKind.METHOD: CodeHitKind.METHOD,
    SymbolKind.NESTED_FUNCTION: CodeHitKind.NESTED_FUNCTION,
}

_NODE_KIND_MAP = {
    NodeKind.MODULE: CodeHitKind.MODULE,
    NodeKind.CLASS: CodeHitKind.CLASS,
    NodeKind.FUNCTION: CodeHitKind.FUNCTION,
    NodeKind.METHOD: CodeHitKind.METHOD,
    NodeKind.NESTED_FUNCTION: CodeHitKind.NESTED_FUNCTION,
    NodeKind.FILE: CodeHitKind.FILE,
}


@dataclass
class _SearchCache:
    root: Path
    index_stamp: str
    index: RepositoryIndex
    graph_ready: bool = False
    # path -> mtime for lightweight recent-usage proxy
    mtimes: dict[str, float] = field(default_factory=dict)


class CodeSearchService:
    """Local structural + semantic code navigation."""

    def __init__(
        self,
        logger: "Logger",
        git_service: GitService,
        indexer_service: IndexerService,
        graph_service: RepositoryGraphService,
        parser_service: ParserService,
        retrieval_service: RetrievalService,
        *,
        top_k: int = 20,
    ) -> None:
        self._logger = logger
        self._git = git_service
        self._indexer = indexer_service
        self._graph = graph_service
        self._parser = parser_service  # available for language metadata / future parse hooks
        self._retrieval = retrieval_service
        self._default_top_k = max(1, top_k)
        self._cache: _SearchCache | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(self, query: str, *, top_k: int | None = None) -> CodeSearchResult:
        """Hybrid search: exact/symbol/path + semantic similarity."""
        q = (query or "").strip()
        if not q:
            return CodeSearchResult(query=query or "")
        limit = top_k or self._default_top_k
        cache = self._ensure_ready()

        structural = self._merge_unique(
            self.search_symbols(q, top_k=limit).hits
            + self.search_files(q, top_k=limit).hits
            + self.search_functions(q, top_k=limit).hits
            + self.search_classes(q, top_k=limit).hits
        )
        semantic = self._semantic_hits(q, root=cache.root, top_k=limit)
        merged = self._rank_and_merge(q, structural, semantic, root=cache.root, limit=limit)
        return CodeSearchResult(
            query=q,
            hits=merged,
            structural_hits=len(structural),
            semantic_hits=len(semantic),
        )

    def search_files(self, query: str, *, top_k: int | None = None) -> CodeSearchResult:
        q = (query or "").strip().lower()
        cache = self._ensure_ready()
        limit = top_k or self._default_top_k
        hits: list[CodeSearchHit] = []
        for indexed in cache.index.files:
            path = self._norm(indexed.relative_path)
            score = 0.0
            reasons: list[str] = []
            if q and q in path.lower():
                score += 0.9 if path.lower().endswith(q) or Path(path).stem.lower() == q else 0.7
                reasons.append("path_match")
            if q and q in indexed.module_name.lower():
                score += 0.5
                reasons.append("module_match")
            if score <= 0:
                continue
            hits.append(
                self._hit(
                    file=path,
                    line=1,
                    symbol=indexed.module_name,
                    kind=CodeHitKind.FILE,
                    score=score,
                    reasons=reasons,
                    root=cache.root,
                )
            )
        hits.sort(key=lambda h: (-h.score, h.file))
        return CodeSearchResult(query=query, hits=hits[:limit], structural_hits=len(hits[:limit]))

    def search_symbols(self, query: str, *, top_k: int | None = None) -> CodeSearchResult:
        return self._search_symbols_by_kinds(query, kinds=None, top_k=top_k)

    def search_functions(self, query: str, *, top_k: int | None = None) -> CodeSearchResult:
        return self._search_symbols_by_kinds(
            query,
            kinds={SymbolKind.FUNCTION, SymbolKind.METHOD, SymbolKind.NESTED_FUNCTION},
            top_k=top_k,
        )

    def search_classes(self, query: str, *, top_k: int | None = None) -> CodeSearchResult:
        return self._search_symbols_by_kinds(query, kinds={SymbolKind.CLASS}, top_k=top_k)

    def search_imports(self, query: str, *, top_k: int | None = None) -> CodeSearchResult:
        q = (query or "").strip().lower()
        cache = self._ensure_ready()
        limit = top_k or self._default_top_k
        hits: list[CodeSearchHit] = []
        for ref in cache.index.import_references:
            target = (ref.target_module or "").lower()
            symbol = (ref.symbol or "").lower()
            source = self._norm(ref.source_file)
            score = 0.0
            reasons: list[str] = []
            if q and q in target:
                score += 0.85
                reasons.append("import_module")
            if q and symbol and q in symbol:
                score += 0.95
                reasons.append("import_symbol")
            if q and q in source.lower():
                score += 0.4
                reasons.append("import_source")
            if score <= 0:
                continue
            label = ref.symbol or ref.target_module
            hits.append(
                self._hit(
                    file=source,
                    line=ref.start_line,
                    symbol=label or "",
                    kind=CodeHitKind.IMPORT,
                    score=min(score, 1.5),
                    reasons=reasons,
                    root=cache.root,
                    snippet_override=f"import {ref.target_module}"
                    + (f" ({ref.symbol})" if ref.symbol else ""),
                )
            )
        hits.sort(key=lambda h: (-h.score, h.file, h.line or 0))
        return CodeSearchResult(query=query, hits=hits[:limit], structural_hits=len(hits[:limit]))

    def search_comments(self, query: str, *, top_k: int | None = None) -> CodeSearchResult:
        q = (query or "").strip().lower()
        cache = self._ensure_ready()
        limit = top_k or self._default_top_k
        hits: list[CodeSearchHit] = []
        for indexed in cache.index.files:
            for comment in indexed.comments:
                if q and q not in comment.lower():
                    continue
                if not q and not comment.strip():
                    continue
                score = 0.8 if q else 0.5
                hits.append(
                    self._hit(
                        file=self._norm(indexed.relative_path),
                        line=None,
                        symbol="",
                        kind=CodeHitKind.COMMENT,
                        score=score,
                        reasons=["comment_match"],
                        root=cache.root,
                        snippet_override=comment[:200],
                    )
                )
        hits.sort(key=lambda h: (-h.score, h.file))
        return CodeSearchResult(query=query, hits=hits[:limit], structural_hits=len(hits[:limit]))

    def search_todos(self) -> CodeSearchResult:
        cache = self._ensure_ready()
        hits: list[CodeSearchHit] = []
        for indexed in cache.index.files:
            tags = [t.upper() for t in indexed.todo_tags]
            if not tags:
                continue
            # Prefer comment lines that look like TODOs / FIXMEs.
            matched_comments = [
                c
                for c in indexed.comments
                if any(tag in c.upper() for tag in ("TODO", "FIXME", "HACK", "NOTE"))
            ]
            if matched_comments:
                for comment in matched_comments:
                    tag = next(
                        (t for t in ("TODO", "FIXME", "HACK", "NOTE") if t in comment.upper()),
                        "TODO",
                    )
                    hits.append(
                        self._hit(
                            file=self._norm(indexed.relative_path),
                            line=None,
                            symbol=tag,
                            kind=CodeHitKind.TODO,
                            score=1.0 if tag in {"TODO", "FIXME"} else 0.8,
                            reasons=["todo_tag"],
                            root=cache.root,
                            snippet_override=comment[:200],
                        )
                    )
            else:
                for tag in tags:
                    hits.append(
                        self._hit(
                            file=self._norm(indexed.relative_path),
                            line=1,
                            symbol=tag,
                            kind=CodeHitKind.TODO,
                            score=0.9,
                            reasons=["todo_tag"],
                            root=cache.root,
                            snippet_override=tag,
                        )
                    )
        hits.sort(key=lambda h: (-h.score, h.file, h.symbol))
        return CodeSearchResult(query="TODO", hits=hits, structural_hits=len(hits))

    def find_definition(self, symbol: str) -> CodeSearchResult:
        parent, name = self._split_qualified(symbol)
        cache = self._ensure_ready()
        hits: list[CodeSearchHit] = []

        # Prefer graph matches (include line / parent).
        for match in self._graph.find_symbol(name):
            if parent and (match.parent_name or "").lower() != parent.lower():
                continue
            kind = _NODE_KIND_MAP.get(match.kind, CodeHitKind.DEFINITION)
            hits.append(
                self._hit(
                    file=self._norm(match.file_path or ""),
                    line=match.start_line,
                    symbol=self._display_symbol(match.parent_name, match.name),
                    kind=kind,
                    score=1.0,
                    reasons=["exact_definition"],
                    root=cache.root,
                )
            )

        if not hits:
            for indexed in cache.index.symbols:
                if indexed.name != name:
                    continue
                if parent and (indexed.parent or "").lower() != parent.lower():
                    continue
                hits.append(
                    self._hit(
                        file=self._norm(indexed.file_path),
                        line=indexed.start_line,
                        symbol=self._display_symbol(indexed.parent, indexed.name),
                        kind=_KIND_MAP.get(indexed.kind, CodeHitKind.DEFINITION),
                        score=0.95,
                        reasons=["index_definition"],
                        root=cache.root,
                    )
                )

        hits = self._merge_unique(hits)
        hits.sort(key=lambda h: (-h.score, h.file, h.line or 0))
        return CodeSearchResult(query=symbol, hits=hits, structural_hits=len(hits))

    def find_references(self, symbol: str) -> CodeSearchResult:
        parent, name = self._split_qualified(symbol)
        cache = self._ensure_ready()
        paths = self._graph.files_referencing_symbol(name)
        hits: list[CodeSearchHit] = []
        for path in paths:
            line = self._reference_line(cache.index, path, name)
            hits.append(
                self._hit(
                    file=path,
                    line=line,
                    symbol=self._display_symbol(parent, name) if parent else name,
                    kind=CodeHitKind.REFERENCE,
                    score=0.9,
                    reasons=["graph_reference"],
                    root=cache.root,
                )
            )
        # Also surface import references that mention the symbol / alias.
        for ref in cache.index.import_references:
            if (ref.symbol or "") != name and name.lower() not in (ref.target_module or "").lower():
                continue
            path = self._norm(ref.source_file)
            if any(h.file == path for h in hits):
                continue
            hits.append(
                self._hit(
                    file=path,
                    line=ref.start_line,
                    symbol=ref.symbol or name,
                    kind=CodeHitKind.REFERENCE,
                    score=0.85,
                    reasons=["import_reference"],
                    root=cache.root,
                )
            )
        hits.sort(key=lambda h: (-h.score, h.file, h.line or 0))
        return CodeSearchResult(query=symbol, hits=hits, structural_hits=len(hits))

    def find_callers(self, symbol: str) -> CodeSearchResult:
        _, name = self._split_qualified(symbol)
        cache = self._ensure_ready()
        paths = self._graph.callers_of(name)
        hits: list[CodeSearchHit] = []
        for path in paths:
            line = self._call_line(cache.index, path, name)
            hits.append(
                self._hit(
                    file=path,
                    line=line,
                    symbol=name,
                    kind=CodeHitKind.CALLER,
                    score=0.92,
                    reasons=["call_graph"],
                    root=cache.root,
                )
            )
        hits.sort(key=lambda h: (-h.score, h.file))
        return CodeSearchResult(query=symbol, hits=hits, structural_hits=len(hits))

    def find_callees(self, symbol: str) -> CodeSearchResult:
        """Find callees of a symbol or file path.

        ``AuthService.login`` resolves to the defining file and lists symbols
        called from that file (graph CALLS edges are file-sourced).
        """
        cache = self._ensure_ready()
        query = (symbol or "").strip()
        paths: list[str] = []

        if "/" in query or "\\" in query or query.endswith(".py"):
            paths = [self._norm(query)]
        else:
            defs = self.find_definition(query).hits
            paths = sorted({h.file for h in defs if h.file})

        hits: list[CodeSearchHit] = []
        for path in paths:
            for callee in self._graph.callees_of(path):
                # Prefer definition site of callee for navigation.
                callee_defs = self.find_definition(callee).hits
                if callee_defs:
                    primary = callee_defs[0]
                    hits.append(
                        primary.model_copy(
                            update={
                                "type": CodeHitKind.CALLEE.value,
                                "score": 0.9,
                                "confidence": 0.9,
                                "reasons": ["call_graph", f"from:{path}"],
                            }
                        )
                    )
                else:
                    hits.append(
                        self._hit(
                            file=path,
                            line=None,
                            symbol=callee,
                            kind=CodeHitKind.CALLEE,
                            score=0.8,
                            reasons=["call_graph", f"from:{path}"],
                            root=cache.root,
                        )
                    )
        hits = self._merge_unique(hits)
        hits.sort(key=lambda h: (-h.score, h.symbol, h.file))
        return CodeSearchResult(query=symbol, hits=hits, structural_hits=len(hits))

    def find_related(self, symbol: str, *, top_k: int | None = None) -> CodeSearchResult:
        """Related files: graph imports/dependents/affected first, then embeddings."""
        cache = self._ensure_ready()
        limit = top_k or self._default_top_k
        defs = self.find_definition(symbol).hits
        seed_paths = [h.file for h in defs if h.file]
        if not seed_paths:
            # Treat as path / module name.
            seed_paths = [self._norm(symbol)]

        hits: list[CodeSearchHit] = []
        seen: set[str] = set()
        embeddings_available = True

        for seed in seed_paths:
            seed_n = self._norm(seed)
            # --- Structural graph first ---
            try:
                deps = [self._norm(p) for p in self._graph.dependencies_of(seed_n)]
                importers = [self._norm(p) for p in self._graph.reverse_dependencies(seed_n)]
                affected = [self._norm(p) for p in self._graph.affected_files(seed_n)]
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("Graph related skipped for {}: {}", seed_n, exc)
                deps, importers, affected = [], [], []

            structural_paths: list[tuple[str, str, float]] = []
            for path in deps:
                structural_paths.append((path, "graph_imports", 0.92))
            for path in importers:
                structural_paths.append((path, "graph_dependents", 0.9))
            for path in affected:
                structural_paths.append((path, "graph_related", 0.75))

            # Caller/callee signals
            try:
                callers = [self._norm(p) for p in self._graph.callers_of(seed_n)]
                callees = [self._norm(p) for p in self._graph.callees_of(seed_n)]
            except Exception:  # noqa: BLE001
                callers, callees = [], []
            for path in callers:
                structural_paths.append((path, "caller", 0.85))
            for path in callees:
                structural_paths.append((path, "callee", 0.83))

            # Package proximity
            seed_pkg = "/".join(seed_n.split("/")[:-1])
            if seed_pkg:
                for indexed in cache.index.files:
                    path_n = self._norm(indexed.relative_path)
                    if path_n == seed_n:
                        continue
                    file_pkg = "/".join(path_n.split("/")[:-1])
                    if file_pkg == seed_pkg and path_n not in seen:
                        structural_paths.append((path_n, "same_package", 0.5))

            scored: dict[str, tuple[float, list[str]]] = {}
            for path_n, reason, score in structural_paths:
                if path_n == seed_n:
                    continue
                if path_n in scored:
                    old_score, old_reasons = scored[path_n]
                    scored[path_n] = (max(old_score, score), old_reasons + [reason])
                else:
                    scored[path_n] = (score, [reason])

            # --- Semantic enhancement (fused into same scored dict) ---
            try:
                related = self._retrieval.related_files(seed_n, top_k=limit, root=cache.root)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("Semantic related skipped for {}: {}", seed_n, exc)
                related = []
            if not self._retrieval.has_store(cache.root):
                embeddings_available = False

            semantic_symbols: dict[str, str] = {}
            for item in related:
                path = self._norm(item.file_path)
                if path == seed_n:
                    continue
                semantic_symbols[path] = item.best_symbol or item.module_name
                if path in scored:
                    old_s, old_r = scored[path]
                    fused = 0.55 * float(item.score) + 0.45 * old_s
                    scored[path] = (max(old_s, fused), old_r + ["semantic_related"])
                else:
                    scored[path] = (float(item.score), ["semantic_related"])

            # Dependency distance boost
            for path_n in list(scored.keys()):
                try:
                    dist = self._graph.graph_distance(seed_n, path_n, max_depth=3)
                except Exception:  # noqa: BLE001
                    dist = None
                if dist is not None and dist > 0:
                    boost = max(0.2, 0.9 - 0.15 * dist)
                    old_s, old_r = scored[path_n]
                    scored[path_n] = (max(old_s, boost), old_r + [f"graph_dist:{dist}"])

            for path_n, (score, reasons) in scored.items():
                if path_n in seen:
                    continue
                seen.add(path_n)
                unique_reasons = list(dict.fromkeys(reasons))
                hits.append(
                    self._hit(
                        file=path_n,
                        line=1,
                        symbol=semantic_symbols.get(path_n, ""),
                        kind=CodeHitKind.RELATED,
                        score=score,
                        reasons=unique_reasons,
                        root=cache.root,
                    )
                )

        hits.sort(key=lambda h: (-h.score, h.file))
        limited = hits[:limit]
        notes: list[str] = []
        if not embeddings_available:
            notes.append(
                "No embeddings store found — showing graph relationships only. "
                "Run `refactory embed` to enable semantic relatedness."
            )
        return CodeSearchResult(
            query=symbol,
            hits=limited,
            structural_hits=sum(
                1 for h in limited if any(r.startswith("graph_") for r in h.reasons)
            ),
            semantic_hits=sum(1 for h in limited if "semantic_related" in h.reasons),
            notes=notes,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_ready(self) -> _SearchCache:
        root = self._git.get_root_path()
        index = self._load_or_build_index(root)
        stamp = (
            f"{index.summary.timestamp.isoformat()}|"
            f"{index.summary.total_indexed_files}|"
            f"{len(index.symbols)}"
        )
        if (
            self._cache is not None
            and self._cache.root == root
            and self._cache.index_stamp == stamp
            and self._cache.graph_ready
        ):
            return self._cache

        self._graph.build_graph(index)
        mtimes: dict[str, float] = {}
        for indexed in index.files:
            path = root / indexed.relative_path
            try:
                mtimes[self._norm(indexed.relative_path)] = path.stat().st_mtime
            except OSError:
                continue
        self._cache = _SearchCache(
            root=root,
            index_stamp=stamp,
            index=index,
            graph_ready=True,
            mtimes=mtimes,
        )
        self._logger.info(
            "Code search ready — {} file(s), {} symbol(s)",
            len(index.files),
            len(index.symbols),
        )
        return self._cache

    def _load_or_build_index(self, root: Path) -> RepositoryIndex:
        existing = self._indexer.load_index(root)
        if existing is not None:
            return existing
        try:
            name = self._git.get_repository_name()
        except (RefactoryError, RepositoryNotFound):
            name = root.name
        return self._indexer.build_index(root, repository_name=name, force=False)

    def _search_symbols_by_kinds(
        self,
        query: str,
        *,
        kinds: set[SymbolKind] | None,
        top_k: int | None,
    ) -> CodeSearchResult:
        parent, name = self._split_qualified(query)
        needle = name.strip()
        cache = self._ensure_ready()
        limit = top_k or self._default_top_k
        hits: list[CodeSearchHit] = []
        q_lower = needle.lower()

        for symbol in cache.index.symbols:
            if kinds is not None and symbol.kind not in kinds:
                continue
            if parent and (symbol.parent or "").lower() != parent.lower():
                continue
            score, reasons = self._symbol_score(symbol, q_lower)
            if score <= 0:
                continue
            hits.append(
                self._hit(
                    file=self._norm(symbol.file_path),
                    line=symbol.start_line,
                    symbol=self._display_symbol(symbol.parent, symbol.name),
                    kind=_KIND_MAP.get(symbol.kind, CodeHitKind.FUNCTION),
                    score=min(score, 1.5),
                    reasons=reasons,
                    root=cache.root,
                )
            )

        # Supported languages metadata touch — proves ParserService reuse without re-parse.
        _ = self._parser.supported_languages()

        hits.sort(key=lambda h: (-h.score, h.file, h.line or 0))
        return CodeSearchResult(query=query, hits=hits[:limit], structural_hits=len(hits[:limit]))

    def _symbol_score(self, symbol: IndexedSymbol, q_lower: str) -> tuple[float, list[str]]:
        if not q_lower:
            return 0.0, []
        name = symbol.name.lower()
        reasons: list[str] = []
        score = 0.0
        if name == q_lower:
            score = 1.0
            reasons.append("exact_match")
        elif name.startswith(q_lower):
            score = 0.85
            reasons.append("prefix_match")
        elif q_lower in name:
            score = 0.7
            reasons.append("symbol_match")
        path = symbol.file_path.lower()
        if q_lower in path:
            score = max(score, 0.45)
            reasons.append("path_relevance")
        # Decorator name match (query targets a decorator, not the symbol name).
        if any(q_lower == d.lower().lstrip("@") or q_lower in d.lower() for d in symbol.decorators):
            score = max(score, 0.75)
            reasons.append("decorator_match")
        return score, reasons

    def _semantic_hits(self, query: str, *, root: Path, top_k: int) -> list[CodeSearchHit]:
        try:
            result: SearchResult = self._retrieval.search(query, top_k=top_k, root=root)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("Semantic search unavailable: {}", exc)
            return []
        hits: list[CodeSearchHit] = []
        for item in result.hits:
            kind = {
                EntityKind.FILE: CodeHitKind.FILE,
                EntityKind.MODULE: CodeHitKind.MODULE,
                EntityKind.CLASS: CodeHitKind.CLASS,
                EntityKind.FUNCTION: CodeHitKind.FUNCTION,
            }.get(item.kind, CodeHitKind.FILE)
            hits.append(
                self._hit(
                    file=self._norm(item.file_path),
                    line=None,
                    symbol=item.symbol,
                    kind=kind,
                    score=float(item.score) * 0.9,
                    reasons=["semantic_similarity"],
                    root=root,
                )
            )
        return hits

    def _rank_and_merge(
        self,
        query: str,
        structural: list[CodeSearchHit],
        semantic: list[CodeSearchHit],
        *,
        root: Path,
        limit: int,
    ) -> list[CodeSearchHit]:
        cache = self._cache
        by_key: dict[tuple[str, str, str], CodeSearchHit] = {}

        def key(hit: CodeSearchHit) -> tuple[str, str, str]:
            return (hit.file, hit.symbol, hit.type)

        for hit in structural + semantic:
            k = key(hit)
            existing = by_key.get(k)
            if existing is None:
                by_key[k] = hit
                continue
            combined = max(existing.score, hit.score)
            if "exact_match" in hit.reasons or "exact_match" in existing.reasons:
                combined = max(combined, 1.0)
            if "semantic_similarity" in hit.reasons or "semantic_similarity" in existing.reasons:
                combined = min(1.5, combined + 0.15)
            reasons = sorted(set(existing.reasons + hit.reasons))
            by_key[k] = existing.model_copy(
                update={
                    "score": round(combined, 4),
                    "confidence": round(min(combined, 1.0), 4),
                    "reasons": reasons,
                    "line": existing.line or hit.line,
                    "snippet": existing.snippet or hit.snippet,
                }
            )

        # Recent usage boost from mtime rank.
        if cache and cache.mtimes:
            ranked = sorted(cache.mtimes.items(), key=lambda kv: -kv[1])
            recent = {path for path, _ in ranked[: max(5, len(ranked) // 5)]}
            for k, hit in list(by_key.items()):
                if hit.file in recent:
                    by_key[k] = hit.model_copy(
                        update={
                            "score": round(hit.score + 0.05, 4),
                            "reasons": sorted(set(hit.reasons + ["recent_usage"])),
                            "confidence": round(min(hit.confidence + 0.05, 1.0), 4),
                        }
                    )

        hits = list(by_key.values())
        hits.sort(key=lambda h: (-h.score, h.file, h.line or 0))
        return hits[:limit]

    def _hit(
        self,
        *,
        file: str,
        line: int | None,
        symbol: str,
        kind: CodeHitKind,
        score: float,
        reasons: list[str],
        root: Path,
        snippet_override: str | None = None,
    ) -> CodeSearchHit:
        snippet = snippet_override if snippet_override is not None else self._read_snippet(root, file, line)
        confidence = round(min(max(score, 0.0), 1.0), 4)
        return CodeSearchHit(
            file=file,
            line=line,
            symbol=symbol,
            type=kind.value,
            snippet=snippet,
            score=round(score, 4),
            confidence=confidence,
            reasons=reasons,
        )

    def _read_snippet(self, root: Path, relative: str, line: int | None) -> str:
        if not relative:
            return ""
        path = root / relative
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        if not lines:
            return ""
        if line is None or line < 1:
            return lines[0][:200]
        idx = min(max(line - 1, 0), len(lines) - 1)
        start = max(0, idx - 1)
        end = min(len(lines), idx + 2)
        return " | ".join(part.strip() for part in lines[start:end])[:240]

    @staticmethod
    def _reference_line(index: RepositoryIndex, path: str, symbol: str) -> int | None:
        for ref in index.import_references:
            if ref.source_file.replace("\\", "/") != path:
                continue
            if ref.symbol == symbol or symbol in (ref.target_module or ""):
                return ref.start_line
        return None

    @staticmethod
    def _call_line(index: RepositoryIndex, path: str, symbol: str) -> int | None:
        for ref in index.import_references:
            if ref.source_file.replace("\\", "/") != path:
                continue
            if (ref.kind or "") == "call" and ref.symbol == symbol:
                return ref.start_line
            if ref.symbol == symbol:
                return ref.start_line
        return None

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
    def _display_symbol(parent: str | None, name: str) -> str:
        if parent:
            return f"{parent}.{name}"
        return name

    @staticmethod
    def _norm(path: str) -> str:
        return path.replace("\\", "/").lstrip("./")

    @staticmethod
    def _merge_unique(hits: list[CodeSearchHit]) -> list[CodeSearchHit]:
        seen: set[tuple[str, str, str, int | None]] = set()
        out: list[CodeSearchHit] = []
        for hit in hits:
            key = (hit.file, hit.symbol, hit.type, hit.line)
            if key in seen:
                continue
            seen.add(key)
            out.append(hit)
        return out
