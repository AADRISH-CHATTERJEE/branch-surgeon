"""Repository pattern implementation for the File entity."""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select

from refactory.db.models import FileModel
from refactory.db.repositories.base import BaseRepository


class FileRepository(BaseRepository[FileModel]):
    """CRUD operations for indexed files."""

    model_class = FileModel

    def get_by_repo_path(self, repository_id: str, path: str) -> FileModel | None:
        """Look up a file by repository and relative path."""
        stmt = select(FileModel).where(
            FileModel.repository_id == repository_id,
            FileModel.path == path,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def list_by_repository(
        self, repository_id: str, *, language: str | None = None, limit: int = 1000
    ) -> Sequence[FileModel]:
        """List files belonging to a repository, optionally filtered by language."""
        stmt = select(FileModel).where(FileModel.repository_id == repository_id)
        if language:
            stmt = stmt.where(FileModel.language == language)
        stmt = stmt.limit(limit)
        return self._session.execute(stmt).scalars().all()

    def upsert(self, repository_id: str, path: str, **kwargs) -> FileModel:
        """Insert or update a file record."""
        existing = self.get_by_repo_path(repository_id, path)
        if existing:
            for key, value in kwargs.items():
                setattr(existing, key, value)
            self._session.flush()
            return existing
        return self.create(repository_id=repository_id, path=path, **kwargs)
