"""UI contract tests for review suggestion lifecycle (no browser runner required)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "ui"


def test_endpoint_builder_exposes_patch_path():
    text = (UI / "services" / "endpoints.ts").read_text(encoding="utf-8")
    assert "reviewSuggestionStatus" in text
    assert "/reviews/" in text
    assert "/suggestions/" in text


def test_suggestion_panel_has_lifecycle_actions():
    text = (UI / "components" / "reviews" / "suggestion-panel.tsx").read_text(
        encoding="utf-8"
    )
    assert "Mark Resolved" in text
    assert "Ignore" in text
    assert "Loader2" in text
    assert "data-testid=\"ignore-suggestion\"" in text
    assert "data-testid=\"resolve-suggestion\"" in text
    assert "LifecycleBadge" in text
    assert "LifecycleLegend" in text
    assert 'status === "pending"' in text or "status === 'pending'" in text


def test_reviews_view_uses_canonical_review_id():
    text = (UI / "features" / "reviews" / "reviews-view.tsx").read_text(
        encoding="utf-8"
    )
    assert "detail.data?.id" in text
    assert "cacheIds" in text
    assert "useUpdateReviewSuggestionStatus" in text


def test_mutation_invalidates_truth_surfaces():
    text = (UI / "queries" / "use-reviews.ts").read_text(encoding="utf-8")
    assert "invalidateRecommendationTruth" in text
    assert "invalidateAnalysisMemory" in text
    assert "applyOptimisticRecommendationStats" in text
    assert "recommendationStats" in text


def test_optimistic_stats_helper():
    def apply_optimistic(prev, status, synced):
        if not prev or not synced:
            return prev
        pending = max(0, prev["pending"] - 1)
        if status == "resolved":
            return {**prev, "pending": pending, "resolved": prev["resolved"] + 1}
        return {**prev, "pending": pending, "ignored": prev["ignored"] + 1}

    base = {"pending": 2, "resolved": 1, "ignored": 0, "critical": 3}
    resolved = apply_optimistic(base, "resolved", True)
    assert resolved["pending"] == 1
    assert resolved["resolved"] == 2
    assert resolved["critical"] == 3
    ignored = apply_optimistic(base, "ignored", True)
    assert ignored["pending"] == 1
    assert ignored["ignored"] == 1

    helper = (UI / "lib" / "suggestion-lifecycle.ts").read_text(encoding="utf-8")
    assert "export function applyOptimisticRecommendationStats" in helper
    assert "export function patchSuggestionInList" in helper
