"""RequirementSearch — find candidate files for a parsed requirement.

Orchestrates CodeSearchService, RepositoryGraph, and RetrievalService
(when embeddings exist). Never duplicates graph traversal or search
infrastructure.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from refactory.codesearch.models import CodeSearchHit
from refactory.codesearch.service import CodeSearchService
from refactory.graph.service import RepositoryGraphService
from refactory.requirement.models import RequirementCandidate, RequirementSummary
from refactory.retrieval.service import RetrievalService

if TYPE_CHECKING:
    from loguru import Logger


class RequirementSearch:
    """Given parsed requirement keywords, find candidate files using
    existing search infrastructure."""

    def __init__(
        self,
        logger: "Logger",
        code_search_service: CodeSearchService,
        graph_service: RepositoryGraphService,
        retrieval_service: RetrievalService,
        *,
        top_k: int = 30,
    ) -> None:
        self._logger = logger
        self._search = code_search_service
        self._graph = graph_service
        self._retrieval = retrieval_service
        self._top_k = top_k

    def find_candidates(
        self, summary: RequirementSummary
    ) -> list[RequirementCandidate]:
        """Search for files matching the requirement keywords.

        Strategy:
        1. Structural search for each keyword via CodeSearchService
        2. File-hint search for explicitly referenced filenames
        3. Semantic search using full requirement summary (when embeddings exist)
        4. Merge, deduplicate, and rank
        """
        scored: dict[str, _FileScore] = {}

        # 1. Structural keyword search (batched — one search call per keyword
        #    but results merged into a single scored dict)
        self._batch_keyword_search(scored, summary.detected_keywords[:20])

        # 2. File-hint exact matches
        for hint in summary.file_hints:
            try:
                result = self._search.search_files(hint, top_k=5)
                for hit in result.hits:
                    self._accumulate(scored, hit.file, 0.95, f"file_hint:{hint}")
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("File-hint search failed for '{}': {}", hint, exc)

        # 3. Feature-category broad searches
        for feature in summary.detected_features[:10]:
            try:
                result = self._search.search(feature, top_k=10)
                for hit in result.hits:
                    self._accumulate(scored, hit.file, hit.score * 0.5, f"feature:{feature}")
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("Feature search failed for '{}': {}", feature, exc)

        # 4. Semantic search (using the summary sentence)
        if summary.summary:
            self._semantic_search(scored, summary.summary)

        # 5. Graph expansion: for top-scoring files, add their dependents
        self._graph_expand(scored)

        candidates = self._to_candidates(scored)
        self._logger.info(
            "RequirementSearch found {} candidate(s) from {} keyword(s)",
            len(candidates),
            len(summary.detected_keywords),
        )
        return candidates

    # ---------------------------------------------------------------
    # Internals
    # ---------------------------------------------------------------

    def _batch_keyword_search(
        self, scored: dict[str, "_FileScore"], keywords: list[str],
    ) -> None:
        """Search all keywords, deduplicating file hits across keywords."""
        seen_keyword_file: set[tuple[str, str]] = set()
        for keyword in keywords:
            try:
                result = self._search.search(keyword, top_k=self._top_k)
                for hit in result.hits:
                    key = (keyword, hit.file)
                    if key in seen_keyword_file:
                        continue
                    seen_keyword_file.add(key)
                    self._accumulate(scored, hit.file, hit.score * 0.8, f"keyword:{keyword}")
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("Keyword search failed for '{}': {}", keyword, exc)

    @staticmethod
    def _accumulate(
        scored: dict[str, "_FileScore"],
        path: str,
        score: float,
        reason: str,
    ) -> None:
        norm = path.replace("\\", "/")
        if norm not in scored:
            scored[norm] = _FileScore(path=norm)
        scored[norm].score += score
        if reason not in scored[norm].reasons:
            scored[norm].reasons.append(reason)

    def _semantic_search(self, scored: dict[str, "_FileScore"], query: str) -> None:
        try:
            result = self._search.search(query, top_k=self._top_k)
            for hit in result.hits:
                if hit.score > 0:
                    self._accumulate(scored, hit.file, hit.score * 0.6, "semantic")
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("Semantic search skipped: {}", exc)

    def _graph_expand(self, scored: dict[str, "_FileScore"]) -> None:
        """For high-confidence files, pull in direct graph dependents."""
        top_paths = sorted(scored, key=lambda p: -scored[p].score)[:10]
        for path in top_paths:
            try:
                deps = self._graph.dependencies_of(path)
                for dep in (deps or [])[:5]:
                    self._accumulate(scored, dep, 0.3, f"graph_dep_of:{path}")
            except Exception:  # noqa: BLE001
                pass
            try:
                rev = self._graph.reverse_dependencies(path)
                for rdep in (rev or [])[:5]:
                    self._accumulate(scored, rdep, 0.3, f"graph_rdep_of:{path}")
            except Exception:  # noqa: BLE001
                pass

    def _to_candidates(self, scored: dict[str, "_FileScore"]) -> list[RequirementCandidate]:
        for item in scored.values():
            item.score *= _ranking_factor(item.path)

        items = sorted(scored.values(), key=lambda s: -s.score)
        max_score = items[0].score if items else 1.0
        if max_score <= 0:
            max_score = 1.0
        result: list[RequirementCandidate] = []
        for item in items[:self._top_k]:
            conf = min(item.score / max_score, 1.0)
            if conf < 0.05:
                continue
            result.append(
                RequirementCandidate(
                    path=item.path,
                    confidence=round(conf, 3),
                    reasons=item.reasons[:10],
                )
            )
        return result


def _ranking_factor(path: str) -> float:
    """Apply demotion factor: production > libraries > utilities > tests > demos."""
    parts = [p.lower() for p in Path(path).parts]
    stem = Path(path).stem.lower()

    if (
        stem.endswith("_demo")
        or stem.endswith("_example")
        or any(p in parts for p in ("examples", "demo", "demos"))
    ):
        return 0.3

    if (
        any(p in parts for p in ("tests", "test", "spec", "specs"))
        or stem.startswith("test_")
        or stem.endswith("_test")
    ):
        return 0.5

    if any(p in parts for p in ("utils", "util", "helpers", "helper", "lib", "vendor")):
        return 0.8

    return 1.0


class _FileScore:
    """Mutable accumulator for ranking."""

    __slots__ = ("path", "score", "reasons")

    def __init__(self, path: str) -> None:
        self.path = path
        self.score: float = 0.0
        self.reasons: list[str] = []
