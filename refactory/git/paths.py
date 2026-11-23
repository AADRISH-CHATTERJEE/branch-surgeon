"""Safe repository-relative path resolution (shared by Git / transform / patch)."""

from __future__ import annotations

from pathlib import Path


def safe_repo_relative_path(root: Path, relative: str | None) -> Path | None:
    """Resolve ``relative`` under ``root`` or return None on traversal / escape.

    Rejects empty paths, absolute paths outside the root, and ``..`` escapes.
    """
    if relative is None:
        return None
    cleaned = str(relative).replace("\\", "/").strip()
    if not cleaned or cleaned in {".", "./"}:
        return None
    # Absolute paths are only allowed when they already resolve under root.
    candidate_raw = Path(cleaned)
    root_resolved = root.resolve()
    if candidate_raw.is_absolute():
        try:
            candidate_raw.resolve().relative_to(root_resolved)
        except ValueError:
            return None
        candidate = candidate_raw.resolve()
    else:
        cleaned = cleaned.lstrip("/")
        if any(part == ".." for part in cleaned.split("/")):
            return None
        candidate = (root_resolved / cleaned).resolve()
        try:
            candidate.relative_to(root_resolved)
        except ValueError:
            return None
    return candidate
