"""Best-effort repair of common invalid JSON from LLM outputs."""

from __future__ import annotations

import json
import re
from typing import Any


def try_parse_json(text: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Parse JSON object; attempt repairs on failure. Never raises."""
    warnings: list[str] = []
    candidate = (text or "").strip()
    if not candidate:
        return None, ["Empty JSON candidate"]

    # Strip markdown fences if present
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", candidate, re.DOTALL | re.I)
    if fenced:
        candidate = fenced.group(1).strip()
        warnings.append("Stripped markdown fence from JSON")

    direct = _loads_object(candidate)
    if direct is not None:
        return direct, warnings

    repaired, repair_notes = repair_json_text(candidate)
    warnings.extend(repair_notes)
    parsed = _loads_object(repaired)
    if parsed is not None:
        warnings.append("JSON repaired before parse")
        return parsed, warnings

    warnings.append("JSON repair failed")
    return None, warnings


def repair_json_text(text: str) -> tuple[str, list[str]]:
    """Apply deterministic repairs for common LLM JSON mistakes."""
    notes: list[str] = []
    out = text.strip().lstrip("\ufeff")

    # Extract outermost object if surrounded by prose
    start = out.find("{")
    end = out.rfind("}")
    if start >= 0 and end > start and (start > 0 or end < len(out) - 1):
        out = out[start : end + 1]
        notes.append("Extracted JSON object from surrounding text")

    # Single-quoted keys/strings → double quotes (heuristic)
    if "'" in out and '"' not in out:
        out = out.replace("'", '"')
        notes.append("Normalized single quotes to double quotes")

    # Close truncated braces/brackets before trailing-comma cleanup so a
    # dangling comma at EOF (common LLM truncation) can be removed.
    opens_arr = out.count("[") - out.count("]")
    if opens_arr > 0:
        out = out + ("]" * opens_arr)
        notes.append(f"Closed {opens_arr} truncated bracket(s)")
    opens = out.count("{") - out.count("}")
    if opens > 0:
        out = out + ("}" * opens)
        notes.append(f"Closed {opens} truncated brace(s)")

    # Trailing commas before } or ]
    cleaned = re.sub(r",(\s*[}\]])", r"\1", out)
    if cleaned != out:
        notes.append("Removed trailing commas")
        out = cleaned

    # Remove control characters except whitespace
    sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", out)
    if sanitized != out:
        notes.append("Removed control characters")
        out = sanitized

    return out, notes


def _loads_object(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None
