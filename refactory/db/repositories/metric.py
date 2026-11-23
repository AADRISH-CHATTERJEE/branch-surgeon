"""Repository pattern implementation for the Metric entity."""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select

from refactory.db.models import MetricModel
from refactory.db.repositories.base import BaseRepository


class MetricRepository(BaseRepository[MetricModel]):
    """CRUD operations for historical metrics."""

    model_class = MetricModel

    def list_by_repository(
        self,
        repository_id: str,
        *,
        metric_name: str | None = None,
        branch: str | None = None,
        limit: int = 100,
    ) -> Sequence[MetricModel]:
        """List metrics for a repository with optional filters, most recent first."""
        stmt = select(MetricModel).where(MetricModel.repository_id == repository_id)
        if metric_name:
            stmt = stmt.where(MetricModel.metric_name == metric_name)
        if branch:
            stmt = stmt.where(MetricModel.branch == branch)
        stmt = stmt.order_by(MetricModel.created_at.desc()).limit(limit)
        return self._session.execute(stmt).scalars().all()

    def list_by_commit(
        self, repository_id: str, git_commit: str
    ) -> Sequence[MetricModel]:
        """List all metrics recorded for a specific commit."""
        stmt = (
            select(MetricModel)
            .where(
                MetricModel.repository_id == repository_id,
                MetricModel.git_commit == git_commit,
            )
            .order_by(MetricModel.metric_name)
        )
        return self._session.execute(stmt).scalars().all()

    def delete_by_repository(self, repository_id: str) -> int:
        """Delete all metrics for a repository. Returns count deleted."""
        metrics = self.list_by_repository(repository_id, limit=100000)
        count = 0
        for m in metrics:
            self._session.delete(m)
            count += 1
        self._session.flush()
        return count
