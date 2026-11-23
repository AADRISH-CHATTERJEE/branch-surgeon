"""Registry of language adapters keyed by file extension."""

from __future__ import annotations

from pathlib import Path

from refactory.parser.adapters.base import LanguageAdapter


class LanguageAdapterRegistry:
    def __init__(self) -> None:
        self._by_ext: dict[str, LanguageAdapter] = {}
        self._by_language: dict[str, LanguageAdapter] = {}

    def register(self, adapter: LanguageAdapter) -> None:
        self._by_language[adapter.language] = adapter
        for ext in adapter.extensions:
            self._by_ext[ext.lower()] = adapter

    def get_for_path(self, path: Path) -> LanguageAdapter | None:
        return self._by_ext.get(path.suffix.lower())

    def get_for_language(self, language: str) -> LanguageAdapter | None:
        return self._by_language.get(language)

    def supported_extensions(self) -> set[str]:
        return set(self._by_ext)

    def supported_languages(self) -> set[str]:
        return set(self._by_language)
