"""Embedding store backends for retrieval (swap-friendly).

Default backend reads ``.refactory/embeddings.json`` only — never regenerates
vectors or talks to Chroma / FAISS / remote indexes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from refactory.embedding.models import EmbeddingStore
from refactory.embedding.service import EMBEDDINGS_FILENAME, REFACTORY_DIR


@runtime_checkable
class EmbeddingStoreBackend(Protocol):
    """Load a persisted EmbeddingStore for a repository root."""

    def load(self, root: Path) -> EmbeddingStore | None:
        """Return the store, or None when missing / unreadable."""
        ...

    def store_path(self, root: Path) -> Path:
        ...


class JsonFileEmbeddingStoreBackend:
    """Local JSON backend backed by EmbeddingService's persistence format."""

    def __init__(
        self,
        *,
        refactory_dir: str = REFACTORY_DIR,
        filename: str = EMBEDDINGS_FILENAME,
    ) -> None:
        self._refactory_dir = refactory_dir
        self._filename = filename

    def store_path(self, root: Path) -> Path:
        return Path(root).resolve() / self._refactory_dir / self._filename

    def load(self, root: Path) -> EmbeddingStore | None:
        path = self.store_path(root)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return EmbeddingStore.model_validate(data)
        except Exception:  # noqa: BLE001 — malformed / corrupted store
            return None
