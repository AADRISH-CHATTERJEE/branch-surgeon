"""Configurable ignore rules via .refactoryignore files.

Supports glob patterns similar to .gitignore:
- Directory patterns: build/, dist/
- File patterns: *.pyc, *.pyo
- Negation: !important.py
- Comments: lines starting with #
"""

from __future__ import annotations

import fnmatch
from pathlib import Path


_DEFAULT_PATTERNS: tuple[str, ...] = (
    "build/",
    "dist/",
    "generated/",
    "vendor/",
    "node_modules/",
    "migrations/",
    "coverage/",
    ".git/",
    "__pycache__/",
    ".refactory/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".venv/",
    "venv/",
    "*.pyc",
    "*.pyo",
)

IGNORE_FILENAME = ".refactoryignore"


class IgnoreRules:
    """Parse and apply .refactoryignore rules."""

    def __init__(
        self,
        patterns: list[str] | None = None,
        root: Path | None = None,
    ) -> None:
        self._include: list[str] = []
        self._exclude: list[str] = []

        raw = list(patterns or [])
        if root is not None:
            raw = self._load_file(root) + raw

        for line in raw:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("!"):
                self._include.append(line[1:].strip())
            else:
                self._exclude.append(line)

        if not self._exclude:
            self._exclude = list(_DEFAULT_PATTERNS)

    def is_ignored(self, relative_path: str) -> bool:
        """Check if a relative path should be ignored."""
        norm = relative_path.replace("\\", "/")
        parts = norm.split("/")

        for pattern in self._include:
            if self._matches(norm, parts, pattern):
                return False

        for pattern in self._exclude:
            if self._matches(norm, parts, pattern):
                return True

        return False

    def ignored_dirs(self) -> list[str]:
        """Return directory names from exclude patterns (for legacy compat)."""
        dirs: list[str] = []
        for p in self._exclude:
            if p.endswith("/"):
                dirs.append(p.rstrip("/"))
        return dirs

    @staticmethod
    def _matches(path: str, parts: list[str], pattern: str) -> bool:
        if pattern.endswith("/"):
            dir_name = pattern.rstrip("/").lower()
            return any(p.lower() == dir_name for p in parts)
        if "/" in pattern:
            return fnmatch.fnmatch(path.lower(), pattern.lower())
        return any(fnmatch.fnmatch(p.lower(), pattern.lower()) for p in parts)

    @staticmethod
    def _load_file(root: Path) -> list[str]:
        ignore_path = root / IGNORE_FILENAME
        if not ignore_path.is_file():
            return []
        try:
            return ignore_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []


def load_ignore_rules(root: Path | None = None) -> IgnoreRules:
    """Load ignore rules from .refactoryignore at the given root."""
    return IgnoreRules(root=root)
