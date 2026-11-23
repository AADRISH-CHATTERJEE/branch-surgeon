"""Language adapter protocol for Tree-sitter based parsers.

Add a new language by implementing LanguageAdapter and registering it —
ParserService itself does not change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from refactory.parser.models import ParsedFile


class LanguageAdapter(ABC):
    """Adapter that turns source text into a ParsedFile for one language."""

    @property
    @abstractmethod
    def language(self) -> str:
        """Canonical language id, e.g. 'python'."""

    @property
    @abstractmethod
    def extensions(self) -> frozenset[str]:
        """File extensions handled by this adapter, including the dot."""

    @abstractmethod
    def parse(self, path: Path, content: str, *, relative_path: str) -> ParsedFile:
        """Parse source content into typed models (never return Tree-sitter nodes)."""
