"""Helpers to persist rich recommendation fields from engine models."""

from __future__ import annotations

import re
from typing import Any

_IMPACT_TAGS = (
    "Security",
    "Architecture",
    "Testing",
    "Performance",
    "API",
    "Database",
    "Maintainability",
)

_CATEGORY_IMPACT: dict[str, list[str]] = {
    "security": ["Security"],
    "architecture": ["Architecture"],
    "testing": ["Testing"],
    "performance": ["Performance"],
    "api": ["API"],
    "database": ["Database"],
    "maintainability": ["Maintainability"],
    "refactoring": ["Maintainability"],
    "documentation": ["Maintainability"],
    "company_rules": ["Security", "Architecture"],
}


def normalize_effort(raw: str | None) -> str:
    """Map free-text effort estimates to XS|S|M|L|XL."""
    text = (raw or "").strip().lower()
    if not text:
        return "M"
    if text in {"xs", "s", "m", "l", "xl"}:
        return text.upper()
    minutes = None
    m = re.search(r"(\d+)\s*min", text)
    if m:
        minutes = int(m.group(1))
    h = re.search(r"(\d+)\s*h", text)
    if h:
        minutes = int(h.group(1)) * 60
    if minutes is not None:
        if minutes <= 15:
            return "XS"
        if minutes <= 30:
            return "S"
        if minutes <= 60:
            return "M"
        if minutes <= 180:
            return "L"
        return "XL"
    if any(w in text for w in ("trivial", "tiny", "quick")):
        return "XS"
    if any(w in text for w in ("small", "easy")):
        return "S"
    if any(w in text for w in ("large", "hard", "complex")):
        return "L"
    if any(w in text for w in ("huge", "epic", "major")):
        return "XL"
    return "M"


def impact_tags_for(
    *,
    category: str | None,
    business_impact: str | None = None,
    technical_impact: str | None = None,
    explicit: list[str] | None = None,
) -> list[str]:
    tags: list[str] = []
    if explicit:
        tags.extend(str(t).strip() for t in explicit if str(t).strip())
    cat = (category or "").strip().lower()
    tags.extend(_CATEGORY_IMPACT.get(cat, []))
    blob = f"{business_impact or ''} {technical_impact or ''}".lower()
    for tag in _IMPACT_TAGS:
        if tag.lower() in blob and tag not in tags:
            tags.append(tag)
    if not tags:
        tags.append("Maintainability")
    # Preserve order, unique
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        key = t if t in _IMPACT_TAGS else t.title()
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def reasoning_from_rec(rec: Any) -> str:
    explanation = getattr(rec, "explanation", None)
    if explanation is not None:
        why = getattr(explanation, "why", None) or ""
        if str(why).strip():
            return str(why).strip()
        if isinstance(explanation, dict) and explanation.get("why"):
            return str(explanation["why"]).strip()
    desc = getattr(rec, "description", None) or ""
    return str(desc).strip()


def payload_from_engine_rec(rec: Any) -> dict[str, Any]:
    """Build a persistence dict for one engine Recommendation."""
    category = getattr(getattr(rec, "category", None), "value", None) or getattr(
        rec, "type", None
    ) or "refactoring"
    priority = getattr(getattr(rec, "priority", None), "value", None) or getattr(
        rec, "priority", None
    ) or "medium"
    affected = list(getattr(rec, "affected_files", None) or [])
    return {
        "id": getattr(rec, "id", None) or "",
        "type": str(category),
        "priority": str(priority),
        "title": str(getattr(rec, "title", "") or ""),
        "description": str(getattr(rec, "description", "") or ""),
        "status": "pending",
        "reasoning": reasoning_from_rec(rec),
        "affected_files": affected,
        "impact": impact_tags_for(
            category=str(category),
            business_impact=str(getattr(rec, "business_impact", "") or ""),
            technical_impact=str(getattr(rec, "technical_impact", "") or ""),
        ),
        "effort": normalize_effort(str(getattr(rec, "estimated_effort", "") or "")),
        "confidence": float(getattr(rec, "confidence", 0.0) or 0.0),
        "verification_status": "unverified",
    }
