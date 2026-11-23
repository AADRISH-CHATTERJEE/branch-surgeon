"""UI contract — Recommendation page has no Requires Backend Support."""

from __future__ import annotations

from pathlib import Path

UI = Path(__file__).resolve().parents[2] / "ui"


def test_no_requires_backend_support_on_recommendations_page():
    view = (
        UI / "features" / "recommendations" / "recommendations-view.tsx"
    ).read_text(encoding="utf-8")
    assert "Requires Backend Support" not in view
    assert "Unavailable" not in view
    assert "Mark Resolved" in view
    assert "Ignore" in view
    assert "data-testid=\"resolve-recommendation\"" in view
    assert "data-testid=\"ignore-recommendation\"" in view
    assert "selected.reasoning" in view
    assert "selected.affected_files" in view
    assert "selected.impact" in view
    assert "selected.effort" in view
    assert "selected.confidence" in view
    assert "Patch History" in view
    assert "LifecycleLegend" in view


def test_endpoints_expose_patch_recommendation():
    text = (UI / "services" / "endpoints.ts").read_text(encoding="utf-8")
    assert "recommendationItem" in text
