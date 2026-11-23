"""Shared helper to run PostTransformationPipeline from Local API routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from refactory.core.container import ServiceContainer
from refactory.recommendation.post_transformation import PostTransformationResult


def run_post_transformation_pipeline(
    container: ServiceContainer,
    root: Path,
    *,
    trigger: str,
    transformation_id: str | None = None,
    patch_id: str | None = None,
    skip_activity_applied: bool = True,
) -> PostTransformationResult | None:
    """Best-effort full refresh after a successful repository mutation."""
    pipeline = getattr(container, "post_transformation_pipeline", None)
    if pipeline is None:
        return None
    try:
        return pipeline.run(
            Path(root).resolve(),
            trigger=trigger,
            transformation_id=transformation_id,
            patch_id=patch_id,
            skip_activity_applied=skip_activity_applied,
        )
    except Exception:  # noqa: BLE001
        return None


def pipeline_meta(result: PostTransformationResult | None) -> dict[str, Any]:
    if result is None:
        return {}
    return {
        "post_transformation": {
            "trigger": result.trigger,
            "indexed": result.indexed,
            "graph_updated": result.graph_updated,
            "recommendations_active": result.recommendations_active,
            "reconcile": result.reconcile,
            "summary": result.summary,
            "branch_surgeon_refreshed": result.branch_surgeon_refreshed,
            "duration_ms": result.duration_ms,
            "errors": result.errors,
        }
    }
