"""Repository pattern implementation for the ReviewSuggestion entity."""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select

from refactory.db.models import ReviewModel, ReviewSuggestionModel
from refactory.db.repositories.base import BaseRepository


class ReviewSuggestionRepository(BaseRepository[ReviewSuggestionModel]):
    """CRUD operations for review suggestions / findings."""

    model_class = ReviewSuggestionModel

    def list_by_review(self, review_id: str) -> Sequence[ReviewSuggestionModel]:
        """List all suggestions for a review."""
        stmt = select(ReviewSuggestionModel).where(
            ReviewSuggestionModel.review_id == review_id
        )
        return self._session.execute(stmt).scalars().all()

    def list_by_review_ids(
        self, review_ids: Sequence[str]
    ) -> Sequence[ReviewSuggestionModel]:
        """List suggestions for many reviews (one query)."""
        if not review_ids:
            return []
        stmt = select(ReviewSuggestionModel).where(
            ReviewSuggestionModel.review_id.in_(list(review_ids))
        )
        return self._session.execute(stmt).scalars().all()

    def list_by_severity(
        self, review_id: str, severity: str
    ) -> Sequence[ReviewSuggestionModel]:
        """List suggestions filtered by severity."""
        stmt = select(ReviewSuggestionModel).where(
            ReviewSuggestionModel.review_id == review_id,
            ReviewSuggestionModel.severity == severity,
        )
        return self._session.execute(stmt).scalars().all()

    def list_pending_for_repository(
        self, repository_id: str, *, limit: int = 5_000
    ) -> Sequence[ReviewSuggestionModel]:
        """Pending suggestions across all reviews for a repository."""
        stmt = (
            select(ReviewSuggestionModel)
            .join(ReviewModel, ReviewModel.id == ReviewSuggestionModel.review_id)
            .where(
                ReviewModel.repository_id == repository_id,
                ReviewSuggestionModel.status == "pending",
            )
            .limit(limit)
        )
        return self._session.execute(stmt).scalars().all()

    def delete_by_review(self, review_id: str) -> int:
        """Delete all suggestions for a review. Returns count deleted."""
        suggestions = self.list_by_review(review_id)
        count = len(suggestions)
        for s in suggestions:
            self._session.delete(s)
        self._session.flush()
        return count
