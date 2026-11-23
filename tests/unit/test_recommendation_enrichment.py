"""Unit tests for recommendation enrichment helpers."""

from __future__ import annotations

from types import SimpleNamespace

from refactory.recommendation.enrichment import (
    impact_tags_for,
    normalize_effort,
    payload_from_engine_rec,
    reasoning_from_rec,
)


def test_normalize_effort_buckets():
    assert normalize_effort("10 min") == "XS"
    assert normalize_effort("30 min") == "S"
    assert normalize_effort("60 min") == "M"
    assert normalize_effort("2h") == "L"
    assert normalize_effort("xl") == "XL"


def test_impact_tags_from_category():
    tags = impact_tags_for(category="security", business_impact="Security vulnerability")
    assert "Security" in tags


def test_payload_from_engine_rec():
    rec = SimpleNamespace(
        id="R-1",
        title="Fix eval",
        description="Remove eval",
        category=SimpleNamespace(value="security"),
        priority=SimpleNamespace(value="critical"),
        confidence=0.95,
        estimated_effort="15 min",
        affected_files=["auth.py"],
        business_impact="Security",
        technical_impact="",
        explanation=SimpleNamespace(why="eval allows arbitrary code execution"),
    )
    payload = payload_from_engine_rec(rec)
    assert payload["reasoning"].startswith("eval")
    assert payload["affected_files"] == ["auth.py"]
    assert payload["effort"] == "XS"
    assert payload["confidence"] == 0.95
    assert "Security" in payload["impact"]


def test_reasoning_falls_back_to_description():
    rec = SimpleNamespace(description="plain desc", explanation=None)
    assert reasoning_from_rec(rec) == "plain desc"
