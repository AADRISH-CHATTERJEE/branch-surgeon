"""RecommendationService — orchestrates recommendation patch apply / rollback.

Controllers call only this service (or thin wrappers). Business logic and
repository access live here / in PatchService / PersistenceService.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from refactory.recommendation.models import RecommendationStatus
from refactory.recommendation.patch_models import (
    PatchApplyError,
    PatchApplyResult,
)

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.db.persistence import PersistenceService
    from refactory.db.query_service import RepositoryQueryService
    from refactory.git.service import GitService
    from refactory.recommendation.patch_apply_service import PatchService
    from refactory.recommendation.stats import RecommendationStatsService


class RecommendationService:
    """Lifecycle operations for recommendations (apply / rollback patches)."""

    def __init__(
        self,
        *,
        logger: "Logger",
        git_service: "GitService",
        query_service: "RepositoryQueryService",
        persistence_service: "PersistenceService",
        patch_service: "PatchService",
        recommendation_stats_service: "RecommendationStatsService | None" = None,
    ) -> None:
        self._logger = logger
        self._git = git_service
        self._query = query_service
        self._persistence = persistence_service
        self._patches = patch_service
        self._stats = recommendation_stats_service

    def apply_patch(
        self,
        recommendation_id: str,
        *,
        patch_id: str | None = None,
        dry_run: bool = False,
        applied_by: str = "local",
        repo_root: Path | None = None,
    ) -> PatchApplyResult:
        """Apply the latest (or specified) patch for a recommendation."""
        root = (repo_root or self._git.get_root_path()).resolve()
        repo = self._query.get_repository_by_root(str(root))
        if repo is None:
            raise PatchApplyError(
                "No repository record yet — configure repo root and run index first.",
                status_code=404,
            )

        rec = self._query.get_recommendation(recommendation_id)
        if rec is None or rec.get("repository_id") != repo["id"]:
            raise PatchApplyError(
                f"Recommendation '{recommendation_id}' not found.",
                status_code=404,
            )

        resolved_patch_id = patch_id or self._latest_patch_id(recommendation_id)
        if not resolved_patch_id:
            raise PatchApplyError(
                "No patch available for this recommendation — generate a patch first.",
                status_code=404,
            )

        stored = self._persistence.get_recommendation_patch(resolved_patch_id)
        if stored is None or stored.get("recommendation_id") != recommendation_id:
            raise PatchApplyError(
                f"Patch '{resolved_patch_id}' not found for this recommendation.",
                status_code=404,
            )

        result = self._patches.apply(
            resolved_patch_id,
            root,
            dry_run=dry_run,
            applied_by=applied_by,
        )

        if result.applied and not dry_run:
            updated = self._persistence.update_recommendation_status(
                recommendation_id, RecommendationStatus.APPLIED.value
            )
            result.recommendation_status = RecommendationStatus.APPLIED.value
            result.recommendation = updated
            if self._stats is not None:
                self._stats.invalidate(
                    repository_id=str(repo["id"]),
                    repo_root=root,
                )
        else:
            result.recommendation_status = rec.get("status")
            result.recommendation = rec

        return result

    def apply_patch_by_id(
        self,
        patch_id: str,
        *,
        dry_run: bool = False,
        applied_by: str = "local",
        repo_root: Path | None = None,
    ) -> PatchApplyResult:
        """Apply a patch by id; updates owning recommendation status on success."""
        root = (repo_root or self._git.get_root_path()).resolve()
        result = self._patches.apply(
            patch_id, root, dry_run=dry_run, applied_by=applied_by
        )
        if result.applied and result.recommendation_id and not dry_run:
            updated = self._persistence.update_recommendation_status(
                result.recommendation_id, RecommendationStatus.APPLIED.value
            )
            result.recommendation_status = RecommendationStatus.APPLIED.value
            result.recommendation = updated
            if self._stats is not None:
                self._stats.invalidate(repo_root=root)
                if updated and updated.get("repository_id"):
                    self._stats.invalidate(repository_id=str(updated["repository_id"]))
        elif result.recommendation_id:
            result.recommendation = self._query.get_recommendation(
                result.recommendation_id
            )
            result.recommendation_status = (result.recommendation or {}).get("status")
        return result

    def rollback_patch(
        self,
        recommendation_id: str,
        *,
        patch_id: str | None = None,
        applied_by: str = "local",
        repo_root: Path | None = None,
    ) -> PatchApplyResult:
        """Roll back an applied patch and mark recommendation rolled_back."""
        root = (repo_root or self._git.get_root_path()).resolve()
        repo = self._query.get_repository_by_root(str(root))
        if repo is None:
            raise PatchApplyError(
                "No repository record yet — configure repo root and run index first.",
                status_code=404,
            )
        rec = self._query.get_recommendation(recommendation_id)
        if rec is None or rec.get("repository_id") != repo["id"]:
            raise PatchApplyError(
                f"Recommendation '{recommendation_id}' not found.",
                status_code=404,
            )

        resolved = patch_id or self._latest_applied_patch_id(recommendation_id)
        if not resolved:
            raise PatchApplyError(
                "No applied patch to roll back for this recommendation.",
                status_code=404,
            )

        result = self._patches.rollback(resolved, root, applied_by=applied_by)
        updated = self._persistence.update_recommendation_status(
            recommendation_id, RecommendationStatus.ROLLED_BACK.value
        )
        result.recommendation_status = RecommendationStatus.ROLLED_BACK.value
        result.recommendation = updated
        if self._stats is not None:
            self._stats.invalidate(repository_id=str(repo["id"]), repo_root=root)
        return result

    def list_patches(
        self, recommendation_id: str, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        return self._persistence.get_patches_for_recommendation(
            recommendation_id, limit=limit
        )

    def _latest_patch_id(self, recommendation_id: str) -> str | None:
        rows = self._persistence.get_patches_for_recommendation(
            recommendation_id, limit=1
        )
        return rows[0]["id"] if rows else None

    def _latest_applied_patch_id(self, recommendation_id: str) -> str | None:
        rows = self._persistence.get_patches_for_recommendation(
            recommendation_id, limit=20
        )
        for row in rows:
            if row.get("status") == "applied":
                return row["id"]
        return None
