"""Post-transformation refresh pipeline.

After a successful repository mutation (transform apply/rollback, patch apply/rollback),
re-index the repo, regenerate recommendations with reconciliation, refresh Branch Surgeon
inputs, and emit Activity events so every surface shows identical live totals.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.db.persistence import PersistenceService
    from refactory.db.query_service import RepositoryQueryService
    from refactory.graph.service import RepositoryGraphService
    from refactory.indexer.service import IndexerService
    from refactory.recommendation.service import RecommendationEngine
    from refactory.recommendation.stats import (
        RecommendationRepositorySummary,
        RecommendationStatsService,
    )
    from refactory.review.suggestion_status import ReviewSuggestionStatusService
    from refactory.surgeon.service import BranchSurgeonService


@dataclass
class PostTransformationResult:
    """Outcome of a full post-mutation refresh."""

    trigger: str
    indexed: bool = False
    graph_updated: bool = False
    recommendations_active: int = 0
    reconcile: dict[str, int] = field(default_factory=dict)
    suggestions_auto_resolved: int = 0
    summary: dict[str, Any] | None = None
    branch_surgeon_refreshed: bool = False
    duration_ms: float = 0.0
    errors: list[str] = field(default_factory=list)


class PostTransformationPipeline:
    """Repository changed → index → recommendations → summary → Branch Surgeon → activity."""

    def __init__(
        self,
        logger: "Logger",
        *,
        indexer_service: "IndexerService | None" = None,
        graph_service: "RepositoryGraphService | None" = None,
        recommendation_engine: "RecommendationEngine | None" = None,
        recommendation_stats_service: "RecommendationStatsService | None" = None,
        branch_surgeon_service: "BranchSurgeonService | None" = None,
        query_service: "RepositoryQueryService | None" = None,
        persistence_service: "PersistenceService | None" = None,
        suggestion_status_service: "ReviewSuggestionStatusService | None" = None,
        activity_writer: Any | None = None,
    ) -> None:
        self._logger = logger
        self._indexer = indexer_service
        self._graph = graph_service
        self._engine = recommendation_engine
        self._stats = recommendation_stats_service
        self._surgeon = branch_surgeon_service
        self._query = query_service
        self._persistence = persistence_service
        self._suggestion_status = suggestion_status_service
        self._activity_writer = activity_writer

    def run(
        self,
        root: Path,
        *,
        trigger: str,
        transformation_id: str | None = None,
        patch_id: str | None = None,
        recommendation_top: int = 2000,
        skip_activity_applied: bool = False,
    ) -> PostTransformationResult:
        """Execute the full refresh pipeline for ``root``."""
        started = time.perf_counter()
        root = Path(root).resolve()
        result = PostTransformationResult(trigger=trigger)

        if not skip_activity_applied:
            label = {
                "transform-apply": "Transformation Applied",
                "transform-rollback": "Transformation Rolled Back",
                "patch-apply": "Transformation Applied",
                "patch-rollback": "Transformation Rolled Back",
            }.get(trigger, "Repository Changed")
            self._emit_activity(
                command=trigger.split("-")[0] if "-" in trigger else trigger,
                result_type="post_transformation",
                summary=label,
                result_data={
                    "stage": "repository_changed",
                    "trigger": trigger,
                    "transformation_id": transformation_id,
                    "patch_id": patch_id,
                },
            )

        # 1) Re-index + dependency graph / blast-radius inputs
        result.indexed, result.graph_updated = self._reindex(root)
        self._emit_activity(
            command="index",
            result_type="repository_index",
            summary="Repository Indexed",
            result_data={
                "stage": "repository_indexed",
                "trigger": trigger,
                "indexed": result.indexed,
                "graph_updated": result.graph_updated,
            },
        )

        # 2–4) Generate + reconcile recommendations, then refresh summary
        if self._engine is not None:
            try:
                report = self._engine.generate_recommendations(
                    root,
                    top=recommendation_top,
                    reconcile=True,
                )
                result.recommendations_active = int(report.total_recommendations)
                result.reconcile = dict(
                    getattr(report, "reconcile_stats", None) or {}
                )
            except Exception as exc:  # noqa: BLE001
                msg = f"Recommendation regeneration failed: {exc}"
                self._logger.warning(msg)
                result.errors.append(msg)

        self._emit_activity(
            command="recommend",
            result_type="recommendations",
            summary="Recommendations Generated",
            result_data={
                "stage": "recommendations_generated",
                "trigger": trigger,
                "active": result.recommendations_active,
                "reconcile": result.reconcile,
            },
        )

        # Auto-resolve review suggestions whose findings no longer exist as open recs.
        if self._suggestion_status is not None and self._query is not None:
            try:
                repo = self._query.get_repository_by_root(str(root))
                if repo:
                    auto = self._suggestion_status.auto_resolve_for_repository(
                        str(repo["id"])
                    )
                    result.suggestions_auto_resolved = int(auto.get("resolved") or 0)
                    if result.suggestions_auto_resolved:
                        self._emit_activity(
                            command="review",
                            result_type="review_suggestion",
                            summary="Resolved review suggestion",
                            result_data={
                                "stage": "review_suggestions_auto_resolved",
                                "trigger": trigger,
                                "resolved_count": result.suggestions_auto_resolved,
                                "checked": auto.get("checked"),
                            },
                        )
            except Exception as exc:  # noqa: BLE001
                msg = f"Review suggestion auto-resolve failed: {exc}"
                self._logger.warning(msg)
                result.errors.append(msg)

        summary_obj: RecommendationRepositorySummary | None = None
        if self._stats is not None:
            try:
                self._stats.invalidate(repo_root=root)
                summary_obj = self._stats.get_repository_summary(
                    repo_root=root, force_refresh=True
                )
                result.summary = summary_obj.model_dump(mode="json")
            except Exception as exc:  # noqa: BLE001
                msg = f"Recommendation summary refresh failed: {exc}"
                self._logger.warning(msg)
                result.errors.append(msg)

        # 5) Branch Surgeon — warm compose so surgery score / blast radius use new data
        if self._surgeon is not None:
            try:
                self._surgeon.compose_workspace()
                result.branch_surgeon_refreshed = True
            except Exception as exc:  # noqa: BLE001
                msg = f"Branch Surgeon refresh failed: {exc}"
                self._logger.warning(msg)
                result.errors.append(msg)

        self._emit_activity(
            command="branch-surgeon",
            result_type="branch_surgeon",
            summary="Branch Surgeon Updated",
            result_data={
                "stage": "branch_surgeon_updated",
                "trigger": trigger,
                "refreshed": result.branch_surgeon_refreshed,
                "critical": (result.summary or {}).get("critical"),
                "pending": (result.summary or {}).get("pending"),
                "resolved": (result.summary or {}).get("resolved"),
            },
        )

        result.duration_ms = (time.perf_counter() - started) * 1000
        self._logger.info(
            "PostTransformationPipeline ({}) finished in {:.0f}ms "
            "(indexed={}, graph={}, active={}, surgeon={})",
            trigger,
            result.duration_ms,
            result.indexed,
            result.graph_updated,
            result.recommendations_active,
            result.branch_surgeon_refreshed,
        )
        return result

    def _reindex(self, root: Path) -> tuple[bool, bool]:
        indexed = False
        graph_updated = False
        repo_name = root.name
        if self._query is not None:
            try:
                repo = self._query.get_repository_by_root(str(root))
                if repo and repo.get("name"):
                    repo_name = str(repo["name"])
            except Exception:  # noqa: BLE001
                pass

        if self._indexer is None:
            return indexed, graph_updated
        try:
            index = self._indexer.build_index(
                root,
                repository_name=repo_name,
                force=True,
            )
            indexed = True
            if self._graph is not None:
                try:
                    self._graph.build_graph(index, force=True)
                    graph_updated = True
                except Exception as exc:  # noqa: BLE001
                    self._logger.warning(
                        "Graph refresh in post-transformation pipeline failed: {}",
                        exc,
                    )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning(
                "Index refresh in post-transformation pipeline failed: {}",
                exc,
            )
        return indexed, graph_updated

    def _emit_activity(
        self,
        *,
        command: str,
        result_type: str,
        summary: str,
        result_data: dict[str, Any] | None = None,
    ) -> None:
        writer = self._activity_writer
        if writer is None:
            return
        try:
            writer(
                command=command,
                result_type=result_type,
                summary=summary,
                result_data=result_data or {},
                status="completed",
            )
        except Exception:  # noqa: BLE001
            self._logger.debug("Post-transformation activity write skipped")
