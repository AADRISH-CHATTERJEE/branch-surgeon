"""EmbeddingService — generate and persist vectors from a RepositoryIndex.

Depends on EmbeddingProvider only (never a concrete model class).
Incremental: reuses prior vectors when IndexedFile.content_hash is unchanged.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from refactory.core.exceptions import EmbeddingError, IndexError_
from refactory.core.settings_groups import EmbeddingSettings
from refactory.embedding.interfaces import EmbeddingProvider
from refactory.embedding.models import (
    EmbeddingRunResult,
    EmbeddingStatus,
    EmbeddingStore,
    EmbeddingTarget,
    FileEmbeddingRecord,
)
from refactory.indexer.models import IndexedFile, IndexedSymbol, RepositoryIndex, SymbolKind

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.db.persistence import PersistenceService

EMBEDDINGS_FILENAME = "embeddings.json"
REFACTORY_DIR = ".refactory"


class EmbeddingService:
    def __init__(
        self,
        provider: EmbeddingProvider,
        logger: "Logger",
        settings: EmbeddingSettings | None = None,
        *,
        persistence_service: "PersistenceService | None" = None,
    ) -> None:
        self._provider = provider
        self._logger = logger
        self._settings = settings or EmbeddingSettings(model=provider.model_name)
        self._persistence = persistence_service

    @property
    def settings(self) -> EmbeddingSettings:
        return self._settings

    @property
    def model_name(self) -> str:
        return self._provider.model_name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed_repository(
        self,
        index: RepositoryIndex,
        *,
        root: Path | str,
        force: bool = False,
    ) -> EmbeddingRunResult:
        """Embed indexed entities; reuse vectors when file hashes match."""
        started = time.perf_counter()
        root_path = Path(root).resolve()
        storage_path = self.storage_path(root_path)

        if not isinstance(index, RepositoryIndex):
            raise EmbeddingError("Invalid repository index: expected RepositoryIndex")

        previous = self.load_store(root_path)
        if previous is not None and previous.model != self._provider.model_name and not force:
            self._logger.info(
                "Embedding model changed ({} -> {}); rebuilding store",
                previous.model,
                self._provider.model_name,
            )
            previous = None

        store = EmbeddingStore(model=self._provider.model_name, files={})
        files_processed = 0
        embedded_files = 0
        skipped_files = 0
        newly_embedded_symbols = 0
        reused_vectors = 0

        pending_texts: list[str] = []
        pending_meta: list[tuple[str, str, str]] = []  # file_path, kind, entity_key

        current_paths = {self._norm(f.relative_path) for f in index.files}

        for indexed in index.files:
            path = self._norm(indexed.relative_path)
            files_processed += 1
            prior = None if previous is None else previous.files.get(path)

            if (
                not force
                and prior is not None
                and prior.hash == indexed.content_hash
                and prior.file
            ):
                store.files[path] = prior.model_copy(deep=True)
                skipped_files += 1
                reused_vectors += self._count_file_symbols(prior)
                continue

            targets = self._targets_for_file(indexed)
            if not targets:
                # Still record hash with empty vectors for deterministic reuse
                store.files[path] = FileEmbeddingRecord(hash=indexed.content_hash)
                embedded_files += 1
                continue

            store.files[path] = FileEmbeddingRecord(hash=indexed.content_hash)
            for target in targets:
                pending_texts.append(target.text)
                pending_meta.append((path, target.entity_kind, target.entity_key))
            embedded_files += 1

        if pending_texts:
            vectors = self._provider.embed_batch(pending_texts)
            if len(vectors) != len(pending_texts):
                raise EmbeddingError(
                    f"Provider returned {len(vectors)} vectors for {len(pending_texts)} texts"
                )
            for (path, kind, key), vector in zip(pending_meta, vectors, strict=True):
                record = store.files[path]
                self._assign_vector(record, kind, key, vector)
                newly_embedded_symbols += 1

        # Drop embeddings for files no longer in the index
        if previous is not None:
            removed = set(previous.files) - current_paths
            if removed:
                self._logger.debug("Removed embeddings for {} deleted files", len(removed))

        store.updated_at = datetime.now(timezone.utc)
        self._persist(store, storage_path)

        total_stored = self._count_symbols(store)
        elapsed = time.perf_counter() - started
        result = EmbeddingRunResult(
            model=self._provider.model_name,
            repository_symbols=total_stored,
            total_stored_vectors=total_stored,
            files_processed=files_processed,
            embedded=embedded_files,
            skipped=skipped_files,
            newly_embedded_symbols=newly_embedded_symbols,
            reused_vectors=reused_vectors,
            symbols_embedded=newly_embedded_symbols,
            elapsed_seconds=round(elapsed, 4),
            storage_path=str(storage_path),
        )
        self._logger.info(
            "Embedded repository — model={}, stored={}, this_run embedded_files={}, "
            "skipped_files={}, new_symbols={}, reused_vectors={}, elapsed={:.2f}s",
            result.model,
            result.total_stored_vectors,
            result.embedded,
            result.skipped,
            result.newly_embedded_symbols,
            result.reused_vectors,
            result.elapsed_seconds,
        )

        self._persist_to_db(index, store)

        return result

    def status(self, root: Path | str) -> EmbeddingStatus:
        root_path = Path(root).resolve()
        path = self.storage_path(root_path)
        store = self.load_store(root_path)
        if store is None:
            return EmbeddingStatus(
                model=self._provider.model_name,
                storage_path=str(path),
                store_exists=False,
            )
        return EmbeddingStatus(
            model=store.model or self._provider.model_name,
            total_embedded_symbols=self._count_symbols(store),
            total_files=len(store.files),
            last_update=store.updated_at,
            storage_path=str(path),
            store_exists=True,
        )

    def load_store(self, root: Path | str) -> EmbeddingStore | None:
        path = self.storage_path(Path(root))
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return EmbeddingStore.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Failed to load embeddings store {}: {}", path, exc)
            return None

    def storage_path(self, root: Path | str) -> Path:
        return Path(root).resolve() / REFACTORY_DIR / EMBEDDINGS_FILENAME

    def embed_incremental(
        self,
        index: RepositoryIndex,
        *,
        root: Path | str,
    ) -> EmbeddingRunResult:
        """Incremental embedding — alias for the default hash-based behavior.

        Explicitly named method for the incremental pipeline:
        - Hashes source files
        - Skips unchanged files
        - Removes deleted embeddings
        - Inserts new vectors
        - Updates modified vectors
        """
        return self.embed_repository(index, root=root, force=False)

    # Compatibility hooks for RetrievalService (not used this phase)
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._provider.embed_batch(list(texts))

    def embed_query(self, text: str) -> list[float]:
        return self._provider.embed_text(text)

    # ------------------------------------------------------------------
    # Database persistence (metadata only — vectors stay in ChromaDB)
    # ------------------------------------------------------------------

    def _persist_to_db(
        self,
        index: RepositoryIndex,
        store: EmbeddingStore,
    ) -> None:
        """Persist embedding metadata to the relational database.

        Only metadata is stored (chunk_id, provider, model, vector_reference).
        Actual vectors remain in ChromaDB / JSON store.
        Never raises — persistence failures are logged but never abort
        the embedding pipeline.
        """
        if self._persistence is None:
            return

        persist_start = time.perf_counter()
        repo_name = index.summary.repository_name
        try:
            repo_data = self._persistence.get_or_create_repository(
                name=repo_name,
                root_path=index.summary.repository_root,
                default_branch="main",
            )
            repo_id = repo_data["id"]

            total_embeddings = 0
            for path, record in store.files.items():
                file_data = self._persistence.persist_file(
                    repository_id=repo_id,
                    path=path,
                    language="python",
                    sha256=record.hash,
                )
                file_id = file_data["id"]

                emb_dicts: list[dict] = []
                if record.file:
                    emb_dicts.append({
                        "chunk_id": f"{path}::file",
                        "provider": self._provider.model_name,
                        "model": self._provider.model_name,
                        "vector_reference": f"chroma:{path}::file",
                    })
                if record.module:
                    emb_dicts.append({
                        "chunk_id": f"{path}::module",
                        "provider": self._provider.model_name,
                        "model": self._provider.model_name,
                        "vector_reference": f"chroma:{path}::module",
                    })
                for cls_name in record.classes:
                    emb_dicts.append({
                        "chunk_id": f"{path}::class::{cls_name}",
                        "provider": self._provider.model_name,
                        "model": self._provider.model_name,
                        "vector_reference": f"chroma:{path}::class::{cls_name}",
                    })
                for fn_name in record.functions:
                    emb_dicts.append({
                        "chunk_id": f"{path}::function::{fn_name}",
                        "provider": self._provider.model_name,
                        "model": self._provider.model_name,
                        "vector_reference": f"chroma:{path}::function::{fn_name}",
                    })

                if emb_dicts:
                    self._persistence.persist_embeddings(file_id, emb_dicts)
                    total_embeddings += len(emb_dicts)

            persist_ms = round((time.perf_counter() - persist_start) * 1000.0, 3)
            self._logger.info(
                "Embeddings persisted — repository={}, files={}, embeddings={}, elapsed_ms={}",
                repo_name,
                len(store.files),
                total_embeddings,
                persist_ms,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.error(
                "Failed to persist embeddings for repository={}: {}\n{}",
                repo_name,
                exc,
                _format_traceback(exc),
            )

    # ------------------------------------------------------------------
    # Text building (deterministic, index-only)
    # ------------------------------------------------------------------

    def _targets_for_file(self, indexed: IndexedFile) -> list[EmbeddingTarget]:
        path = self._norm(indexed.relative_path)
        targets: list[EmbeddingTarget] = [
            EmbeddingTarget(
                entity_key="__file__",
                entity_kind="file",
                file_path=path,
                text=self._file_text(indexed),
            ),
            EmbeddingTarget(
                entity_key="__module__",
                entity_kind="module",
                file_path=path,
                text=self._module_text(indexed),
            ),
        ]

        for symbol in indexed.symbols:
            if symbol.kind == SymbolKind.MODULE:
                continue
            if symbol.kind == SymbolKind.CLASS:
                targets.append(
                    EmbeddingTarget(
                        entity_key=symbol.name,
                        entity_kind="class",
                        file_path=path,
                        text=self._class_text(indexed, symbol),
                    )
                )
            elif symbol.kind in {
                SymbolKind.FUNCTION,
                SymbolKind.METHOD,
                SymbolKind.NESTED_FUNCTION,
            }:
                key = self._function_key(symbol)
                targets.append(
                    EmbeddingTarget(
                        entity_key=key,
                        entity_kind="function",
                        file_path=path,
                        text=self._function_text(indexed, symbol),
                    )
                )
        return targets

    def _file_text(self, indexed: IndexedFile) -> str:
        parts = [
            "Kind: file",
            f"File: {self._norm(indexed.relative_path)}",
            f"Module: {indexed.module_name}",
            f"Language: {indexed.language}",
        ]
        if indexed.classes:
            parts.append("Classes: " + ", ".join(indexed.classes))
        if indexed.functions:
            parts.append("Functions: " + ", ".join(indexed.functions))
        if indexed.imports:
            parts.append("Imports: " + "; ".join(indexed.imports[:20]))
        if indexed.todo_tags:
            parts.append("TODOs: " + ", ".join(indexed.todo_tags))
        if indexed.comments:
            parts.append("Comments: " + " | ".join(indexed.comments[:10]))
        return "\n".join(parts)

    def _module_text(self, indexed: IndexedFile) -> str:
        parts = [
            "Kind: module",
            f"Module: {indexed.module_name}",
            f"File: {self._norm(indexed.relative_path)}",
        ]
        if indexed.classes:
            parts.append("Classes: " + ", ".join(indexed.classes))
        if indexed.functions:
            parts.append("Functions: " + ", ".join(indexed.functions))
        if indexed.imports:
            parts.append("Imports: " + "; ".join(indexed.imports[:20]))
        # Index stores comments (often includes module docstring text)
        docstringish = self._first_doc_like_comment(indexed)
        if docstringish:
            parts.append(f"Docstring: {docstringish}")
        return "\n".join(parts)

    def _class_text(self, indexed: IndexedFile, symbol: IndexedSymbol) -> str:
        methods = [
            s.name
            for s in indexed.symbols
            if s.kind == SymbolKind.METHOD and s.parent == symbol.name
        ]
        parts = [
            "Kind: class",
            f"Class: {symbol.name}",
            f"Module: {indexed.module_name}",
            f"File: {self._norm(indexed.relative_path)}",
        ]
        if methods:
            parts.append("Methods: " + ", ".join(methods))
        if symbol.decorators:
            parts.append("Decorators: " + ", ".join(symbol.decorators))
        docstringish = self._first_doc_like_comment(indexed)
        if docstringish:
            parts.append(f"Docstring: {docstringish}")
        return "\n".join(parts)

    def _function_text(self, indexed: IndexedFile, symbol: IndexedSymbol) -> str:
        kind_label = {
            SymbolKind.FUNCTION: "function",
            SymbolKind.METHOD: "method",
            SymbolKind.NESTED_FUNCTION: "nested_function",
        }.get(symbol.kind, "function")
        parts = [
            f"Kind: {kind_label}",
            f"Function: {symbol.name}",
            f"Module: {indexed.module_name}",
            f"File: {self._norm(indexed.relative_path)}",
        ]
        if symbol.parent:
            parts.append(f"Parent: {symbol.parent}")
        if symbol.decorators:
            parts.append("Decorators: " + ", ".join(symbol.decorators))
        if symbol.is_async:
            parts.append("Async: true")
        if symbol.is_generator:
            parts.append("Generator: true")
        # Parameters / returns are not in RepositoryIndex yet — use available context
        if indexed.imports:
            parts.append("Imports: " + "; ".join(indexed.imports[:10]))
        docstringish = self._comment_near_symbol(indexed, symbol)
        if docstringish:
            parts.append(f"Docstring: {docstringish}")
        return "\n".join(parts)

    @staticmethod
    def _function_key(symbol: IndexedSymbol) -> str:
        if symbol.parent and symbol.kind in {
            SymbolKind.METHOD,
            SymbolKind.NESTED_FUNCTION,
        }:
            return f"{symbol.parent}.{symbol.name}"
        return symbol.name

    @staticmethod
    def _first_doc_like_comment(indexed: IndexedFile) -> str | None:
        for comment in indexed.comments:
            text = comment.strip()
            if text:
                return text[:500]
        return None

    @staticmethod
    def _comment_near_symbol(indexed: IndexedFile, symbol: IndexedSymbol) -> str | None:
        # Index does not attach comments to symbols; use first non-empty comment as context.
        _ = symbol
        for comment in indexed.comments:
            text = comment.strip()
            if text:
                return text[:500]
        return None

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _assign_vector(
        record: FileEmbeddingRecord,
        kind: str,
        key: str,
        vector: list[float],
    ) -> None:
        if kind == "file":
            record.file = vector
        elif kind == "module":
            record.module = vector
        elif kind == "class":
            record.classes[key] = vector
        elif kind == "function":
            record.functions[key] = vector
        else:
            raise EmbeddingError(f"Unknown embedding entity kind: {kind}")

    def _persist(self, store: EmbeddingStore, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                store.model_dump_json(indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            raise EmbeddingError(f"Failed to write embeddings to {path}: {exc}") from exc

    @classmethod
    def _count_symbols(cls, store: EmbeddingStore) -> int:
        return sum(cls._count_file_symbols(record) for record in store.files.values())

    @staticmethod
    def _count_file_symbols(record: FileEmbeddingRecord) -> int:
        total = 0
        if record.file:
            total += 1
        if record.module:
            total += 1
        total += len(record.classes)
        total += len(record.functions)
        return total

    @staticmethod
    def _norm(path: str) -> str:
        return path.replace("\\", "/")


def _format_traceback(exc: Exception) -> str:
    """Format an exception traceback for logging."""
    import traceback

    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def require_index(index: RepositoryIndex | None) -> RepositoryIndex:
    """Helper for CLI: raise a typed error when the index is missing/invalid."""
    if index is None:
        raise IndexError_("No repository index found. Run `refactory index` first.")
    return index
