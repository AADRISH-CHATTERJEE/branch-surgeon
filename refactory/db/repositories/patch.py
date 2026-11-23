"""Repository pattern implementation for persisted AI patches."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import select

from refactory.db.models import PatchModel
from refactory.db.repositories.base import BaseRepository


class PatchRepository(BaseRepository[PatchModel]):
    """CRUD operations for recommendation patches."""

    model_class = PatchModel

    def list_by_recommendation(
        self, recommendation_id: str, *, limit: int = 20
    ) -> Sequence[PatchModel]:
        stmt = (
            select(PatchModel)
            .where(PatchModel.recommendation_id == recommendation_id)
            .order_by(PatchModel.created_at.desc())
            .limit(limit)
        )
        return self._session.execute(stmt).scalars().all()

    def list_by_repository(
        self, repository_id: str, *, limit: int = 50
    ) -> Sequence[PatchModel]:
        stmt = (
            select(PatchModel)
            .where(PatchModel.repository_id == repository_id)
            .order_by(PatchModel.created_at.desc())
            .limit(limit)
        )
        return self._session.execute(stmt).scalars().all()

    def mark_applied(
        self,
        patch_id: str,
        *,
        applied_by: str,
        git_commit: str | None,
        applied_at: datetime,
    ) -> PatchModel | None:
        return self.update(
            patch_id,
            status="applied",
            applied_at=applied_at,
            applied_by=applied_by,
            git_commit=git_commit,
            failure_reason=None,
        )

    def mark_failed(
        self,
        patch_id: str,
        *,
        failure_reason: str,
        status: str = "failed",
    ) -> PatchModel | None:
        return self.update(
            patch_id,
            status=status,
            failure_reason=failure_reason,
        )

    def mark_rolled_back(
        self,
        patch_id: str,
        *,
        rollback_metadata: dict[str, Any] | None,
        failure_reason: str | None = None,
    ) -> PatchModel | None:
        return self.update(
            patch_id,
            status="rolled_back",
            rollback_metadata=rollback_metadata or {},
            failure_reason=failure_reason,
            applied_at=None,
            applied_by=None,
        )
