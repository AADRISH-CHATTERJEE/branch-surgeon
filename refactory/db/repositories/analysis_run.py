"""Repository pattern implementation for the AnalysisRun entity."""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select

from refactory.db.models import AnalysisRunModel
from refactory.db.repositories.base import BaseRepository


class AnalysisRunRepository(BaseRepository[AnalysisRunModel]):
    """CRUD operations for analysis run records."""

    model_class = AnalysisRunModel

    def list_by_repository(
        self,
        repository_id: str,
        *,
        command: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> Sequence[AnalysisRunModel]:
        """List analysis runs for a repository with optional filters, most recent first."""
        stmt = select(AnalysisRunModel).where(
            AnalysisRunModel.repository_id == repository_id
        )
        if command:
            stmt = stmt.where(AnalysisRunModel.command == command)
        if status:
            stmt = stmt.where(AnalysisRunModel.status == status)
        stmt = stmt.order_by(AnalysisRunModel.created_at.desc()).limit(limit)
        return self._session.execute(stmt).scalars().all()

    def get_latest(
        self, repository_id: str, *, command: str | None = None
    ) -> AnalysisRunModel | None:
        """Get the most recent analysis run for a repository."""
        stmt = select(AnalysisRunModel).where(
            AnalysisRunModel.repository_id == repository_id
        )
        if command:
            stmt = stmt.where(AnalysisRunModel.command == command)
        stmt = stmt.order_by(AnalysisRunModel.created_at.desc()).limit(1)
        return self._session.execute(stmt).scalar_one_or_none()

    def list_by_commit(
        self, repository_id: str, git_commit: str
    ) -> Sequence[AnalysisRunModel]:
        """List all analysis runs for a specific commit."""
        stmt = (
            select(AnalysisRunModel)
            .where(
                AnalysisRunModel.repository_id == repository_id,
                AnalysisRunModel.git_commit == git_commit,
            )
            .order_by(AnalysisRunModel.created_at.desc())
        )
        return self._session.execute(stmt).scalars().all()

    def delete_by_repository(self, repository_id: str) -> int:
        """Delete all analysis runs for a repository. Returns count deleted."""
        runs = self.list_by_repository(repository_id, limit=100000)
        count = 0
        for r in runs:
            self._session.delete(r)
            count += 1
        self._session.flush()
        return count
