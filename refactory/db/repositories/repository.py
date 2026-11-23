"""Repository pattern implementation for the Repository entity."""

from __future__ import annotations

from sqlalchemy import select

from refactory.db.models import RepositoryModel
from refactory.db.repositories.base import BaseRepository


class RepositoryRepository(BaseRepository[RepositoryModel]):
    """CRUD operations for code repositories."""

    model_class = RepositoryModel

    def get_by_root_path(self, root_path: str) -> RepositoryModel | None:
        """Look up a repository by its filesystem root path."""
        stmt = select(RepositoryModel).where(RepositoryModel.root_path == root_path)
        return self._session.execute(stmt).scalar_one_or_none()

    def get_or_create(self, *, name: str, root_path: str, **kwargs) -> RepositoryModel:
        """Get an existing repository by root_path, or create a new one."""
        existing = self.get_by_root_path(root_path)
        if existing is not None:
            return existing
        return self.create(name=name, root_path=root_path, **kwargs)

    def list_active(self, *, limit: int = 100) -> list[RepositoryModel]:
        """List repositories ordered by last update."""
        stmt = (
            select(RepositoryModel)
            .order_by(RepositoryModel.updated_at.desc())
            .limit(limit)
        )
        return list(self._session.execute(stmt).scalars().all())
