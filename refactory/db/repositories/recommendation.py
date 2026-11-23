"""Repository pattern implementation for the Recommendation entity."""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import func, select

from refactory.db.models import RecommendationModel
from refactory.db.repositories.base import BaseRepository


class RecommendationRepository(BaseRepository[RecommendationModel]):
    """CRUD operations for engineering recommendations."""

    model_class = RecommendationModel

    def list_by_repository(
        self,
        repository_id: str,
        *,
        status: str | None = None,
        priority: str | None = None,
        limit: int = 100,
    ) -> Sequence[RecommendationModel]:
        """List recommendations with optional status/priority filters."""
        stmt = select(RecommendationModel).where(
            RecommendationModel.repository_id == repository_id
        )
        if status:
            stmt = stmt.where(RecommendationModel.status == status)
        if priority:
            stmt = stmt.where(RecommendationModel.priority == priority)
        stmt = stmt.order_by(RecommendationModel.created_at.desc()).limit(limit)
        return self._session.execute(stmt).scalars().all()

    def count_by_repository(
        self,
        repository_id: str,
        *,
        status: str | None = None,
        priority: str | None = None,
    ) -> int:
        """Count persisted recommendations (no pagination)."""
        stmt = (
            select(func.count())
            .select_from(RecommendationModel)
            .where(RecommendationModel.repository_id == repository_id)
        )
        if status:
            stmt = stmt.where(RecommendationModel.status == status)
        if priority:
            stmt = stmt.where(RecommendationModel.priority == priority)
        return int(self._session.execute(stmt).scalar_one())

    def aggregate_by_repository(self, repository_id: str) -> dict[str, Any]:
        """GROUP BY aggregates used exclusively by RecommendationStatsService.

        Priority tiles (critical/high/medium/low) count **pending-only** rows
        (open work). Lifecycle tiles come from ``by_status``.
        ``by_priority_all`` retains all-status priority counts for diagnostics.
        """
        base = RecommendationModel.repository_id == repository_id
        # Open work for severity tiles — pending / rolled_back only.
        open_base = base & RecommendationModel.status.in_(("pending", "rolled_back"))

        total = int(
            self._session.execute(
                select(func.count())
                .select_from(RecommendationModel)
                .where(base)
            ).scalar_one()
        )

        by_priority: dict[str, int] = {}
        for priority, count in self._session.execute(
            select(RecommendationModel.priority, func.count())
            .where(open_base)
            .group_by(RecommendationModel.priority)
        ).all():
            by_priority[str(priority or "medium")] = int(count)

        by_priority_all: dict[str, int] = {}
        for priority, count in self._session.execute(
            select(RecommendationModel.priority, func.count())
            .where(base)
            .group_by(RecommendationModel.priority)
        ).all():
            by_priority_all[str(priority or "medium")] = int(count)

        by_status: dict[str, int] = {}
        for status, count in self._session.execute(
            select(RecommendationModel.status, func.count())
            .where(base)
            .group_by(RecommendationModel.status)
        ).all():
            by_status[str(status or "pending")] = int(count)

        by_type: dict[str, int] = {}
        for rec_type, count in self._session.execute(
            select(RecommendationModel.type, func.count())
            .where(base)
            .group_by(RecommendationModel.type)
        ).all():
            by_type[str(rec_type or "unknown")] = int(count)

        last_created = self._session.execute(
            select(func.max(RecommendationModel.created_at)).where(base)
        ).scalar_one()
        last_resolved = self._session.execute(
            select(func.max(RecommendationModel.resolved_at)).where(base)
        ).scalar_one()
        last_updated = last_created
        if last_resolved is not None and (
            last_updated is None or last_resolved > last_updated
        ):
            last_updated = last_resolved

        return {
            "total": total,
            "by_priority": by_priority,
            "by_priority_all": by_priority_all,
            "by_status": by_status,
            "by_type": by_type,
            "last_updated": last_updated,
        }

    def list_by_type(self, repository_id: str, rec_type: str) -> Sequence[RecommendationModel]:
        """List recommendations of a specific type."""
        stmt = (
            select(RecommendationModel)
            .where(
                RecommendationModel.repository_id == repository_id,
                RecommendationModel.type == rec_type,
            )
            .order_by(RecommendationModel.created_at.desc())
        )
        return self._session.execute(stmt).scalars().all()

    def update_status(self, rec_id: str, status: str) -> RecommendationModel | None:
        """Update just the status field of a recommendation."""
        return self.update(rec_id, status=status)

    def list_all_for_repository(
        self, repository_id: str, *, limit: int = 10_000
    ) -> Sequence[RecommendationModel]:
        """List all recommendations for reconciliation (high limit)."""
        stmt = (
            select(RecommendationModel)
            .where(RecommendationModel.repository_id == repository_id)
            .order_by(RecommendationModel.created_at.desc())
            .limit(limit)
        )
        return self._session.execute(stmt).scalars().all()

    def upsert(
        self,
        *,
        recommendation_id: str,
        repository_id: str,
        **values: Any,
    ) -> RecommendationModel:
        """Create or update a recommendation by primary key."""
        existing = self.get_by_id(recommendation_id)
        if existing is None:
            return self.create(id=recommendation_id, repository_id=repository_id, **values)
        for key, value in values.items():
            setattr(existing, key, value)
        self._session.flush()
        return existing
