"""RetrievalService — deterministic semantic search over persisted embeddings.

Loads ``.refactory/embeddings.json`` only. Never regenerates embeddings, never
calls parser/indexer, and never talks to Chroma/FAISS/remote vector DBs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from refactory.cache.keys import (
    embedding_lookup_key,
    file_hashes_digest,
    retrieval_cache_key,
)
from refactory.cache.store import CacheStore, NullCache
from refactory.core.exceptions import RefactoryError
from refactory.core.logger import bind_context
from refactory.embedding.interfaces import EmbeddingProvider
from refactory.embedding.models import EmbeddingStore, FileEmbeddingRecord
from refactory.github.models import PullRequest
from refactory.retrieval.models import (
    EntityKind,
    RetrievedFile,
    RetrievedSymbol,
    RetrievalStatistics,
    SearchQuery,
    SearchResult,
)
from refactory.retrieval.similarity import (
    CosineSimilarity,
    SimilarityError,
    SimilarityMetric,
    get_similarity_metric,
)
from refactory.retrieval.store import EmbeddingStoreBackend, JsonFileEmbeddingStoreBackend

if TYPE_CHECKING:
    from loguru import Logger


class RetrievalError(RefactoryError):
    """Retrieval failed (missing store, empty query, etc.)."""


@dataclass(frozen=True, slots=True)
class _Candidate:
    file_path: str
    module_name: str
    symbol: str
    kind: EntityKind
    vector: list[float]


class RetrievalService:
    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        logger: "Logger",
        *,
        store_backend: EmbeddingStoreBackend | None = None,
        similarity: SimilarityMetric | None = None,
        cache: CacheStore | None = None,
    ) -> None:
        self._provider = embedding_provider
        self._logger = logger
        self._store_backend: EmbeddingStoreBackend = (
            store_backend or JsonFileEmbeddingStoreBackend()
        )
        self._similarity: SimilarityMetric = similarity or CosineSimilarity()
        self._cache: CacheStore = cache or NullCache()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        root: Path | str | None = None,
        metric: str | None = None,
    ) -> SearchResult:
        """Semantic search over all persisted file/module/class/function vectors."""
        return self.top_k(query, top_k, root=root, metric=metric)

    def top_k(
        self,
        query: str,
        k: int = 8,
        *,
        root: Path | str | None = None,
        metric: str | None = None,
    ) -> SearchResult:
        text = query.strip()
        if not text:
            raise RetrievalError("Search query must not be empty")
        if k < 1:
            raise RetrievalError("top_k must be >= 1")

        root_path = self._resolve_root(root)
        store = self._load_store(root_path)
        similarity = self._resolve_metric(metric)
        search_query = SearchQuery(text=text, top_k=k, metric=similarity.name)

        if store is None:
            bind_context(self._logger, cache="miss").warning(
                "No embeddings store at {}",
                self._store_backend.store_path(root_path),
            )
            return SearchResult(
                query=search_query,
                hits=[],
                statistics=RetrievalStatistics(
                    embedding_model=self._provider.model_name,
                    metric=similarity.name,
                    store_path=str(self._store_backend.store_path(root_path)),
                ),
            )

        repo_hash = self._store_fingerprint(store)
        cache_key = retrieval_cache_key(
            repository_hash=repo_hash,
            model_version=store.model or self._provider.model_name,
            query=text,
            top_k=k,
            metric=similarity.name,
        )
        cached = self._cache.get(cache_key)
        if isinstance(cached, dict):
            result = SearchResult.model_validate(cached)
            bind_context(self._logger, cache="hit").info(
                "Retrieval search cache hit — query={!r}, hits={}, metric={}",
                text,
                len(result.hits),
                similarity.name,
            )
            return result

        candidates, skipped = self._flatten_store(store)
        if not candidates:
            return SearchResult(
                query=search_query,
                hits=[],
                statistics=RetrievalStatistics(
                    candidates_scanned=0,
                    candidates_skipped=skipped,
                    embedding_model=store.model or self._provider.model_name,
                    metric=similarity.name,
                    store_path=str(self._store_backend.store_path(root_path)),
                ),
            )

        query_vector = self._embed_text_cached(text)
        hits, rank_skipped = self._rank(
            query_vector, candidates, k=k, similarity=similarity
        )

        stats = RetrievalStatistics(
            candidates_scanned=len(candidates),
            candidates_skipped=skipped + rank_skipped,
            results_returned=len(hits),
            embedding_model=store.model or self._provider.model_name,
            metric=similarity.name,
            store_path=str(self._store_backend.store_path(root_path)),
        )
        result = SearchResult(query=search_query, hits=hits, statistics=stats)
        self._cache.set(cache_key, result.model_dump(mode="json"))
        bind_context(self._logger, cache="miss").info(
            "Retrieval search — query={!r}, hits={}, scanned={}, metric={}",
            text,
            len(hits),
            len(candidates),
            similarity.name,
        )
        return result

    def search_symbol(
        self,
        name: str,
        *,
        top_k: int = 8,
        root: Path | str | None = None,
        metric: str | None = None,
    ) -> SearchResult:
        """Search preferring entities whose symbol name matches ``name``."""
        text = name.strip()
        if not text:
            raise RetrievalError("Symbol name must not be empty")

        root_path = self._resolve_root(root)
        store = self._load_store(root_path)
        similarity = self._resolve_metric(metric)
        search_query = SearchQuery(text=text, top_k=top_k, metric=similarity.name)

        if store is None:
            return SearchResult(
                query=search_query,
                hits=[],
                statistics=RetrievalStatistics(
                    embedding_model=self._provider.model_name,
                    metric=similarity.name,
                    store_path=str(self._store_backend.store_path(root_path)),
                ),
            )

        candidates, skipped = self._flatten_store(store)
        exact = [
            c
            for c in candidates
            if c.kind in {EntityKind.CLASS, EntityKind.FUNCTION, EntityKind.MODULE}
            and c.symbol == text
        ]
        pool = exact if exact else candidates
        if not pool:
            return SearchResult(
                query=search_query,
                hits=[],
                statistics=RetrievalStatistics(
                    candidates_scanned=0,
                    candidates_skipped=skipped,
                    embedding_model=store.model or self._provider.model_name,
                    metric=similarity.name,
                    store_path=str(self._store_backend.store_path(root_path)),
                ),
            )

        query_vector = self._embed_text_cached(text)
        hits, rank_skipped = self._rank(
            query_vector, pool, k=top_k, similarity=similarity
        )
        return SearchResult(
            query=search_query,
            hits=hits,
            statistics=RetrievalStatistics(
                candidates_scanned=len(pool),
                candidates_skipped=skipped
                + rank_skipped
                + (len(candidates) - len(pool) if exact else 0),
                results_returned=len(hits),
                embedding_model=store.model or self._provider.model_name,
                metric=similarity.name,
                store_path=str(self._store_backend.store_path(root_path)),
            ),
        )

    def related_files(
        self,
        path: str,
        *,
        top_k: int = 8,
        root: Path | str | None = None,
        metric: str | None = None,
    ) -> list[RetrievedFile]:
        """Files most similar to ``path`` using file-level embeddings."""
        return self._files_by_seed(
            path,
            top_k=top_k,
            root=root,
            metric=metric,
            prefer_file_vectors=True,
        )

    def impacted_files(
        self,
        path: str,
        *,
        top_k: int = 8,
        root: Path | str | None = None,
        metric: str | None = None,
    ) -> list[RetrievedFile]:
        """Files most similar to any embedding under ``path`` (impact heuristic)."""
        return self._files_by_seed(
            path,
            top_k=top_k,
            root=root,
            metric=metric,
            prefer_file_vectors=False,
        )

    def retrieve_related_context(
        self,
        pull_request: PullRequest,
        *,
        top_k: int = 8,
        root: Path | str | None = None,
    ) -> list[str]:
        """Return related file paths for a PR's changed files (empty when no embeddings)."""
        root_path = self._resolve_root(root)
        seen: set[str] = set()
        ordered: list[str] = []

        for changed in pull_request.changed_files:
            path = (changed.path or "").strip()
            if not path:
                continue
            try:
                related = self.related_files(path, top_k=top_k, root=root_path)
            except Exception as exc:  # noqa: BLE001 — soft-fail per file
                self._logger.warning("related_files failed for {}: {}", path, exc)
                continue
            for item in related:
                key = self._norm(item.file_path)
                if key and key not in seen:
                    seen.add(key)
                    ordered.append(item.file_path)

        if not ordered and pull_request.title.strip():
            try:
                result = self.search(pull_request.title, top_k=top_k, root=root_path)
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("fallback search failed: {}", exc)
            else:
                for hit in result.hits:
                    key = self._norm(hit.file_path)
                    if key and key not in seen:
                        seen.add(key)
                        ordered.append(hit.file_path)

        self._logger.info(
            "retrieve_related_context PR #{} — {} path(s)",
            pull_request.number,
            len(ordered),
        )
        return ordered

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _files_by_seed(
        self,
        path: str,
        *,
        top_k: int,
        root: Path | str | None,
        metric: str | None,
        prefer_file_vectors: bool,
    ) -> list[RetrievedFile]:
        if top_k < 1:
            raise RetrievalError("top_k must be >= 1")
        needle = self._norm(path)
        if not needle:
            raise RetrievalError("File path must not be empty")

        root_path = self._resolve_root(root)
        store = self._load_store(root_path)
        similarity = self._resolve_metric(metric)
        if store is None:
            return []

        candidates, _skipped = self._flatten_store(store)
        seed_candidates = [c for c in candidates if self._norm(c.file_path) == needle]
        if not seed_candidates:
            # basename fallback when unique
            basename = needle.rsplit("/", 1)[-1]
            seed_candidates = [
                c for c in candidates if self._norm(c.file_path).endswith(basename)
            ]
            paths = {c.file_path for c in seed_candidates}
            if len(paths) != 1:
                return []

        seed_path = self._norm(seed_candidates[0].file_path)
        if prefer_file_vectors:
            file_seeds = [c for c in seed_candidates if c.kind == EntityKind.FILE]
            seed_vector = (file_seeds[0].vector if file_seeds else seed_candidates[0].vector)
        else:
            # Average seed entity vectors for a stable impact query vector
            seed_vector = self._mean_vector([c.vector for c in seed_candidates])

        # Aggregate best score per other file
        best: dict[str, RetrievedFile] = {}
        others = [c for c in candidates if self._norm(c.file_path) != seed_path]
        for candidate in others:
            try:
                value = similarity.score(seed_vector, candidate.vector)
            except SimilarityError:
                continue
            existing = best.get(candidate.file_path)
            if existing is None or value > existing.score:
                best[candidate.file_path] = RetrievedFile(
                    file_path=candidate.file_path,
                    module_name=candidate.module_name,
                    score=round(value, 6),
                    metric=similarity.name,
                    best_symbol=candidate.symbol,
                    best_kind=candidate.kind,
                )

        ranked = sorted(
            best.values(),
            key=lambda item: (-item.score, item.file_path),
        )
        return ranked[:top_k]

    def _rank(
        self,
        query_vector: list[float],
        candidates: list[_Candidate],
        *,
        k: int,
        similarity: SimilarityMetric,
    ) -> tuple[list[RetrievedSymbol], int]:
        scored: list[RetrievedSymbol] = []
        skipped = 0
        query_dim = len(query_vector)
        for candidate in candidates:
            if len(candidate.vector) != query_dim:
                skipped += 1
                continue
            try:
                value = similarity.score(query_vector, candidate.vector)
            except SimilarityError:
                skipped += 1
                continue
            scored.append(
                RetrievedSymbol(
                    result=f"{candidate.kind.value}:{candidate.symbol}",
                    score=round(value, 6),
                    file_path=candidate.file_path,
                    module_name=candidate.module_name,
                    symbol=candidate.symbol,
                    kind=candidate.kind,
                    metric=similarity.name,
                )
            )
        scored.sort(key=lambda hit: (-hit.score, hit.file_path, hit.symbol, hit.kind.value))
        return scored[:k], skipped

    def _embed_text_cached(self, text: str) -> list[float]:
        """Cache query embedding lookups by model version + text."""
        key = embedding_lookup_key(
            model_version=self._provider.model_name,
            text=text,
        )
        cached = self._cache.get(key)
        if isinstance(cached, list) and cached and isinstance(cached[0], (int, float)):
            bind_context(self._logger, cache="hit").debug(
                "Embedding lookup cache hit — model={}",
                self._provider.model_name,
            )
            return [float(v) for v in cached]
        vector = self._provider.embed_text(text)
        self._cache.set(key, list(vector))
        return vector

    @staticmethod
    def _store_fingerprint(store: EmbeddingStore) -> str:
        hashes = {path: record.hash for path, record in store.files.items()}
        return file_hashes_digest(hashes)

    def _flatten_store(self, store: EmbeddingStore) -> tuple[list[_Candidate], int]:
        candidates: list[_Candidate] = []
        skipped = 0

        for file_path, record in sorted(store.files.items(), key=lambda item: item[0]):
            path = self._norm(file_path)
            module_name = Path(path).stem
            for kind, symbol, vector in self._iter_record_vectors(record, module_name):
                if not self._is_usable_vector(vector):
                    skipped += 1
                    continue
                candidates.append(
                    _Candidate(
                        file_path=path,
                        module_name=module_name,
                        symbol=symbol,
                        kind=kind,
                        vector=list(vector),
                    )
                )
        return candidates, skipped

    @staticmethod
    def _iter_record_vectors(
        record: FileEmbeddingRecord,
        module_name: str,
    ) -> list[tuple[EntityKind, str, list[float]]]:
        items: list[tuple[EntityKind, str, list[float]]] = []
        if record.file:
            items.append((EntityKind.FILE, module_name, record.file))
        if record.module:
            items.append((EntityKind.MODULE, module_name, record.module))
        for name, vector in sorted(record.classes.items()):
            items.append((EntityKind.CLASS, name, vector))
        for name, vector in sorted(record.functions.items()):
            items.append((EntityKind.FUNCTION, name, vector))
        return items

    @staticmethod
    def _is_usable_vector(vector: list[float]) -> bool:
        if not vector:
            return False
        try:
            return all(isinstance(v, (int, float)) and math.isfinite(float(v)) for v in vector)
        except (TypeError, ValueError):
            return False

    def has_store(self, root: Path | str | None = None) -> bool:
        """Return True when a persisted embeddings store exists for ``root``."""
        return self._load_store(self._resolve_root(root)) is not None

    def _load_store(self, root: Path) -> EmbeddingStore | None:
        return self._store_backend.load(root)

    def _resolve_metric(self, metric: str | None) -> SimilarityMetric:
        if metric is None:
            return self._similarity
        return get_similarity_metric(metric)

    @staticmethod
    def _resolve_root(root: Path | str | None) -> Path:
        return Path(root or Path.cwd()).resolve()

    @staticmethod
    def _norm(path: str) -> str:
        return path.replace("\\", "/").lstrip("./")

    @staticmethod
    def _mean_vector(vectors: list[list[float]]) -> list[float]:
        if not vectors:
            raise RetrievalError("No seed vectors available")
        dim = len(vectors[0])
        acc = [0.0] * dim
        count = 0
        for vector in vectors:
            if len(vector) != dim:
                continue
            for i, value in enumerate(vector):
                acc[i] += float(value)
            count += 1
        if count == 0:
            raise RetrievalError("No usable seed vectors available")
        return [value / count for value in acc]
