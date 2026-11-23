"""Review suggestion lifecycle + recommendation synchronization."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.db.persistence import PersistenceService
    from refactory.db.query_service import RepositoryQueryService
    from refactory.recommendation.stats import RecommendationStatsService

ALLOWED_STATUSES = frozenset({"pending", "resolved", "ignored"})


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _norm_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip()


def suggestion_matches_recommendation(
    suggestion: dict[str, Any], recommendation: dict[str, Any]
) -> bool:
    """Heuristic link (title, or file+category). Prefer find_matching_recommendation."""
    return bool(
        find_match_rank(suggestion, recommendation) is not None
    )


def find_match_rank(
    suggestion: dict[str, Any], recommendation: dict[str, Any]
) -> int | None:
    """Return match priority rank (lower is better) or None if no match.

    Priority:
      1. recommendation_id exact
      2. exact suggestion id == recommendation id
      3. title + file
      4. title + category
      5. title only
      6. file + category
    """
    linked = _norm(suggestion.get("recommendation_id"))
    rid = _norm(recommendation.get("id"))
    if linked and linked == rid:
        return 1
    sid = _norm(suggestion.get("id"))
    if sid and sid == rid:
        return 2

    st = _norm(suggestion.get("title"))
    rt = _norm(recommendation.get("title"))
    file_path = _norm_path(suggestion.get("file"))
    hay = _norm_path(
        f"{recommendation.get('title') or ''} {recommendation.get('description') or ''}"
    )
    basename = file_path.rsplit("/", 1)[-1] if file_path else ""
    file_hit = bool(
        file_path
        and (file_path in hay or (basename and basename in hay))
    )
    cat = _norm(suggestion.get("category"))
    rtype = _norm(recommendation.get("type"))
    cat_hit = bool(cat and rtype and (cat == rtype or cat in rtype or rtype in cat))
    title_hit = bool(st and st == rt)

    if title_hit and file_hit:
        return 3
    if title_hit and cat_hit:
        return 4
    if title_hit:
        return 5
    if file_hit and (cat_hit or not cat or not rtype):
        return 6
    return None


class ReviewSuggestionStatusService:
    """Update suggestion status and keep recommendations / stats in sync."""

    def __init__(
        self,
        logger: "Logger",
        *,
        query_service: "RepositoryQueryService",
        persistence_service: "PersistenceService",
        recommendation_stats_service: "RecommendationStatsService | None" = None,
    ) -> None:
        self._logger = logger
        self._query = query_service
        self._persistence = persistence_service
        self._stats = recommendation_stats_service

    def update_status(
        self,
        *,
        review_id: str,
        suggestion_id: str,
        status: str,
        repository_id: str,
        updated_by: str = "local",
        sync_recommendations: bool = True,
    ) -> dict[str, Any]:
        status_norm = str(status or "").strip().lower()
        if status_norm not in ALLOWED_STATUSES:
            raise ValueError(
                f"Unsupported status '{status}'. Use pending, resolved, or ignored."
            )

        review = self._resolve_review(review_id, repository_id)
        canonical_review_id = str(review["id"])

        suggestion = self._persistence.get_review_suggestion(suggestion_id)
        if suggestion is None or suggestion.get("review_id") != canonical_review_id:
            raise LookupError(f"Suggestion '{suggestion_id}' not found")

        old_status = str(suggestion.get("status") or "pending")
        linked_rec_id = suggestion.get("recommendation_id")
        synced: list[str] = []
        if sync_recommendations and status_norm in {"resolved", "ignored"}:
            synced = self._sync_recommendations(
                repository_id=repository_id,
                suggestion=suggestion,
                status=status_norm,
            )
            if synced and not linked_rec_id:
                linked_rec_id = synced[0]

        updated = self._persistence.update_review_suggestion_status(
            suggestion_id,
            status_norm,
            updated_by=updated_by,
            recommendation_id=str(linked_rec_id) if linked_rec_id else None,
        )
        if updated is None:
            raise LookupError(f"Suggestion '{suggestion_id}' not found")

        if self._stats is not None:
            self._stats.invalidate(repository_id=repository_id)

        return {
            "suggestion": updated,
            "synced_recommendation_ids": synced,
            "review_id": canonical_review_id,
            "old_status": old_status,
            "new_status": status_norm,
            "updated_by": updated_by,
        }

    def _resolve_review(self, review_id: str, repository_id: str) -> dict[str, Any]:
        """Resolve by UUID or PR number (UI detail URLs often use the PR number)."""
        review = self._query.get_review(review_id)
        if review is not None and review.get("repository_id") == repository_id:
            return review

        reviews = self._query.get_reviews(repository_id, limit=100)
        match = next(
            (r for r in reviews if str(r.get("pr_number")) == str(review_id)),
            None,
        )
        if match is None:
            raise LookupError(f"Review '{review_id}' not found")
        return match

    def auto_resolve_for_repository(self, repository_id: str) -> dict[str, int]:
        """Mark pending suggestions resolved when no matching open recommendation remains."""
        pending_suggestions = self._persistence.list_pending_review_suggestions(
            repository_id
        )
        open_recs = self._query.get_recommendations(
            repository_id, status="pending", limit=10_000
        )
        resolved = 0
        for suggestion in pending_suggestions:
            still_open = any(
                suggestion_matches_recommendation(suggestion, rec) for rec in open_recs
            )
            if still_open:
                continue
            linked = self._find_best_matching_recommendation(repository_id, suggestion)
            self._persistence.update_review_suggestion_status(
                str(suggestion["id"]),
                "resolved",
                updated_by="post-transformation",
                recommendation_id=linked,
            )
            resolved += 1

        if resolved and self._stats is not None:
            self._stats.invalidate(repository_id=repository_id)
        return {"resolved": resolved, "checked": len(pending_suggestions)}

    def _sync_recommendations(
        self,
        *,
        repository_id: str,
        suggestion: dict[str, Any],
        status: str,
    ) -> list[str]:
        """Update at most one matching recommendation — never create duplicates."""
        match = self._find_best_matching_recommendation_row(repository_id, suggestion)
        if match is None:
            return []
        rid = str(match["id"])
        if self._stats is not None:
            self._stats.set_status(rid, status)
        else:
            self._persistence.update_recommendation_status(rid, status)
        return [rid]

    def _find_best_matching_recommendation(
        self, repository_id: str, suggestion: dict[str, Any]
    ) -> str | None:
        row = self._find_best_matching_recommendation_row(repository_id, suggestion)
        return str(row["id"]) if row else None

    def _find_best_matching_recommendation_row(
        self, repository_id: str, suggestion: dict[str, Any]
    ) -> dict[str, Any] | None:
        linked = suggestion.get("recommendation_id")
        if linked:
            row = self._query.get_recommendation(str(linked))
            if row and row.get("repository_id") == repository_id:
                return row

        # Prefer open recommendations, then any status (still no duplicates).
        candidates = self._query.get_recommendations(
            repository_id, status="pending", limit=10_000
        )
        if not candidates:
            candidates = self._query.get_recommendations(repository_id, limit=10_000)

        best: tuple[int, dict[str, Any]] | None = None
        for rec in candidates:
            rank = find_match_rank(suggestion, rec)
            if rank is None:
                continue
            if best is None or rank < best[0]:
                best = (rank, rec)
        return best[1] if best else None
