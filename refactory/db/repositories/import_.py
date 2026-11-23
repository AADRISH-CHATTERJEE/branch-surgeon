"""Repository pattern implementation for the Import entity."""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select

from refactory.db.models import ImportModel
from refactory.db.repositories.base import BaseRepository


class ImportRepository(BaseRepository[ImportModel]):
    """CRUD operations for import references."""

    model_class = ImportModel

    def list_by_file(self, file_id: str) -> Sequence[ImportModel]:
        """List all imports in a file."""
        stmt = select(ImportModel).where(ImportModel.file_id == file_id)
        return self._session.execute(stmt).scalars().all()

    def find_by_module(self, module: str) -> Sequence[ImportModel]:
        """Find all imports of a given module across the codebase."""
        stmt = select(ImportModel).where(ImportModel.module == module)
        return self._session.execute(stmt).scalars().all()

    def delete_by_file(self, file_id: str) -> int:
        """Delete all imports for a file. Returns count deleted."""
        imports = self.list_by_file(file_id)
        count = len(imports)
        for i in imports:
            self._session.delete(i)
        self._session.flush()
        return count
