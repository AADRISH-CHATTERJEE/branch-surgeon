"""IndexerService — deterministic repository indexing via injected ParserService.

Coordinates traversal + parsing only. No embeddings, vector stores, or LLMs.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from refactory.core.exceptions import IndexError_, ParserError
from refactory.core.ignore import IgnoreRules, load_ignore_rules
from refactory.indexer.models import (
    ImportReference,
    IndexedFile,
    IndexedSymbol,
    RepositoryIndex,
    RepositoryStatistics,
    RepositorySummary,
    SymbolKind,
)
from refactory.parser.models import CommentTag, ParsedFile, ParsedFunction
from refactory.parser.service import ParserService
from refactory.review.models import Repository

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.db.persistence import PersistenceService

INDEX_FILENAME = "repository_index.json"


class IndexerService:
    def __init__(
        self,
        parser_service: ParserService,
        ignore_dirs: list[str],
        logger: "Logger",
        *,
        persistence_service: "PersistenceService | None" = None,
    ) -> None:
        self._parser = parser_service
        self._ignore_dirs = ignore_dirs
        self._logger = logger
        self._last_index: RepositoryIndex | None = None
        self._persistence = persistence_service

    # ------------------------------------------------------------------
    # Port methods (ReviewEngine contract)
    # ------------------------------------------------------------------

    def index_repository(self, repository: Repository, *, force: bool = False) -> int:
        """Build/rebuild index. Returns indexed file count (port contract)."""
        index = self.build_index(
            repository.root_path,
            repository_name=repository.name,
            force=force,
        )
        return index.summary.total_indexed_files

    def ensure_index(self, repository: Repository) -> int:
        """Reuse persisted index when present; otherwise build one."""
        existing = self.load_index(Path(repository.root_path))
        if existing is not None:
            self._last_index = existing
            self._logger.bind(repository=repository.name).info(
                "Reusing persisted index ({} files)",
                existing.summary.total_indexed_files,
            )
            return existing.summary.total_indexed_files
        return self.index_repository(repository, force=False)

    def clear_index(self, repository: Repository) -> None:
        """Delete the persisted index for a repository."""
        path = self._index_path(Path(repository.root_path))
        if path.exists():
            path.unlink()
            self._logger.info("Cleared index at {}", path)
        self._last_index = None

    def has_index(self, repository: Repository) -> bool:
        return self._index_path(Path(repository.root_path)).is_file()

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def build_index(
        self,
        root: Path | str,
        *,
        repository_name: str | None = None,
        force: bool = False,
    ) -> RepositoryIndex:
        """Walk ``root``, parse supported files, persist a RepositoryIndex."""
        root_path = Path(root).resolve()
        if not root_path.is_dir():
            raise IndexError_(f"Repository root not found: {root_path}")

        started = time.perf_counter()
        name = repository_name or root_path.name
        previous = None if force else self.load_index(root_path)
        previous_by_path = (
            {item.relative_path: item for item in previous.files} if previous else {}
        )

        ignore = {d.strip().lower() for d in self._ignore_dirs if d and d.strip()}
        ignore_rules = load_ignore_rules(root_path)
        supported = {ext.lower() for ext in self._parser.supported_extensions()}

        indexed_files: list[IndexedFile] = []
        ignored_count = 0
        unsupported_count = 0
        parse_failures = 0
        reused = 0
        newly_added = 0
        modified = 0
        files_parsed = 0
        seen_paths: set[str] = set()

        for path in root_path.rglob("*"):
            if not path.is_file():
                continue
            relative = str(path.relative_to(root_path)).replace("\\", "/")
            if self._should_skip(path, root_path, ignore, ignore_rules, relative):
                ignored_count += 1
                continue
            if path.suffix.lower() not in supported:
                unsupported_count += 1
                ignored_count += 1
                self._logger.debug("Unsupported file (skipped): {}", relative)
                continue

            if relative in seen_paths:
                continue
            seen_paths.add(relative)

            try:
                content_hash = self._hash_file(path)
                modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                file_size = path.stat().st_size
            except OSError as exc:
                self._logger.warning("Unable to read metadata for {}: {}", relative, exc)
                parse_failures += 1
                continue

            cached = previous_by_path.get(relative)
            if cached is not None and cached.content_hash == content_hash and not force:
                indexed_files.append(cached)
                reused += 1
                continue

            if cached is None:
                newly_added += 1
            else:
                modified += 1

            try:
                parsed = self._parser.parse_file(path, repo_root=root_path)
                files_parsed += 1
            except ParserError as exc:
                self._logger.warning("Parse failure {}: {}", relative, exc.message)
                parse_failures += 1
                indexed_files.append(
                    IndexedFile(
                        relative_path=relative,
                        language="unknown",
                        file_size=file_size,
                        content_hash=content_hash,
                        modified_at=modified_at,
                        module_name=Path(relative).stem,
                        parse_error=exc.message,
                    )
                )
                continue

            indexed_files.append(
                self._to_indexed_file(
                    parsed,
                    relative_path=relative,
                    content_hash=content_hash,
                    file_size=file_size,
                    modified_at=modified_at,
                )
            )

        previous_paths = set(previous_by_path)
        deleted = len(previous_paths - seen_paths)

        duration = time.perf_counter() - started
        index = self._assemble_index(
            root_path=root_path,
            repository_name=name,
            files=indexed_files,
            ignored_count=ignored_count,
            unsupported_count=unsupported_count,
            parse_failures=parse_failures,
            reused=reused,
            newly_added=newly_added,
            modified=modified,
            deleted=deleted,
            files_parsed=files_parsed,
            duration=duration,
        )
        self._persist(index, root_path)
        self._persist_to_db(index)
        self._last_index = index
        self._logger.bind(
            repository=name,
            elapsed_ms=round(duration * 1000.0, 3),
        ).info(
            "Indexed — total={}, parsed={}, reused={}, added={}, modified={}, "
            "deleted={}, ignored={}",
            index.summary.total_indexed_files,
            index.statistics.files_parsed,
            index.statistics.reused_unchanged_files,
            index.statistics.newly_added_files,
            index.statistics.modified_files,
            index.statistics.deleted_files,
            index.statistics.ignored_files,
        )
        return index

    def load_index(self, root: Path | str) -> RepositoryIndex | None:
        path = self._index_path(Path(root))
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return RepositoryIndex.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Failed to load index {}: {}", path, exc)
            return None

    def get_last_index(self) -> RepositoryIndex | None:
        return self._last_index

    # ------------------------------------------------------------------
    # Query helpers (foundation for later retrieval)
    # ------------------------------------------------------------------

    def find_files_defining(self, symbol_name: str, index: RepositoryIndex | None = None) -> list[str]:
        idx = index or self._last_index
        if idx is None:
            return []
        return sorted(
            {
                symbol.file_path
                for symbol in idx.symbols
                if symbol.name == symbol_name
            }
        )

    def find_files_importing(self, module: str, index: RepositoryIndex | None = None) -> list[str]:
        idx = index or self._last_index
        if idx is None:
            return []
        needle = module.removesuffix(".py")
        return sorted(
            {
                ref.source_file
                for ref in idx.import_references
                if ref.target_module == needle or ref.target_module.endswith(f".{needle}")
            }
        )

    def find_files_with_todos(self, index: RepositoryIndex | None = None) -> list[str]:
        idx = index or self._last_index
        if idx is None:
            return []
        return sorted(f.relative_path for f in idx.files if f.todo_tags)

    def assess_staleness(self, root: Path | str) -> dict[str, object]:
        """Compare persisted index size to current on-disk supported sources.

        Returns a plain dict so CLI callers stay decoupled from new models:
        ``{is_stale, indexed_files, current_files, missing_index}``.
        """
        root_path = Path(root).resolve()
        existing = self.load_index(root_path)
        ignore = {d.strip().lower() for d in self._ignore_dirs if d and d.strip()}
        ignore_rules = load_ignore_rules(root_path)
        supported = {ext.lower() for ext in self._parser.supported_extensions()}
        current = 0
        if root_path.is_dir():
            for path in root_path.rglob("*"):
                if not path.is_file():
                    continue
                relative = str(path.relative_to(root_path)).replace("\\", "/")
                if self._should_skip(path, root_path, ignore, ignore_rules, relative):
                    continue
                if path.suffix.lower() not in supported:
                    continue
                current += 1
        if existing is None:
            return {
                "is_stale": current > 0,
                "indexed_files": 0,
                "current_files": current,
                "missing_index": True,
            }
        indexed = int(existing.summary.total_indexed_files)
        return {
            "is_stale": indexed != current,
            "indexed_files": indexed,
            "current_files": current,
            "missing_index": False,
        }

    def changed_files_since(
        self,
        previous: RepositoryIndex,
        current: RepositoryIndex | None = None,
    ) -> list[str]:
        """Return relative paths whose content hash changed (incremental foundation)."""
        current_index = current or self._last_index
        if current_index is None:
            return []
        prev_hashes = previous.file_hashes
        changed: list[str] = []
        for path, digest in current_index.file_hashes.items():
            if prev_hashes.get(path) != digest:
                changed.append(path)
        for path in prev_hashes:
            if path not in current_index.file_hashes:
                changed.append(path)
        return sorted(set(changed))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _to_indexed_file(
        self,
        parsed: ParsedFile,
        *,
        relative_path: str,
        content_hash: str,
        file_size: int,
        modified_at: datetime,
    ) -> IndexedFile:
        module = parsed.module
        symbols: list[IndexedSymbol] = [
            IndexedSymbol(
                name=module.name,
                kind=SymbolKind.MODULE,
                file_path=relative_path,
                start_line=1,
                end_line=parsed.metadata.line_count or 1,
            )
        ]
        nested_names: list[str] = []
        decorators: list[str] = []

        for cls in module.classes:
            symbols.append(
                IndexedSymbol(
                    name=cls.name,
                    kind=SymbolKind.CLASS,
                    file_path=relative_path,
                    start_line=cls.start_line,
                    end_line=cls.end_line,
                    decorators=list(cls.decorators),
                    bases=list(cls.bases),
                )
            )
            decorators.extend(cls.decorators)
            for method in cls.methods:
                symbols.append(
                    IndexedSymbol(
                        name=method.name,
                        kind=SymbolKind.METHOD,
                        file_path=relative_path,
                        start_line=method.start_line,
                        end_line=method.end_line,
                        parent=cls.name,
                        decorators=list(method.decorators),
                        is_async=method.is_async,
                        is_generator=method.is_generator,
                    )
                )
                decorators.extend(method.decorators)
                self._collect_nested_symbols(
                    method,
                    relative_path=relative_path,
                    symbols=symbols,
                    nested_names=nested_names,
                    decorators=decorators,
                )

        function_names: list[str] = []
        for fn in module.functions:
            function_names.append(fn.name)
            symbols.append(
                IndexedSymbol(
                    name=fn.name,
                    kind=SymbolKind.FUNCTION,
                    file_path=relative_path,
                    start_line=fn.start_line,
                    end_line=fn.end_line,
                    decorators=list(fn.decorators),
                    is_async=fn.is_async,
                    is_generator=fn.is_generator,
                )
            )
            decorators.extend(fn.decorators)
            self._collect_nested_symbols(
                fn,
                relative_path=relative_path,
                symbols=symbols,
                nested_names=nested_names,
                decorators=decorators,
            )

        import_names = [imp.raw or imp.module for imp in module.imports]
        import_refs = [
            ImportReference(
                source_file=relative_path,
                source_module=ref.source_module,
                target_module=ref.target_module,
                symbol=ref.symbol,
                kind=ref.kind,
                start_line=ref.start_line,
            )
            for ref in module.references
        ]
        todo_tags = [
            c.tag.value
            for c in module.comments
            if c.tag in {CommentTag.TODO, CommentTag.FIXME, CommentTag.HACK, CommentTag.NOTE}
            and c.tag != CommentTag.NONE
        ]

        return IndexedFile(
            relative_path=relative_path,
            language=parsed.metadata.language,
            file_size=file_size,
            content_hash=content_hash,
            modified_at=modified_at,
            module_name=module.name,
            classes=[cls.name for cls in module.classes],
            functions=function_names,
            nested_functions=nested_names,
            decorators=sorted(set(decorators)),
            imports=import_names,
            comments=[c.text for c in module.comments],
            todo_tags=todo_tags,
            symbols=symbols,
            import_references=import_refs,
            has_syntax_errors=parsed.has_syntax_errors,
            # parse_error is reserved for fatal ParserError failures (exception path).
            parse_error=None,
        )

    def _collect_nested_symbols(
        self,
        fn: ParsedFunction,
        *,
        relative_path: str,
        symbols: list[IndexedSymbol],
        nested_names: list[str],
        decorators: list[str],
    ) -> None:
        for nested in fn.nested_functions:
            nested_names.append(nested.name)
            symbols.append(
                IndexedSymbol(
                    name=nested.name,
                    kind=SymbolKind.NESTED_FUNCTION,
                    file_path=relative_path,
                    start_line=nested.start_line,
                    end_line=nested.end_line,
                    parent=fn.name,
                    decorators=list(nested.decorators),
                    is_async=nested.is_async,
                    is_generator=nested.is_generator,
                )
            )
            decorators.extend(nested.decorators)
            self._collect_nested_symbols(
                nested,
                relative_path=relative_path,
                symbols=symbols,
                nested_names=nested_names,
                decorators=decorators,
            )

    def _assemble_index(
        self,
        *,
        root_path: Path,
        repository_name: str,
        files: list[IndexedFile],
        ignored_count: int,
        unsupported_count: int,
        parse_failures: int,
        reused: int,
        newly_added: int,
        modified: int,
        deleted: int,
        files_parsed: int,
        duration: float,
    ) -> RepositoryIndex:
        total_functions = 0
        total_classes = 0
        total_imports = 0
        total_todos = 0
        total_fixmes = 0
        languages: dict[str, int] = {}
        all_symbols: list[IndexedSymbol] = []
        all_refs: list[ImportReference] = []

        for item in files:
            total_functions += len(item.functions) + len(item.nested_functions)
            method_count = sum(1 for s in item.symbols if s.kind == SymbolKind.METHOD)
            total_functions += method_count
            total_classes += len(item.classes)
            total_imports += len(item.imports)
            total_todos += sum(1 for tag in item.todo_tags if tag == "TODO")
            total_fixmes += sum(1 for tag in item.todo_tags if tag == "FIXME")
            if item.language and item.language != "unknown":
                languages[item.language] = languages.get(item.language, 0) + 1
            all_symbols.extend(item.symbols)
            all_refs.extend(item.import_references)

        indexed_count = sum(1 for f in files if f.parse_error is None)

        # Repository state (totals)
        summary = RepositorySummary(
            repository_root=str(root_path),
            repository_name=repository_name,
            total_indexed_files=indexed_count,
            ignored_file_count=ignored_count,
            total_functions=total_functions,
            total_classes=total_classes,
            total_imports=total_imports,
            todo_count=total_todos + total_fixmes,
            languages=languages,
            timestamp=datetime.now(timezone.utc),
        )
        # This-run activity
        stats = RepositoryStatistics(
            files_parsed=files_parsed,
            reused_unchanged_files=reused,
            newly_added_files=newly_added,
            modified_files=modified,
            deleted_files=deleted,
            ignored_files=ignored_count,
            unsupported_file_count=unsupported_count,
            parse_failures=parse_failures,
            indexing_duration_seconds=round(duration, 4),
        )
        return RepositoryIndex(
            summary=summary,
            statistics=stats,
            files=files,
            symbols=all_symbols,
            import_references=all_refs,
            file_hashes={f.relative_path: f.content_hash for f in files},
        )

    def _persist(self, index: RepositoryIndex, root: Path) -> None:
        path = self._index_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(index.model_dump_json(indent=2), encoding="utf-8")
        self._logger.debug("Persisted index to {}", path)

    def _persist_to_db(self, index: RepositoryIndex) -> None:
        """Persist indexed data to the relational database.

        Uses a single UnitOfWork for repository+files, then per-file
        UoWs for symbols and imports. Never raises — failures are logged
        but never abort the indexing pipeline.
        """
        if self._persistence is None:
            return

        persist_start = time.perf_counter()
        repo_name = index.summary.repository_name
        try:
            repo_data = self._persistence.get_or_create_repository(
                name=repo_name,
                root_path=index.summary.repository_root,
                default_branch="main",
            )
            repo_id = repo_data["id"]
            self._logger.info(
                "DB persist — repository={}, repo_id={}",
                repo_name, repo_id,
            )

            indexable = [f for f in index.files if f.parse_error is None]
            file_dicts = [
                {
                    "path": f.relative_path,
                    "language": f.language or "unknown",
                    "sha256": f.content_hash,
                    "size": f.file_size,
                }
                for f in indexable
            ]
            file_count = self._persistence.persist_files_bulk(repo_id, file_dicts)
            self._logger.info(
                "DB persist — repository={}, files={}",
                repo_name, file_count,
            )

            total_symbols = 0
            total_imports = 0
            with self._persistence.unit_of_work() as uow:
                for f in indexable:
                    file_model = uow.files.get_by_repo_path(repo_id, f.relative_path)
                    if file_model is None:
                        continue
                    file_id = file_model.id

                    if f.symbols:
                        uow.symbols.delete_by_file(file_id)
                        sym_dicts = [
                            {
                                "file_id": file_id,
                                "name": s.name,
                                "type": s.kind.value if hasattr(s.kind, "value") else str(s.kind),
                                "line": s.start_line,
                            }
                            for s in f.symbols
                        ]
                        uow.symbols.bulk_insert(sym_dicts)
                        total_symbols += len(sym_dicts)

                    if f.import_references:
                        uow.imports.delete_by_file(file_id)
                        imp_dicts = [
                            {
                                "file_id": file_id,
                                "module": ref.target_module,
                                "symbol": ref.symbol,
                            }
                            for ref in f.import_references
                        ]
                        uow.imports.bulk_insert(imp_dicts)
                        total_imports += len(imp_dicts)

            self._logger.info(
                "DB persist — repository={}, symbols={}",
                repo_name, total_symbols,
            )
            self._logger.info(
                "DB persist — repository={}, imports={}",
                repo_name, total_imports,
            )

            persist_ms = round((time.perf_counter() - persist_start) * 1000.0, 3)
            self._logger.info(
                "DB persist complete — repository={}, files={}, symbols={}, imports={}, elapsed_ms={}",
                repo_name, file_count, total_symbols, total_imports, persist_ms,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.error(
                "DB persist failed for repository={}: {}\n{}",
                repo_name, exc, _format_traceback(exc),
            )

    @staticmethod
    def _index_path(root: Path) -> Path:
        return root.resolve() / ".refactory" / INDEX_FILENAME

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 64), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _is_ignored(path: Path, root: Path, ignore: set[str]) -> bool:
        try:
            relative = path.resolve().relative_to(root.resolve())
        except ValueError:
            return True
        return any(part.lower() in ignore for part in relative.parts)

    @classmethod
    def _should_skip(
        cls,
        path: Path,
        root: Path,
        ignore: set[str],
        ignore_rules: IgnoreRules,
        relative: str,
    ) -> bool:
        if cls._is_ignored(path, root, ignore):
            return True
        return ignore_rules.is_ignored(relative)


def _format_traceback(exc: Exception) -> str:
    """Format an exception traceback for logging."""
    import traceback

    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
