"""ParserService — structured source parsing via language adapters.

Produces canonical ParsedFile models for Indexer / Retrieval / Review / AI later.
Independent of AI providers and GitHub.
"""

from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING

from refactory.core.exceptions import ParserError
from refactory.parser.adapters.ecmascript_adapter import (
    javascript_adapter,
    typescript_adapter,
)
from refactory.parser.adapters.json_adapter import JsonLanguageAdapter
from refactory.parser.adapters.python_adapter import PythonLanguageAdapter
from refactory.parser.adapters.registry import LanguageAdapterRegistry
from refactory.parser.models import ParsedFile
from refactory.review.models import Repository, RepositorySummary

if TYPE_CHECKING:
    from loguru import Logger


def _default_registry() -> LanguageAdapterRegistry:
    registry = LanguageAdapterRegistry()
    registry.register(PythonLanguageAdapter())
    registry.register(javascript_adapter())
    registry.register(typescript_adapter())
    registry.register(JsonLanguageAdapter())
    return registry


class ParserService:
    def __init__(
        self,
        ignore_dirs: list[str],
        logger: "Logger",
        registry: LanguageAdapterRegistry | None = None,
        *,
        max_workers: int = 4,
    ) -> None:
        self._ignore_dirs = ignore_dirs
        self._logger = logger
        self._registry = registry or _default_registry()
        if not self._registry.supported_languages():
            self._registry.register(PythonLanguageAdapter())
        self._max_workers = max(1, max_workers)
        self._cache: dict[str, ParsedFile] = {}
        self._cache_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Port method (ReviewEngine contract)
    # ------------------------------------------------------------------

    def parse_repository(self, repository: Repository) -> RepositorySummary:
        """Parse supported source files under the repository root."""
        root = Path(repository.root_path)
        parsed_files = self.parse_directory(root)
        languages = sorted({item.metadata.language for item in parsed_files})
        self._logger.bind(repository=repository.name).info(
            "Parsed repository — {} file(s), languages={}",
            len(parsed_files),
            languages,
        )
        return RepositorySummary(
            repository=repository,
            file_count=len(parsed_files),
            languages=languages,
            summary=f"Parsed {len(parsed_files)} file(s)",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_file(self, path: Path | str, *, repo_root: Path | str | None = None) -> ParsedFile:
        """Parse a single source file into a strongly typed ParsedFile."""
        file_path = Path(path).resolve()
        if not file_path.is_file():
            raise ParserError(f"File not found: {file_path}")

        adapter = self._registry.get_for_path(file_path)
        if adapter is None:
            raise ParserError(
                f"Unsupported file type '{file_path.suffix}' for {file_path.name}. "
                f"Supported extensions: {sorted(self._registry.supported_extensions())}"
            )

        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            self._logger.warning("Decoded {} with replacement characters", file_path)
        except OSError as exc:
            raise ParserError(f"Unable to read {file_path}: {exc}") from exc

        content_hash = hashlib.sha256(content.encode()).hexdigest()
        cache_key = f"{file_path}:{content_hash}"
        with self._cache_lock:
            cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        root = Path(repo_root).resolve() if repo_root else file_path.parent
        try:
            relative = str(file_path.relative_to(root)).replace("\\", "/")
        except ValueError:
            relative = file_path.name

        self._logger.info("Parsing {} ({})", relative, adapter.language)
        try:
            parsed = adapter.parse(file_path, content, relative_path=relative)
        except Exception as exc:  # noqa: BLE001 — never leak Tree-sitter errors
            raise ParserError(f"Failed to parse {relative}: {exc}") from exc

        if parsed.has_syntax_errors:
            self._logger.warning("Syntax issues detected in {}", relative)
        else:
            self._logger.debug(
                "Parsed {} — classes={}, functions={}, imports={}",
                relative,
                len(parsed.module.classes),
                len(parsed.module.functions),
                len(parsed.module.imports),
            )

        with self._cache_lock:
            self._cache[cache_key] = parsed
        return parsed

    def parse_directory(
        self, root: Path | str, *, max_workers: int | None = None,
    ) -> list[ParsedFile]:
        """Parse all supported source files under root using thread pool."""
        root_path = Path(root).resolve()
        if not root_path.is_dir():
            raise ParserError(f"Directory not found: {root_path}")

        file_paths = sorted(self._iter_source_files(root_path))
        if not file_paths:
            return []

        workers = max_workers or self._max_workers
        results: list[tuple[int, ParsedFile]] = []
        errors: list[tuple[int, str]] = []

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self.parse_file, fp, repo_root=root_path): idx
                for idx, fp in enumerate(file_paths)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results.append((idx, future.result()))
                except ParserError as exc:
                    self._logger.warning("Skipping {}: {}", file_paths[idx], exc.message)
                    errors.append((idx, str(file_paths[idx])))

        results.sort(key=lambda pair: pair[0])
        return [pf for _, pf in results]

    def clear_cache(self) -> None:
        """Clear the in-memory parse cache."""
        with self._cache_lock:
            self._cache.clear()

    def parse_incremental(
        self,
        root: Path | str,
        *,
        previous_hashes: dict[str, str] | None = None,
    ) -> "IncrementalParseResult":
        """Parse only files whose content hash has changed since previous_hashes.

        Returns an IncrementalParseResult with parsed files, skipped count,
        and updated file hashes for future incremental calls.
        """
        root_path = Path(root).resolve()
        if not root_path.is_dir():
            raise ParserError(f"Directory not found: {root_path}")

        prev = previous_hashes or {}
        file_paths = sorted(self._iter_source_files(root_path))
        parsed: list[ParsedFile] = []
        skipped = 0
        new_hashes: dict[str, str] = {}
        errors = 0

        for fp in file_paths:
            try:
                content = fp.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                errors += 1
                continue

            relative = str(fp.relative_to(root_path)).replace("\\", "/")
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            new_hashes[relative] = content_hash

            if prev.get(relative) == content_hash:
                skipped += 1
                continue

            try:
                pf = self.parse_file(fp, repo_root=root_path)
                parsed.append(pf)
            except ParserError:
                errors += 1

        self._logger.info(
            "Incremental parse — parsed={}, skipped={}, errors={}",
            len(parsed), skipped, errors,
        )
        return IncrementalParseResult(
            parsed_files=parsed,
            skipped_count=skipped,
            error_count=errors,
            file_hashes=new_hashes,
            total_files=len(file_paths),
        )

    def supported_languages(self) -> list[str]:
        return sorted(self._registry.supported_languages())

    def supported_extensions(self) -> set[str]:
        """File extensions handled by registered language adapters."""
        return self._registry.supported_extensions()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _iter_source_files(self, root: Path):
        ignore = {d.strip().lower() for d in self._ignore_dirs if d and d.strip()}
        supported = self._registry.supported_extensions()
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in supported:
                continue
            if self._is_ignored(path, root, ignore):
                continue
            yield path

    @staticmethod
    def _is_ignored(path: Path, root: Path, ignore: set[str]) -> bool:
        try:
            relative = path.resolve().relative_to(root.resolve())
        except ValueError:
            return True
        return any(part.lower() in ignore for part in relative.parts)


from dataclasses import dataclass as _dataclass


@_dataclass
class IncrementalParseResult:
    """Result of an incremental parse operation."""

    parsed_files: list[ParsedFile]
    skipped_count: int
    error_count: int
    file_hashes: dict[str, str]
    total_files: int

    @property
    def parsed_count(self) -> int:
        return len(self.parsed_files)
