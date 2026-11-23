"""Repository pattern implementation for the Symbol entity."""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select

from refactory.db.models import SymbolModel
from refactory.db.repositories.base import BaseRepository


class SymbolRepository(BaseRepository[SymbolModel]):
    """CRUD operations for code symbols."""

    model_class = SymbolModel

    def list_by_file(self, file_id: str) -> Sequence[SymbolModel]:
        """List all symbols in a file."""
        stmt = select(SymbolModel).where(SymbolModel.file_id == file_id)
        return self._session.execute(stmt).scalars().all()

    def find_by_name(self, name: str, *, symbol_type: str | None = None) -> Sequence[SymbolModel]:
        """Find symbols by name across all files, optionally filtered by type."""
        stmt = select(SymbolModel).where(SymbolModel.name == name)
        if symbol_type:
            stmt = stmt.where(SymbolModel.type == symbol_type)
        return self._session.execute(stmt).scalars().all()

    def delete_by_file(self, file_id: str) -> int:
        """Delete all symbols for a file. Returns count deleted."""
        symbols = self.list_by_file(file_id)
        count = len(symbols)
        for s in symbols:
            self._session.delete(s)
        self._session.flush()
        return count
