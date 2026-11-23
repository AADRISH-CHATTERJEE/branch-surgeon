"""ChromaDB storage adapter skeleton — local persistence in a later phase."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from loguru import Logger


class ChromaStore:
    def __init__(self, persist_path: Path, collection_name: str, logger: "Logger") -> None:
        self._persist_path = persist_path
        self._collection_name = collection_name
        self._logger = logger

    def upsert(
        self,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        self._logger.debug("ChromaStore.upsert called (n={})", len(ids))
        raise NotImplementedError("Chroma upsert not implemented yet")

    def query(self, embedding: list[float], *, top_k: int = 8) -> list[dict[str, Any]]:
        self._logger.debug("ChromaStore.query called (top_k={})", top_k)
        raise NotImplementedError("Chroma query not implemented yet")

    def count(self) -> int:
        self._logger.debug("ChromaStore.count called")
        raise NotImplementedError("Chroma count not implemented yet")

    def clear(self) -> None:
        self._logger.debug("ChromaStore.clear called")
        raise NotImplementedError("Chroma clear not implemented yet")
