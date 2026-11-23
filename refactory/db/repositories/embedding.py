"""Repository pattern implementation for the Embedding entity."""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select

from refactory.db.models import EmbeddingModel
from refactory.db.repositories.base import BaseRepository


class EmbeddingRepository(BaseRepository[EmbeddingModel]):
    """CRUD operations for embedding metadata."""

    model_class = EmbeddingModel

    def list_by_file(self, file_id: str) -> Sequence[EmbeddingModel]:
        """List all embeddings for a file."""
        stmt = select(EmbeddingModel).where(EmbeddingModel.file_id == file_id)
        return self._session.execute(stmt).scalars().all()

    def get_by_chunk(self, chunk_id: str) -> EmbeddingModel | None:
        """Look up an embedding by chunk ID."""
        stmt = select(EmbeddingModel).where(EmbeddingModel.chunk_id == chunk_id)
        return self._session.execute(stmt).scalar_one_or_none()

    def delete_by_file(self, file_id: str) -> int:
        """Delete all embeddings for a file. Returns count deleted."""
        embeddings = self.list_by_file(file_id)
        count = len(embeddings)
        for e in embeddings:
            self._session.delete(e)
        self._session.flush()
        return count
