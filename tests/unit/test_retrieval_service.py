"""Unit tests for RetrievalService (local embeddings.json, no Chroma / AI)."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from refactory.core.logger import get_service_logger
from refactory.embedding.models import EmbeddingStore, FileEmbeddingRecord
from refactory.retrieval.models import EntityKind
from refactory.retrieval.service import RetrievalError, RetrievalService
from refactory.retrieval.similarity import (
    CosineSimilarity,
    DotProductSimilarity,
    EuclideanSimilarity,
    SimilarityError,
    get_similarity_metric,
)
from refactory.retrieval.store import JsonFileEmbeddingStoreBackend


class FakeProvider:
    def __init__(self, model_name: str = "fake-model") -> None:
        self._model_name = model_name
        self.embed_calls: list[str] = []

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed_text(self, text: str) -> list[float]:
        self.embed_calls.append(text)
        return self._vector(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(t) for t in texts]

    @staticmethod
    def _vector(text: str, dim: int = 8) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        raw = [((digest[i % len(digest)] / 255.0) * 2) - 1 for i in range(dim)]
        norm = math.sqrt(sum(v * v for v in raw)) or 1.0
        return [v / norm for v in raw]


def _logger():
    return get_service_logger("test.retrieval")


def _service(tmp_path: Path, provider: FakeProvider | None = None) -> tuple[RetrievalService, FakeProvider]:
    provider = provider or FakeProvider()
    service = RetrievalService(
        embedding_provider=provider,
        logger=_logger(),
        store_backend=JsonFileEmbeddingStoreBackend(),
        similarity=CosineSimilarity(),
    )
    return service, provider


def _write_store(root: Path, files: dict[str, FileEmbeddingRecord], model: str = "fake-model") -> Path:
    store = EmbeddingStore(
        model=model,
        updated_at=datetime.now(timezone.utc),
        files=files,
    )
    path = root / ".refactory" / "embeddings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(store.model_dump_json(indent=2), encoding="utf-8")
    return path


def _vec(*values: float) -> list[float]:
    # Normalize for stable cosine comparisons
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


def test_cosine_similarity_correctness():
    metric = CosineSimilarity()
    assert metric.score([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert metric.score([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert metric.score([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_rejects_mismatched_and_zero_vectors():
    metric = CosineSimilarity()
    with pytest.raises(SimilarityError):
        metric.score([1.0], [1.0, 2.0])
    with pytest.raises(SimilarityError):
        metric.score([0.0, 0.0], [1.0, 0.0])


def test_get_similarity_metric_aliases():
    assert isinstance(get_similarity_metric("cosine"), CosineSimilarity)
    assert isinstance(get_similarity_metric("dot"), DotProductSimilarity)
    assert isinstance(get_similarity_metric("euclidean"), EuclideanSimilarity)
    with pytest.raises(SimilarityError):
        get_similarity_metric("nope")


def test_empty_repository_no_store(tmp_path: Path):
    service, provider = _service(tmp_path)
    result = service.search("auth", root=tmp_path)
    assert result.hits == []
    assert result.statistics.results_returned == 0
    assert provider.embed_calls == []  # nothing to score against


def test_empty_embeddings_store(tmp_path: Path):
    _write_store(tmp_path, {})
    service, provider = _service(tmp_path)
    result = service.search("auth", root=tmp_path)
    assert result.hits == []
    assert provider.embed_calls == []


def test_top_k_ordering(tmp_path: Path):
    query_like = _vec(1.0, 0.0, 0.0, 0.0)
    mid = _vec(0.7, 0.7, 0.0, 0.0)
    far = _vec(0.0, 1.0, 0.0, 0.0)
    _write_store(
        tmp_path,
        {
            "a.py": FileEmbeddingRecord(
                hash="1",
                file=far,
                module=far,
                functions={"far_fn": far},
            ),
            "b.py": FileEmbeddingRecord(
                hash="2",
                file=mid,
                module=mid,
                functions={"mid_fn": mid},
            ),
            "c.py": FileEmbeddingRecord(
                hash="3",
                file=query_like,
                module=query_like,
                functions={"near_fn": query_like},
            ),
        },
    )

    class FixedProvider(FakeProvider):
        def embed_text(self, text: str) -> list[float]:
            self.embed_calls.append(text)
            return query_like

    service, _ = _service(tmp_path, FixedProvider())
    result = service.top_k("authentication", 3, root=tmp_path)
    assert len(result.hits) == 3
    scores = [h.score for h in result.hits]
    assert scores == sorted(scores, reverse=True)
    assert result.hits[0].file_path == "c.py"


def test_deterministic_ordering_tie_break(tmp_path: Path):
    same = _vec(1.0, 0.0, 0.0, 0.0)
    _write_store(
        tmp_path,
        {
            "z.py": FileEmbeddingRecord(hash="z", file=same, module=same, functions={"b": same}),
            "a.py": FileEmbeddingRecord(hash="a", file=same, module=same, functions={"a": same}),
        },
    )

    class FixedProvider(FakeProvider):
        def embed_text(self, text: str) -> list[float]:
            return same

    service, _ = _service(tmp_path, FixedProvider())
    first = service.search("x", top_k=10, root=tmp_path)
    second = service.search("x", top_k=10, root=tmp_path)
    assert [ (h.file_path, h.symbol) for h in first.hits ] == [
        (h.file_path, h.symbol) for h in second.hits
    ]
    # Tie-break prefers file path then symbol
    assert first.hits[0].file_path == "a.py"


def test_duplicate_symbols_across_files(tmp_path: Path):
    v1 = _vec(1.0, 0.0, 0.0, 0.0)
    v2 = _vec(0.9, 0.1, 0.0, 0.0)
    _write_store(
        tmp_path,
        {
            "auth.py": FileEmbeddingRecord(
                hash="1", file=v1, module=v1, functions={"validate_token": v1}
            ),
            "legacy/auth.py": FileEmbeddingRecord(
                hash="2", file=v2, module=v2, functions={"validate_token": v2}
            ),
        },
    )

    class FixedProvider(FakeProvider):
        def embed_text(self, text: str) -> list[float]:
            return v1

    service, _ = _service(tmp_path, FixedProvider())
    result = service.search_symbol("validate_token", top_k=10, root=tmp_path)
    paths = {h.file_path for h in result.hits}
    assert paths == {"auth.py", "legacy/auth.py"}
    assert all(h.symbol == "validate_token" for h in result.hits)


def test_query_returning_no_matches_when_all_vectors_corrupt(tmp_path: Path):
    _write_store(
        tmp_path,
        {
            "bad.py": FileEmbeddingRecord(
                hash="1",
                file=[],
                module=[],
                functions={"broken": []},
            )
        },
    )
    service, provider = _service(tmp_path)
    result = service.search("auth", root=tmp_path)
    assert result.hits == []
    assert provider.embed_calls == []


def test_corrupted_vectors_skipped(tmp_path: Path):
    good = _vec(1.0, 0.0, 0.0, 0.0)
    # Mix valid 4-d vectors with wrong-dimension / empty vectors in raw JSON
    payload = {
        "model": "fake-model",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "files": {
            "good.py": {
                "hash": "1",
                "file": good,
                "module": good,
                "classes": {},
                "functions": {"ok": good},
            },
            "bad.py": {
                "hash": "2",
                "file": [1.0, 2.0],
                "module": [],
                "classes": {},
                "functions": {"x": [1.0]},
            },
        },
    }
    path = tmp_path / ".refactory" / "embeddings.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")

    class FixedProvider(FakeProvider):
        def embed_text(self, text: str) -> list[float]:
            return good

    service, _ = _service(tmp_path, FixedProvider())
    result = service.search("ok", top_k=20, root=tmp_path)
    assert result.statistics.candidates_skipped >= 1
    assert result.hits
    assert all(h.file_path == "good.py" for h in result.hits)


def test_malformed_embedding_file(tmp_path: Path):
    path = tmp_path / ".refactory" / "embeddings.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")
    service, provider = _service(tmp_path)
    result = service.search("auth", root=tmp_path)
    assert result.hits == []
    assert provider.embed_calls == []


def test_empty_query_raises(tmp_path: Path):
    service, _ = _service(tmp_path)
    with pytest.raises(RetrievalError):
        service.search("   ", root=tmp_path)


def test_related_and_impacted_files(tmp_path: Path):
    auth = _vec(1.0, 0.0, 0.0, 0.0)
    login = _vec(0.95, 0.05, 0.0, 0.0)
    util = _vec(0.0, 1.0, 0.0, 0.0)
    _write_store(
        tmp_path,
        {
            "auth.py": FileEmbeddingRecord(
                hash="1", file=auth, module=auth, functions={"validate_token": auth}
            ),
            "login.py": FileEmbeddingRecord(
                hash="2", file=login, module=login, functions={"handle": login}
            ),
            "util.py": FileEmbeddingRecord(
                hash="3", file=util, module=util, functions={"helper": util}
            ),
        },
    )
    service, _ = _service(tmp_path)
    related = service.related_files("auth.py", top_k=2, root=tmp_path)
    assert related
    assert related[0].file_path == "login.py"
    assert "auth.py" not in {r.file_path for r in related}

    impacted = service.impacted_files("auth.py", top_k=2, root=tmp_path)
    assert impacted
    assert impacted[0].file_path == "login.py"


def test_incremental_compatibility_hash_ignored_for_search(tmp_path: Path):
    """Retrieval uses vectors only; hash field does not affect ranking."""
    v = _vec(1.0, 0.0, 0.0, 0.0)
    _write_store(
        tmp_path,
        {"auth.py": FileEmbeddingRecord(hash="old-hash", file=v, module=v, functions={"f": v})},
    )
    # Simulate incremental re-embed keeping same vectors, new hash
    _write_store(
        tmp_path,
        {"auth.py": FileEmbeddingRecord(hash="new-hash", file=v, module=v, functions={"f": v})},
    )

    class FixedProvider(FakeProvider):
        def embed_text(self, text: str) -> list[float]:
            return v

    service, _ = _service(tmp_path, FixedProvider())
    result = service.search("f", top_k=10, root=tmp_path)
    function_hits = [h for h in result.hits if h.kind == EntityKind.FUNCTION]
    assert function_hits
    assert function_hits[0].symbol == "f"
    assert function_hits[0].file_path == "auth.py"


def test_never_regenerates_embeddings(tmp_path: Path):
    v = _vec(1.0, 0.0, 0.0, 0.0)
    store_path = _write_store(
        tmp_path,
        {"auth.py": FileEmbeddingRecord(hash="h", file=v, module=v, functions={"f": v})},
    )
    before = store_path.read_text(encoding="utf-8")

    class FixedProvider(FakeProvider):
        def embed_text(self, text: str) -> list[float]:
            return v

        def embed_batch(self, texts: list[str]) -> list[list[float]]:
            raise AssertionError("embed_batch must not be used by retrieval")

    service, _ = _service(tmp_path, FixedProvider())
    service.search("token", root=tmp_path)
    after = store_path.read_text(encoding="utf-8")
    assert before == after


def test_search_result_typed_fields(tmp_path: Path):
    v = _vec(1.0, 0.0, 0.0, 0.0)
    _write_store(
        tmp_path,
        {
            "auth.py": FileEmbeddingRecord(
                hash="h",
                file=v,
                module=v,
                classes={"AuthService": v},
                functions={"validate_token": v},
            )
        },
    )

    class FixedProvider(FakeProvider):
        def embed_text(self, text: str) -> list[float]:
            return v

    service, _ = _service(tmp_path, FixedProvider())
    result = service.search("validate_token", top_k=5, root=tmp_path)
    assert result.query.text == "validate_token"
    assert result.statistics.candidates_scanned >= 4
    assert all(hasattr(h, "score") and hasattr(h, "file_path") for h in result.hits)


def test_dot_and_euclidean_metrics_usable(tmp_path: Path):
    v = _vec(1.0, 0.0, 0.0, 0.0)
    _write_store(
        tmp_path,
        {"auth.py": FileEmbeddingRecord(hash="h", file=v, module=v, functions={"f": v})},
    )

    class FixedProvider(FakeProvider):
        def embed_text(self, text: str) -> list[float]:
            return v

    service, _ = _service(tmp_path, FixedProvider())
    dot = service.search("f", top_k=1, root=tmp_path, metric="dot")
    euc = service.search("f", top_k=1, root=tmp_path, metric="euclidean")
    assert dot.hits[0].metric == "dot"
    assert euc.hits[0].metric == "euclidean"
