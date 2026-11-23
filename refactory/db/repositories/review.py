"""Repository pattern implementation for the Review entity."""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select

from refactory.db.models import ReviewModel
from refactory.db.repositories.base import BaseRepository


class ReviewRepository(BaseRepository[ReviewModel]):
    """CRUD operations for code reviews."""

    model_class = ReviewModel

    def list_by_repository(
        self, repository_id: str, *, limit: int = 50
    ) -> Sequence[ReviewModel]:
        """List reviews for a repository, most recent first."""
        stmt = (
            select(ReviewModel)
            .where(ReviewModel.repository_id == repository_id)
            .order_by(ReviewModel.created_at.desc())
            .limit(limit)
        )
        return self._session.execute(stmt).scalars().all()

    def get_by_pr(self, repository_id: str, pr_number: int) -> Sequence[ReviewModel]:
        """Get all reviews for a specific PR."""
        stmt = (
            select(ReviewModel)
            .where(
                ReviewModel.repository_id == repository_id,
                ReviewModel.pr_number == pr_number,
            )
            .order_by(ReviewModel.created_at.desc())
        )
        return self._session.execute(stmt).scalars().all()

    def get_latest(self, repository_id: str) -> ReviewModel | None:
        """Get the most recent review for a repository."""
        stmt = (
            select(ReviewModel)
            .where(ReviewModel.repository_id == repository_id)
            .order_by(ReviewModel.created_at.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()
