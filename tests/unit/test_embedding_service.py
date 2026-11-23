"""Unit tests for provider-based EmbeddingService (no real model downloads)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from refactory.core.exceptions import EmbeddingError, IndexError_
from refactory.core.logger import get_service_logger
from refactory.embedding.interfaces import EmbeddingProvider
from refactory.embedding.service import EmbeddingService, require_index
from refactory.indexer.models import (
    IndexedFile,
    IndexedSymbol,
    RepositoryIndex,
    RepositoryStatistics,
    RepositorySummary,
    SymbolKind,
)


class FakeEmbeddingProvider:
    """Deterministic provider: vector = first 8 floats from sha256 of text."""

    def __init__(self, model_name: str = "fake-model") -> None:
        self._model_name = model_name
        self.batch_calls: list[list[str]] = []
        self.text_calls: list[str] = []

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed_text(self, text: str) -> list[float]:
        self.text_calls.append(text)
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.batch_calls.append(list(texts))
        return [self._vector(text) for text in texts]

    @staticmethod
    def _vector(text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [b / 255.0 for b in digest[:8]]


def _logger():
    return get_service_logger("test.embedding")


def _index(files: list[IndexedFile], *, name: str = "demo") -> RepositoryIndex:
    symbols: list[IndexedSymbol] = []
    for f in files:
        symbols.extend(f.symbols)
    return RepositoryIndex(
        summary=RepositorySummary(
            repository_root="/tmp/demo",
            repository_name=name,
            total_indexed_files=len(files),
            timestamp=datetime.now(timezone.utc),
        ),
        statistics=RepositoryStatistics(),
        files=files,
        symbols=symbols,
        import_references=[],
        file_hashes={f.relative_path: f.content_hash for f in files},
    )


def _file(
    path: str,
    *,
    content_hash: str,
    module: str | None = None,
    functions: list[str] | None = None,
    classes: list[str] | None = None,
    comments: list[str] | None = None,
) -> IndexedFile:
    module_name = module or Path(path).stem
    functions = functions or []
    classes = classes or []
    symbols: list[IndexedSymbol] = [
        IndexedSymbol(
            name=module_name,
            kind=SymbolKind.MODULE,
            file_path=path,
            start_line=1,
            end_line=10,
        )
    ]
    for cls in classes:
        symbols.append(
            IndexedSymbol(
                name=cls,
                kind=SymbolKind.CLASS,
                file_path=path,
                start_line=2,
                end_line=8,
            )
        )
    for fn in functions:
        symbols.append(
            IndexedSymbol(
                name=fn,
                kind=SymbolKind.FUNCTION,
                file_path=path,
                start_line=3,
                end_line=5,
            )
        )
    return IndexedFile(
        relative_path=path,
        language="python",
        content_hash=content_hash,
        module_name=module_name,
        classes=classes,
        functions=functions,
        comments=comments or [],
        symbols=symbols,
    )


def _service(provider: FakeEmbeddingProvider | None = None) -> tuple[EmbeddingService, FakeEmbeddingProvider]:
    provider = provider or FakeEmbeddingProvider()
    return EmbeddingService(provider=provider, logger=_logger()), provider


def test_provider_satisfies_protocol():
    provider = FakeEmbeddingProvider()
    assert isinstance(provider, EmbeddingProvider)


def test_deterministic_batching_preserves_order():
    service, provider = _service()
    texts = ["alpha", "beta", "gamma"]
    vectors = service.embed_documents(texts)
    assert len(vectors) == 3
    assert vectors[0] == FakeEmbeddingProvider._vector("alpha")
    assert vectors[1] == FakeEmbeddingProvider._vector("beta")
    assert len(provider.batch_calls) == 1
    assert provider.batch_calls[0] == texts


def test_embed_query_uses_provider():
    service, provider = _service()
    vector = service.embed_query("hello")
    assert vector == FakeEmbeddingProvider._vector("hello")
    assert provider.text_calls == ["hello"]


def test_empty_repository(tmp_path: Path):
    service, provider = _service()
    result = service.embed_repository(_index([]), root=tmp_path)
    assert result.files_processed == 0
    assert result.embedded == 0
    assert result.skipped == 0
    assert provider.batch_calls == []
    store_path = tmp_path / ".refactory" / "embeddings.json"
    assert store_path.is_file()


def test_embeds_file_module_class_function(tmp_path: Path):
    service, provider = _service()
    index = _index(
        [
            _file(
                "auth.py",
                content_hash="a" * 64,
                functions=["validate_token"],
                classes=["AuthService"],
                comments=["Validates JWT token"],
            )
        ]
    )
    result = service.embed_repository(index, root=tmp_path)
    assert result.embedded == 1
    assert result.skipped == 0
    assert result.newly_embedded_symbols == 4  # file + module + class + function
    assert result.symbols_embedded == 4
    assert result.repository_symbols == 4
    assert result.total_stored_vectors == 4
    assert result.reused_vectors == 0

    store = service.load_store(tmp_path)
    assert store is not None
    record = store.files["auth.py"]
    assert record.hash == "a" * 64
    assert len(record.file) == 8
    assert len(record.module) == 8
    assert "AuthService" in record.classes
    assert "validate_token" in record.functions

    # Context includes module/function names, not bare names only
    joined = "\n".join(provider.batch_calls[0])
    assert "validate_token" in joined
    assert "Module: auth" in joined
    assert "Validates JWT token" in joined


def test_hash_reuse_skips_unchanged_files(tmp_path: Path):
    service, provider = _service()
    index = _index([_file("auth.py", content_hash="h1", functions=["validate_token"])])
    first = service.embed_repository(index, root=tmp_path)
    assert first.embedded == 1
    assert first.skipped == 0
    calls_after_first = len(provider.batch_calls)

    second = service.embed_repository(index, root=tmp_path)
    assert second.embedded == 0
    assert second.skipped == 1
    assert second.newly_embedded_symbols == 0
    assert second.reused_vectors == first.repository_symbols
    assert second.repository_symbols == first.repository_symbols
    assert second.total_stored_vectors == first.total_stored_vectors
    assert len(provider.batch_calls) == calls_after_first


def test_incremental_embedding_only_modified_file(tmp_path: Path):
    service, provider = _service()
    index_v1 = _index(
        [
            _file("auth.py", content_hash="h1", functions=["a"]),
            _file("login.py", content_hash="h2", functions=["b"]),
        ]
    )
    service.embed_repository(index_v1, root=tmp_path)
    calls_after_first = sum(len(batch) for batch in provider.batch_calls)

    index_v2 = _index(
        [
            _file("auth.py", content_hash="h1-changed", functions=["a"]),
            _file("login.py", content_hash="h2", functions=["b"]),
        ]
    )
    result = service.embed_repository(index_v2, root=tmp_path)
    assert result.embedded == 1
    assert result.skipped == 1
    new_texts = sum(len(batch) for batch in provider.batch_calls) - calls_after_first
    # auth.py only: file + module + function
    assert new_texts == 3

    store = service.load_store(tmp_path)
    assert store is not None
    assert store.files["auth.py"].hash == "h1-changed"
    assert store.files["login.py"].hash == "h2"


def test_json_persistence_shape(tmp_path: Path):
    service, _provider = _service()
    index = _index([_file("auth.py", content_hash="abc", functions=["validate_token"])])
    service.embed_repository(index, root=tmp_path)

    raw = json.loads((tmp_path / ".refactory" / "embeddings.json").read_text(encoding="utf-8"))
    assert raw["model"] == "fake-model"
    assert "auth.py" in raw["files"]
    assert raw["files"]["auth.py"]["hash"] == "abc"
    assert "validate_token" in raw["files"]["auth.py"]["functions"]
    assert isinstance(raw["files"]["auth.py"]["functions"]["validate_token"], list)


def test_force_reembeds_even_when_hash_matches(tmp_path: Path):
    service, provider = _service()
    index = _index([_file("auth.py", content_hash="h1", functions=["a"])])
    service.embed_repository(index, root=tmp_path)
    before = len(provider.batch_calls)
    result = service.embed_repository(index, root=tmp_path, force=True)
    assert result.embedded == 1
    assert result.skipped == 0
    assert len(provider.batch_calls) > before


def test_model_change_rebuilds_store(tmp_path: Path):
    service_a, _ = _service(FakeEmbeddingProvider("model-a"))
    index = _index([_file("auth.py", content_hash="h1", functions=["a"])])
    service_a.embed_repository(index, root=tmp_path)

    service_b, provider_b = _service(FakeEmbeddingProvider("model-b"))
    result = service_b.embed_repository(index, root=tmp_path)
    assert result.embedded == 1
    assert result.skipped == 0
    assert provider_b.batch_calls  # re-embedded under new model
    store = service_b.load_store(tmp_path)
    assert store is not None
    assert store.model == "model-b"


def test_deleted_files_removed_from_store(tmp_path: Path):
    service, _ = _service()
    service.embed_repository(
        _index(
            [
                _file("auth.py", content_hash="h1", functions=["a"]),
                _file("gone.py", content_hash="h2", functions=["b"]),
            ]
        ),
        root=tmp_path,
    )
    service.embed_repository(
        _index([_file("auth.py", content_hash="h1", functions=["a"])]),
        root=tmp_path,
    )
    store = service.load_store(tmp_path)
    assert store is not None
    assert "auth.py" in store.files
    assert "gone.py" not in store.files


def test_malformed_store_returns_none(tmp_path: Path):
    service, _ = _service()
    path = tmp_path / ".refactory" / "embeddings.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")
    assert service.load_store(tmp_path) is None


def test_status_before_and_after_embed(tmp_path: Path):
    service, _ = _service()
    before = service.status(tmp_path)
    assert before.store_exists is False
    assert before.total_embedded_symbols == 0

    service.embed_repository(
        _index([_file("auth.py", content_hash="h1", functions=["validate_token"])]),
        root=tmp_path,
    )
    after = service.status(tmp_path)
    assert after.store_exists is True
    assert after.total_embedded_symbols >= 3
    assert after.model == "fake-model"
    assert after.storage_path.endswith("embeddings.json")
    assert after.last_update is not None


def test_require_index_helper():
    with pytest.raises(IndexError_):
        require_index(None)
    index = _index([])
    assert require_index(index) is index


def test_invalid_index_type_raises(tmp_path: Path):
    service, _ = _service()
    with pytest.raises(EmbeddingError):
        service.embed_repository("not-an-index", root=tmp_path)  # type: ignore[arg-type]


def test_provider_batch_length_mismatch_raises(tmp_path: Path):
    class BadProvider(FakeEmbeddingProvider):
        def embed_batch(self, texts: list[str]) -> list[list[float]]:
            return [[0.1]]  # wrong length

    service, _ = _service(BadProvider())
    with pytest.raises(EmbeddingError):
        service.embed_repository(
            _index([_file("auth.py", content_hash="h1", functions=["a"])]),
            root=tmp_path,
        )


def test_rich_function_context_includes_kind_and_file():
    service, provider = _service()
    indexed = _file(
        "auth.py",
        content_hash="h1",
        functions=["validate_token"],
        comments=["Validates JWT token"],
    )
    targets = service._targets_for_file(indexed)
    fn_targets = [t for t in targets if t.entity_kind == "function"]
    assert len(fn_targets) == 1
    text = fn_targets[0].text
    assert "Function: validate_token" in text
    assert "Module: auth" in text
    assert "File: auth.py" in text
    assert "Docstring: Validates JWT token" in text
    _ = provider
