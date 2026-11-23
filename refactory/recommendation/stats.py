"""Recommendation Statistics Service — single source of truth for recommendation counts.

Branch Surgeon, Recommendations page, Dashboard, and any other consumer MUST use
``RecommendationStatsService.get_repository_summary`` instead of counting rows
locally or issuing ad-hoc COUNT / GROUP BY queries.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.db.persistence import PersistenceService
    from refactory.db.query_service import RepositoryQueryService

# Bump when the summary schema or bucket mapping changes.
SUMMARY_VERSION = "2"

# Canonical lifecycle (documented for UI legend):
#   pending  → open work, not addressed
#   applied  → AI patch applied, awaiting verification
#   resolved → verified fixed
#   ignored  → intentionally dismissed
PENDING_STATUSES = frozenset({"pending", "rolled_back"})
APPLIED_STATUSES = frozenset({"applied"})
RESOLVED_STATUSES = frozenset(
    {"completed", "accepted", "implemented", "resolved"}
)
IGNORED_STATUSES = frozenset({"rejected", "deferred", "ignored"})


class RecommendationRepositorySummary(BaseModel):
    """Canonical recommendation statistics for one repository."""

    total: int = 0
    pending: int = 0
    applied: int = 0
    resolved: int = 0
    ignored: int = 0
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
    by_priority: dict[str, int] = Field(default_factory=dict)
    last_updated: datetime | None = None
    repository_id: str = ""
    repository: str = ""
    repo_root: str = ""
    branch: str = ""
    source: str = "RecommendationStatsService"
    version: str = SUMMARY_VERSION


class RecommendationStatsService:
    """Only place allowed to calculate recommendation repository totals."""

    def __init__(
        self,
        logger: "Logger",
        query_service: "RepositoryQueryService",
        *,
        persistence_service: "PersistenceService | None" = None,
    ) -> None:
        self._logger = logger
        self._query = query_service
        self._persistence = persistence_service
        self._cache: dict[str, RecommendationRepositorySummary] = {}
        self._lock = RLock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_repository_summary(
        self,
        *,
        repo_root: str | Path,
        repository_id: str | None = None,
        branch: str | None = None,
        force_refresh: bool = False,
    ) -> RecommendationRepositorySummary:
        """Return cached or freshly computed repository recommendation stats."""
        root = str(Path(repo_root).resolve())
        repo = self._resolve_repo(root=root, repository_id=repository_id)
        if repo is None:
            return RecommendationRepositorySummary(
                repo_root=root,
                branch=branch or "",
                last_updated=datetime.now(timezone.utc),
            )

        rid = str(repo["id"])
        cache_key = rid
        with self._lock:
            if not force_refresh and cache_key in self._cache:
                cached = self._cache[cache_key].model_copy(deep=True)
                if branch is not None:
                    cached.branch = branch
                cached.repo_root = root
                return cached

        summary = self._compute_summary(repo=repo, repo_root=root, branch=branch or "")
        with self._lock:
            self._cache[cache_key] = summary
        return summary.model_copy(deep=True)

    def invalidate(
        self,
        *,
        repository_id: str | None = None,
        repo_root: str | Path | None = None,
    ) -> None:
        """Drop cached summary so the next read recomputes from the DB."""
        with self._lock:
            if repository_id:
                self._cache.pop(str(repository_id), None)
            if repo_root is not None:
                root = str(Path(repo_root).resolve())
                for key, value in list(self._cache.items()):
                    if value.repo_root == root:
                        self._cache.pop(key, None)
            if repository_id is None and repo_root is None:
                self._cache.clear()
        self._logger.debug(
            "RecommendationStatsService cache invalidated (repository_id={}, repo_root={})",
            repository_id,
            str(repo_root) if repo_root is not None else None,
        )

    def refresh(
        self,
        *,
        repo_root: str | Path,
        repository_id: str | None = None,
        branch: str | None = None,
    ) -> RecommendationRepositorySummary:
        """Invalidate cache and recompute repository recommendation totals."""
        self.invalidate(repository_id=repository_id, repo_root=repo_root)
        return self.get_repository_summary(
            repo_root=repo_root,
            repository_id=repository_id,
            branch=branch,
            force_refresh=True,
        )

    def invalidate_for_recommendation(self, recommendation_id: str) -> None:
        """Invalidate the cache for the repository owning ``recommendation_id``."""
        try:
            row = self._query.get_recommendation(recommendation_id)
        except Exception:  # noqa: BLE001
            row = None
        if row and row.get("repository_id"):
            self.invalidate(repository_id=str(row["repository_id"]))
        else:
            self.invalidate()

    # ------------------------------------------------------------------
    # Mutations that always refresh the cache
    # ------------------------------------------------------------------

    def set_status(
        self,
        recommendation_id: str,
        status: str,
        *,
        updated_by: str | None = None,
        resolution_notes: str | None = None,
        verification_status: str | None = None,
    ) -> dict[str, Any] | None:
        if self._persistence is None:
            raise RuntimeError("PersistenceService required for status updates")
        row = self._persistence.update_recommendation_status(
            recommendation_id,
            status,
            updated_by=updated_by,
            resolution_notes=resolution_notes,
            verification_status=verification_status,
        )
        if row:
            self.invalidate(repository_id=str(row.get("repository_id") or ""))
            if not row.get("repository_id"):
                self.invalidate_for_recommendation(recommendation_id)
        return row

    def set_priority(
        self, recommendation_id: str, priority: str
    ) -> dict[str, Any] | None:
        if self._persistence is None:
            raise RuntimeError("PersistenceService required for priority updates")
        row = self._persistence.update_recommendation_fields(
            recommendation_id, priority=priority
        )
        if row:
            self.invalidate(repository_id=str(row.get("repository_id") or ""))
        else:
            self.invalidate_for_recommendation(recommendation_id)
        return row

    def delete_recommendation(self, recommendation_id: str) -> bool:
        if self._persistence is None:
            raise RuntimeError("PersistenceService required for deletes")
        row = self._query.get_recommendation(recommendation_id)
        rid = str(row.get("repository_id") or "") if row else ""
        deleted = self._persistence.delete_recommendation(recommendation_id)
        if deleted:
            if rid:
                self.invalidate(repository_id=rid)
            else:
                self.invalidate()
        return deleted

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_repo(
        self, *, root: str, repository_id: str | None
    ) -> dict[str, Any] | None:
        if repository_id:
            repo = self._query.get_repository(repository_id)
            if repo is not None:
                return repo
        return self._query.get_repository_by_root(root)

    def _compute_summary(
        self,
        *,
        repo: dict[str, Any],
        repo_root: str,
        branch: str,
    ) -> RecommendationRepositorySummary:
        rid = str(repo["id"])
        try:
            aggregates = self._query.aggregate_recommendations(rid)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning(
                "RecommendationStatsService aggregate failed for {}: {}", rid, exc
            )
            aggregates = {
                "by_priority": {},
                "by_status": {},
                "by_type": {},
                "total": 0,
                "last_updated": None,
            }

        by_priority = {
            str(k).lower(): int(v)
            for k, v in (aggregates.get("by_priority") or {}).items()
        }
        by_status = {
            str(k).lower(): int(v)
            for k, v in (aggregates.get("by_status") or {}).items()
        }
        by_type = {
            str(k): int(v) for k, v in (aggregates.get("by_type") or {}).items()
        }

        pending = sum(by_status.get(s, 0) for s in PENDING_STATUSES)
        applied = sum(by_status.get(s, 0) for s in APPLIED_STATUSES)
        resolved = sum(by_status.get(s, 0) for s in RESOLVED_STATUSES)
        ignored = sum(by_status.get(s, 0) for s in IGNORED_STATUSES)
        # Anything outside known buckets still counts toward total but not status tiles.
        known_status = pending + applied + resolved + ignored
        total = int(aggregates.get("total") or 0)
        if total == 0:
            total = sum(by_status.values())

        last_updated = aggregates.get("last_updated")
        if isinstance(last_updated, str):
            try:
                last_updated = datetime.fromisoformat(
                    last_updated.replace("Z", "+00:00")
                )
            except ValueError:
                last_updated = datetime.now(timezone.utc)
        if last_updated is None:
            last_updated = datetime.now(timezone.utc)

        # by_priority from repository is pending-only (open severity).
        summary = RecommendationRepositorySummary(
            total=total,
            pending=pending,
            applied=applied,
            resolved=resolved,
            ignored=ignored,
            critical=by_priority.get("critical", 0),
            high=by_priority.get("high", 0),
            medium=by_priority.get("medium", 0),
            low=by_priority.get("low", 0),
            by_type=by_type,
            by_status=by_status,
            by_priority=by_priority,
            last_updated=last_updated,
            repository_id=rid,
            repository=str(repo.get("name") or ""),
            repo_root=repo_root,
            branch=branch,
            source="RecommendationStatsService",
            version=SUMMARY_VERSION,
        )
        # Sanity: status buckets should not exceed total (unknown statuses allowed).
        if known_status > total > 0:
            self._logger.warning(
                "Recommendation summary status buckets ({}) exceed total ({}) for {}",
                known_status,
                total,
                rid,
            )
        return summary
