"""DocumentationService — local documentation extraction and coverage.

Reuses ParserService, IndexerService, RepositoryGraphService,
RepositoryAnalysisService, ImpactAnalysisService, CodeSearchService,
CommitService, and TestIntelligenceService. Never rebuilds the index.
Never calls AI Gateway / network / GitHub. No LLM generation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from refactory.analysis.service import RepositoryAnalysisService
from refactory.codesearch.service import CodeSearchService
from refactory.core.exceptions import IndexError_
from refactory.documentation.models import (
    DocEntry,
    DocGap,
    DocQuality,
    DocTargetKind,
    DocumentationCoverage,
    FileDocsReport,
    ModuleSummary,
    PackageNode,
    RepositoryDocsReport,
    RepositoryStructure,
    StaleDoc,
    SymbolDocsReport,
)
from refactory.git.commit_service import CommitService
from refactory.git.service import GitService
from refactory.graph.service import RepositoryGraphService
from refactory.impact.service import ImpactAnalysisService
from refactory.indexer.models import IndexedFile, RepositoryIndex, SymbolKind
from refactory.indexer.service import IndexerService
from refactory.parser.models import ParsedClass, ParsedFile, ParsedFunction, ParsedModule
from refactory.parser.service import ParserService
from refactory.testing.service import TestIntelligenceService

if TYPE_CHECKING:
    from loguru import Logger


_README_NAMES = ("README.md", "README.rst", "README.txt", "README")
_PLACEHOLDER_RE = re.compile(
    r"^(todo|fixme|tbd|placeholder|\.\.\.|pass|xxx)?\.?$",
    re.IGNORECASE,
)
_SECTION_MARKERS = ("args:", "arguments:", "parameters:", "returns:", "raises:", "yields:", "example")


@dataclass
class _ParsedDocCache:
    content_hash: str
    module_doc: str | None
    entries: list[DocEntry]
    gaps: list[DocGap]
    public_api: list[str]
    imports: list[str]
    classes: list[str]
    functions: list[str]
    todo_docs: list[str]


@dataclass
class _DocsCache:
    root: Path
    index_stamp: str
    index: RepositoryIndex
    graph_ready: bool = False
    parsed: dict[str, _ParsedDocCache] = field(default_factory=dict)
    readme_files: list[str] = field(default_factory=list)
    package_dirs: list[str] = field(default_factory=list)


class DocumentationService:
    """Extract and organize repository documentation without LLM generation."""

    def __init__(
        self,
        logger: "Logger",
        git_service: GitService,
        commit_service: CommitService,
        parser_service: ParserService,
        indexer_service: IndexerService,
        graph_service: RepositoryGraphService,
        repository_analysis_service: RepositoryAnalysisService,
        impact_analysis_service: ImpactAnalysisService,
        code_search_service: CodeSearchService,
        test_intelligence_service: TestIntelligenceService,
        ignore_dirs: list[str] | None = None,
    ) -> None:
        self._logger = logger
        self._git = git_service
        self._commits = commit_service
        self._parser = parser_service
        self._indexer = indexer_service
        self._graph = graph_service
        self._analysis = repository_analysis_service
        self._impact = impact_analysis_service
        self._search = code_search_service
        self._testing = test_intelligence_service
        self._ignore_dirs = {
            d.strip().lower()
            for d in (ignore_dirs or [".git", ".venv", "venv", "node_modules", "__pycache__", ".refactory"])
            if d and d.strip()
        }
        self._cache: _DocsCache | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_repository_docs(self) -> RepositoryDocsReport:
        cache = self._ensure_ready()
        self._warm_all_parses(cache)
        coverage = self.find_documentation_coverage()
        missing = self.find_missing_docstrings()
        readmes = self.find_missing_readmes()
        stale = self.find_stale_documentation()
        public_gaps = self.find_public_api_without_docs()
        todos = self.find_todo_documentation()
        structure = self.build_repository_structure()

        # Light reuse of peer services (no rebuild / no AI).
        try:
            _ = self._analysis.get_repository_languages()
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("analysis touch skipped: {}", exc)
        try:
            _ = self._testing.find_orphan_tests()
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("testing touch skipped: {}", exc)
        try:
            _ = self._commits.get_recent_commits(limit=1)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("commits touch skipped: {}", exc)

        return RepositoryDocsReport(
            root=str(cache.root),
            coverage=coverage,
            missing_docstrings=missing,
            missing_readmes=readmes,
            stale_docs=stale,
            public_api_without_docs=public_gaps,
            todo_documentation=todos,
            structure=structure,
            module_count=len(cache.index.files),
            notes=[],
        )

    def analyze_file_docs(self, path: str) -> FileDocsReport:
        cache = self._ensure_ready()
        norm = self._norm(path)
        parsed = self._parse_docs(norm, cache)
        summary = self.build_module_summary(norm)
        coverage = self._entry_coverage(parsed.entries, parsed.gaps)
        return FileDocsReport(
            path=norm,
            module=summary,
            entries=parsed.entries,
            gaps=parsed.gaps,
            coverage=coverage,
        )

    def analyze_symbol_docs(self, symbol: str) -> SymbolDocsReport:
        cache = self._ensure_ready()
        parent, name = self._split_qualified(symbol)
        entries: list[DocEntry] = []
        gaps: list[DocGap] = []
        found = False

        paths: list[str] = []
        try:
            for match in self._graph.find_symbol(name):
                if parent and (match.parent_name or "").lower() != parent.lower():
                    continue
                if match.file_path:
                    paths.append(self._norm(match.file_path))
                    found = True
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("find_symbol failed for {}: {}", symbol, exc)

        if not paths:
            # Index fallback.
            for indexed in cache.index.symbols:
                if indexed.name != name:
                    continue
                if parent and (indexed.parent or "").lower() != parent.lower():
                    continue
                paths.append(self._norm(indexed.file_path))
                found = True

        for path in sorted(set(paths)):
            parsed = self._parse_docs(path, cache)
            for entry in parsed.entries:
                if entry.symbol and (
                    entry.symbol == name
                    or entry.symbol.endswith(f".{name}")
                    or (parent and entry.symbol == f"{parent}.{name}")
                ):
                    entries.append(entry)
            for gap in parsed.gaps:
                if gap.symbol and (
                    gap.symbol == name
                    or gap.symbol.endswith(f".{name}")
                    or (parent and gap.symbol == f"{parent}.{name}")
                ):
                    gaps.append(gap)

        # Optional search assist for locating symbols (structural only path).
        if not found:
            try:
                result = self._search.find_definition(symbol)
                found = bool(result.hits)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("search definition skipped: {}", exc)

        return SymbolDocsReport(symbol=symbol.strip(), entries=entries, gaps=gaps, found=found)

    def find_missing_docstrings(self) -> list[DocGap]:
        cache = self._ensure_ready()
        self._warm_all_parses(cache)
        gaps: list[DocGap] = []
        for path, parsed in cache.parsed.items():
            for gap in parsed.gaps:
                if gap.quality == DocQuality.MISSING and gap.kind != DocTargetKind.README:
                    gaps.append(gap)
        return sorted(gaps, key=lambda g: (g.path, g.kind.value, g.symbol or ""))

    def find_missing_readmes(self) -> list[DocGap]:
        cache = self._ensure_ready()
        gaps: list[DocGap] = []
        readme_dirs = {
            (str(Path(p).parent).replace("\\", "/") or ".") for p in cache.readme_files
        }
        for package in cache.package_dirs:
            if package in readme_dirs:
                continue
            gaps.append(
                DocGap(
                    path=package,
                    kind=DocTargetKind.README,
                    reason="package_missing_readme",
                    quality=DocQuality.MISSING,
                )
            )
        return gaps

    def find_stale_documentation(self) -> list[StaleDoc]:
        cache = self._ensure_ready()
        stale: list[StaleDoc] = []
        for readme in cache.readme_files:
            readme_path = cache.root / readme
            package = str(Path(readme).parent).replace("\\", "/")
            if package == "":
                package = "."
            try:
                doc_mtime = datetime.fromtimestamp(readme_path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue

            newest_source: datetime | None = None
            related: str | None = None
            for indexed in cache.index.files:
                path = self._norm(indexed.relative_path)
                parent = str(Path(path).parent).replace("\\", "/") or "."
                if parent != package and not (package == "." and parent == "."):
                    continue
                src = cache.root / path
                try:
                    mtime = datetime.fromtimestamp(src.stat().st_mtime, tz=timezone.utc)
                except OSError:
                    continue
                if newest_source is None or mtime > newest_source:
                    newest_source = mtime
                    related = path

            if newest_source is not None and newest_source > doc_mtime:
                stale.append(
                    StaleDoc(
                        path=readme,
                        related_source=related,
                        doc_mtime=doc_mtime,
                        source_mtime=newest_source,
                        reason="readme_older_than_source",
                        confidence=0.8,
                    )
                )

            # Commit-based freshness when history is available.
            if related:
                try:
                    hist = self._analysis.get_file_history(related)
                    readme_hist = self._analysis.get_file_history(readme)
                    if (
                        hist.last_modification_at
                        and readme_hist.last_modification_at
                        and hist.last_modification_at > readme_hist.last_modification_at
                    ):
                        stale.append(
                            StaleDoc(
                                path=readme,
                                related_source=related,
                                doc_mtime=readme_hist.last_modification_at,
                                source_mtime=hist.last_modification_at,
                                reason="readme_commit_older_than_source",
                                confidence=0.85,
                            )
                        )
                except Exception as exc:  # noqa: BLE001
                    self._logger.debug("stale commit check skipped: {}", exc)

        # Deduplicate by path+reason
        best: dict[tuple[str, str], StaleDoc] = {}
        for item in stale:
            key = (item.path, item.reason)
            existing = best.get(key)
            if existing is None or item.confidence > existing.confidence:
                best[key] = item
        return sorted(best.values(), key=lambda s: (-s.confidence, s.path))

    def find_public_api_without_docs(self) -> list[DocGap]:
        cache = self._ensure_ready()
        self._warm_all_parses(cache)
        gaps: list[DocGap] = []
        for path, parsed in cache.parsed.items():
            for gap in parsed.gaps:
                # Public gaps only.
                if gap.quality != DocQuality.MISSING:
                    continue
                if gap.kind == DocTargetKind.MODULE:
                    gaps.append(gap)
                    continue
                symbol = gap.symbol or ""
                bare = symbol.rsplit(".", 1)[-1]
                if bare.startswith("_"):
                    continue
                if gap.kind in {
                    DocTargetKind.CLASS,
                    DocTargetKind.FUNCTION,
                    DocTargetKind.METHOD,
                }:
                    gaps.append(gap)
        return sorted(gaps, key=lambda g: (g.path, g.symbol or ""))

    def find_documentation_coverage(self) -> DocumentationCoverage:
        cache = self._ensure_ready()
        self._warm_all_parses(cache)

        total_modules = documented_modules = 0
        total_classes = documented_classes = 0
        total_functions = documented_functions = 0
        total_public = documented_public = 0

        for path, parsed in cache.parsed.items():
            total_modules += 1
            if parsed.module_doc and self._quality(parsed.module_doc) != DocQuality.MISSING:
                documented_modules += 1
            for entry in parsed.entries:
                if entry.kind == DocTargetKind.CLASS:
                    total_classes += 1
                    if entry.quality not in {DocQuality.MISSING}:
                        documented_classes += 1
                elif entry.kind in {DocTargetKind.FUNCTION, DocTargetKind.METHOD}:
                    total_functions += 1
                    if entry.quality not in {DocQuality.MISSING}:
                        documented_functions += 1
                if entry.is_public and entry.kind != DocTargetKind.MODULE:
                    total_public += 1
                    if entry.quality != DocQuality.MISSING:
                        documented_public += 1
            # Module itself as public API surface.
            total_public += 1
            if parsed.module_doc and self._quality(parsed.module_doc) != DocQuality.MISSING:
                documented_public += 1

        packages = cache.package_dirs
        modules_with_readme = 0
        readme_dirs = {str(Path(p).parent).replace("\\", "/") or "." for p in cache.readme_files}
        for package in packages:
            if package in readme_dirs or (
                package == "." and any("/" not in p for p in cache.readme_files)
            ):
                modules_with_readme += 1
        missing_readme = max(0, len(packages) - modules_with_readme)

        def ratio(num: int, den: int) -> float:
            return round((num / den) if den else 0.0, 4)

        module_cov = ratio(documented_modules, total_modules)
        class_cov = ratio(documented_classes, total_classes)
        func_cov = ratio(documented_functions, total_functions)
        public_cov = ratio(documented_public, total_public)
        overall = round((module_cov + class_cov + func_cov + public_cov) / 4.0, 4)

        return DocumentationCoverage(
            total_modules=total_modules,
            documented_modules=documented_modules,
            total_classes=total_classes,
            documented_classes=documented_classes,
            total_functions=total_functions,
            documented_functions=documented_functions,
            total_public_api=total_public,
            documented_public_api=documented_public,
            modules_with_readme=modules_with_readme,
            packages_missing_readme=missing_readme,
            module_coverage=module_cov,
            class_coverage=class_cov,
            function_coverage=func_cov,
            public_api_coverage=public_cov,
            overall_coverage=overall,
        )

    def find_todo_documentation(self) -> list[DocGap]:
        cache = self._ensure_ready()
        gaps: list[DocGap] = []
        for indexed in cache.index.files:
            path = self._norm(indexed.relative_path)
            for comment in indexed.comments:
                upper = comment.upper()
                if not any(tag in upper for tag in ("TODO", "FIXME", "DOC", "DOCUMENT")):
                    continue
                if "DOC" in upper or "DOCUMENT" in upper or "TODO" in upper or "FIXME" in upper:
                    gaps.append(
                        DocGap(
                            path=path,
                            kind=DocTargetKind.UNKNOWN,
                            reason="documentation_todo",
                            quality=DocQuality.POOR,
                        )
                    )
            for tag in indexed.todo_tags:
                if tag.upper() in {"TODO", "FIXME", "NOTE"}:
                    gaps.append(
                        DocGap(
                            path=path,
                            symbol=tag,
                            kind=DocTargetKind.UNKNOWN,
                            reason="todo_tag",
                            quality=DocQuality.POOR,
                        )
                    )
        # Also docstring placeholders from parses.
        self._warm_all_parses(cache)
        for path, parsed in cache.parsed.items():
            for note in parsed.todo_docs:
                gaps.append(
                    DocGap(
                        path=path,
                        reason=note,
                        kind=DocTargetKind.UNKNOWN,
                        quality=DocQuality.POOR,
                    )
                )
        # Dedupe
        seen: set[tuple[str, str | None, str]] = set()
        out: list[DocGap] = []
        for gap in gaps:
            key = (gap.path, gap.symbol, gap.reason)
            if key in seen:
                continue
            seen.add(key)
            out.append(gap)
        return sorted(out, key=lambda g: (g.path, g.reason))

    def build_module_summary(self, path: str) -> ModuleSummary:
        cache = self._ensure_ready()
        norm = self._norm(path)
        indexed = self._file_by_path(cache, norm)
        parsed = self._parse_docs(norm, cache)

        deps: list[str] = []
        dependents: list[str] = []
        try:
            deps = [self._norm(p) for p in self._graph.dependencies_of(norm)]
            dependents = [self._norm(p) for p in self._graph.reverse_dependencies(norm)]
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("graph edges skipped for {}: {}", norm, exc)

        owners: list[str] = []
        try:
            authors = self._analysis.get_file_authors(norm)
            owners = [f"{a.name} <{a.email}>" for a in authors[:5]]
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("owners skipped for {}: {}", norm, exc)

        package = str(Path(norm).parent).replace("\\", "/") or "."
        has_readme = any(
            (str(Path(r).parent).replace("\\", "/") or ".") == package for r in cache.readme_files
        )

        # Soft impact touch for dependency awareness (cached inside impact service).
        try:
            _ = self._impact.analyze_file(norm)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("impact touch skipped for {}: {}", norm, exc)

        documented = sum(1 for e in parsed.entries if e.quality != DocQuality.MISSING)
        total = max(1, len(parsed.entries))
        return ModuleSummary(
            path=norm,
            module_name=indexed.module_name if indexed else Path(norm).stem,
            docstring=parsed.module_doc,
            classes=parsed.classes,
            functions=parsed.functions,
            imports=parsed.imports,
            public_api=parsed.public_api,
            dependencies=deps,
            dependents=dependents,
            owners=owners,
            has_readme=has_readme,
            docstring_coverage=round(documented / total, 4),
            todo_docs=parsed.todo_docs,
        )

    def build_repository_structure(self) -> RepositoryStructure:
        cache = self._ensure_ready()
        packages: dict[str, PackageNode] = {}
        top_level: list[str] = []

        for indexed in cache.index.files:
            path = self._norm(indexed.relative_path)
            parent = str(Path(path).parent).replace("\\", "/") or "."
            if parent == ".":
                top_level.append(path)
            node = packages.get(parent)
            if node is None:
                node = PackageNode(
                    path=parent,
                    has_readme=any(
                        (str(Path(r).parent).replace("\\", "/") or ".") == parent
                        for r in cache.readme_files
                    ),
                    has_init=any(
                        self._norm(f.relative_path) == f"{parent}/__init__.py"
                        or (parent == "." and self._norm(f.relative_path) == "__init__.py")
                        for f in cache.index.files
                    ),
                )
                packages[parent] = node
            node.modules.append(path)

        # Nest package children.
        for pkg_path, node in packages.items():
            if pkg_path == ".":
                continue
            parent = str(Path(pkg_path).parent).replace("\\", "/") or "."
            if parent in packages and parent != pkg_path:
                packages[parent].packages.append(pkg_path)

        ordered = sorted(packages.values(), key=lambda n: (n.path != ".", n.path))
        for node in ordered:
            node.modules = sorted(set(node.modules))
            node.packages = sorted(set(node.packages))

        return RepositoryStructure(
            root=str(cache.root),
            packages=ordered,
            top_level_modules=sorted(set(top_level)),
            readme_files=list(cache.readme_files),
        )

    # ------------------------------------------------------------------
    # Parsing / cache
    # ------------------------------------------------------------------

    def _ensure_ready(self) -> _DocsCache:
        root = self._git.get_root_path()
        index = self._load_index_only(root)
        stamp = (
            f"{index.summary.timestamp.isoformat()}|"
            f"{index.summary.total_indexed_files}|"
            f"{len(index.symbols)}|"
            f"{len(index.file_hashes)}"
        )
        if (
            self._cache is not None
            and self._cache.root == root
            and self._cache.index_stamp == stamp
            and self._cache.graph_ready
        ):
            return self._cache

        self._graph.build_graph(index)
        readmes = self._discover_readmes(root)
        packages = self._discover_packages(index)
        self._cache = _DocsCache(
            root=root,
            index_stamp=stamp,
            index=index,
            graph_ready=True,
            readme_files=readmes,
            package_dirs=packages,
        )
        self._logger.info(
            "Documentation intelligence ready — {} file(s), {} README(s)",
            len(index.files),
            len(readmes),
        )
        return self._cache

    def _load_index_only(self, root: Path) -> RepositoryIndex:
        existing = self._indexer.load_index(root)
        if existing is not None:
            return existing
        last = self._indexer.get_last_index()
        if last is not None:
            return last
        raise IndexError_(
            "No cached repository index found. Run `refactory index` first "
            "(DocumentationService never rebuilds the repository)."
        )

    def _warm_all_parses(self, cache: _DocsCache) -> None:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        py_paths = [
            self._norm(indexed.relative_path)
            for indexed in cache.index.files
            if indexed.relative_path.endswith(".py")
        ]
        if not py_paths:
            return

        def _parse_one(p: str) -> None:
            try:
                self._parse_docs(p, cache)
            except Exception:  # noqa: BLE001
                pass

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(_parse_one, p) for p in py_paths]
            for f in as_completed(futures):
                f.result()

    def _parse_docs(self, path: str, cache: _DocsCache) -> _ParsedDocCache:
        path = self._norm(path)
        indexed = self._file_by_path(cache, path)
        content_hash = indexed.content_hash if indexed else ""
        existing = cache.parsed.get(path)
        if existing is not None and existing.content_hash == content_hash:
            return existing

        abs_path = cache.root / path
        module_doc: str | None = None
        entries: list[DocEntry] = []
        gaps: list[DocGap] = []
        public_api: list[str] = []
        imports: list[str] = []
        classes: list[str] = []
        functions: list[str] = []
        todo_docs: list[str] = []

        if abs_path.is_file() and path.endswith(".py"):
            try:
                parsed_file: ParsedFile = self._parser.parse_file(abs_path, repo_root=cache.root)
                module: ParsedModule = parsed_file.module
                module_doc = module.docstring
                imports = sorted({imp.module for imp in module.imports if imp.module})
                quality = self._quality(module_doc)
                entries.append(
                    DocEntry(
                        path=path,
                        symbol=module.name,
                        kind=DocTargetKind.MODULE,
                        docstring=module_doc,
                        quality=quality,
                        line=1,
                        is_public=True,
                    )
                )
                if quality == DocQuality.MISSING:
                    gaps.append(
                        DocGap(
                            path=path,
                            symbol=module.name,
                            kind=DocTargetKind.MODULE,
                            reason="missing_module_docstring",
                            quality=DocQuality.MISSING,
                            line=1,
                        )
                    )
                if module_doc and _PLACEHOLDER_RE.match(module_doc.strip()):
                    todo_docs.append("placeholder_module_docstring")

                for cls in module.classes:
                    self._collect_class(path, cls, entries, gaps, public_api, classes, todo_docs)
                for fn in module.functions:
                    self._collect_function(
                        path, fn, entries, gaps, public_api, functions, todo_docs, parent=None
                    )
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("parse_file failed for {}: {}", path, exc)
                # Fall back to index symbols as undocumented.
                if indexed is not None:
                    for sym in indexed.symbols:
                        if sym.kind == SymbolKind.MODULE:
                            continue
                        kind = self._symbol_kind(sym.kind)
                        label = f"{sym.parent}.{sym.name}" if sym.parent else sym.name
                        gaps.append(
                            DocGap(
                                path=path,
                                symbol=label,
                                kind=kind,
                                reason="unparsed_missing_docstring",
                                quality=DocQuality.MISSING,
                                line=sym.start_line,
                            )
                        )
        elif indexed is not None:
            # Non-python or missing file — report index symbols without docs.
            for sym in indexed.symbols:
                if sym.kind == SymbolKind.MODULE:
                    continue
                kind = self._symbol_kind(sym.kind)
                label = f"{sym.parent}.{sym.name}" if sym.parent else sym.name
                gaps.append(
                    DocGap(
                        path=path,
                        symbol=label,
                        kind=kind,
                        reason="unavailable_source",
                        quality=DocQuality.MISSING,
                        line=sym.start_line,
                    )
                )

        result = _ParsedDocCache(
            content_hash=content_hash,
            module_doc=module_doc,
            entries=entries,
            gaps=gaps,
            public_api=sorted(set(public_api)),
            imports=imports,
            classes=sorted(set(classes)),
            functions=sorted(set(functions)),
            todo_docs=todo_docs,
        )
        cache.parsed[path] = result
        return result

    def _collect_class(
        self,
        path: str,
        cls: ParsedClass,
        entries: list[DocEntry],
        gaps: list[DocGap],
        public_api: list[str],
        classes: list[str],
        todo_docs: list[str],
    ) -> None:
        is_public = not cls.name.startswith("_")
        quality = self._quality(cls.docstring)
        entries.append(
            DocEntry(
                path=path,
                symbol=cls.name,
                kind=DocTargetKind.CLASS,
                docstring=cls.docstring,
                quality=quality,
                line=cls.start_line,
                is_public=is_public,
            )
        )
        classes.append(cls.name)
        if is_public:
            public_api.append(cls.name)
        if quality == DocQuality.MISSING and is_public:
            gaps.append(
                DocGap(
                    path=path,
                    symbol=cls.name,
                    kind=DocTargetKind.CLASS,
                    reason="missing_class_docstring",
                    quality=DocQuality.MISSING,
                    line=cls.start_line,
                )
            )
        if cls.docstring and _PLACEHOLDER_RE.match(cls.docstring.strip()):
            todo_docs.append(f"placeholder_class_docstring:{cls.name}")
        for method in cls.methods:
            self._collect_function(
                path,
                method,
                entries,
                gaps,
                public_api,
                [],
                todo_docs,
                parent=cls.name,
            )

    def _collect_function(
        self,
        path: str,
        fn: ParsedFunction,
        entries: list[DocEntry],
        gaps: list[DocGap],
        public_api: list[str],
        functions: list[str],
        todo_docs: list[str],
        *,
        parent: str | None,
    ) -> None:
        is_public = not fn.name.startswith("_")
        if parent and parent.startswith("_"):
            is_public = False
        quality = self._quality(fn.docstring)
        label = f"{parent}.{fn.name}" if parent else fn.name
        kind = DocTargetKind.METHOD if parent or fn.is_method else DocTargetKind.FUNCTION
        entries.append(
            DocEntry(
                path=path,
                symbol=label,
                kind=kind,
                docstring=fn.docstring,
                quality=quality,
                line=fn.start_line,
                is_public=is_public,
            )
        )
        if parent is None:
            functions.append(fn.name)
        if is_public and parent is None:
            public_api.append(fn.name)
        elif is_public and parent and not parent.startswith("_"):
            public_api.append(label)
        if quality == DocQuality.MISSING and is_public:
            gaps.append(
                DocGap(
                    path=path,
                    symbol=label,
                    kind=kind,
                    reason="missing_function_docstring"
                    if kind == DocTargetKind.FUNCTION
                    else "missing_method_docstring",
                    quality=DocQuality.MISSING,
                    line=fn.start_line,
                )
            )
        if fn.docstring and _PLACEHOLDER_RE.match(fn.docstring.strip()):
            todo_docs.append(f"placeholder_function_docstring:{label}")
        for nested in fn.nested_functions:
            self._collect_function(
                path,
                nested,
                entries,
                gaps,
                public_api,
                functions,
                todo_docs,
                parent=label,
            )

    # ------------------------------------------------------------------
    # Discovery helpers
    # ------------------------------------------------------------------

    def _discover_readmes(self, root: Path) -> list[str]:
        found: list[str] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.name not in _README_NAMES and not path.name.upper().startswith("README"):
                continue
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if any(part.lower() in self._ignore_dirs for part in rel.parts):
                continue
            found.append(self._norm(str(rel)))
        return sorted(set(found))

    def _discover_packages(self, index: RepositoryIndex) -> list[str]:
        packages: set[str] = {"."}
        for indexed in index.files:
            path = self._norm(indexed.relative_path)
            parent = str(Path(path).parent).replace("\\", "/") or "."
            packages.add(parent)
            # Intermediate dirs.
            parts = Path(path).parts[:-1]
            for i in range(len(parts)):
                packages.add("/".join(parts[: i + 1]))
        return sorted(packages)

    def _file_by_path(self, cache: _DocsCache, path: str) -> IndexedFile | None:
        path = self._norm(path)
        for indexed in cache.index.files:
            if self._norm(indexed.relative_path) == path:
                return indexed
        return None

    @staticmethod
    def _quality(docstring: str | None) -> DocQuality:
        if not docstring or not docstring.strip():
            return DocQuality.MISSING
        text = docstring.strip()
        if _PLACEHOLDER_RE.match(text) or len(text) < 8:
            return DocQuality.POOR
        lower = text.lower()
        if any(marker in lower for marker in _SECTION_MARKERS) or len(text) >= 80:
            return DocQuality.GOOD
        return DocQuality.BASIC

    @staticmethod
    def _entry_coverage(entries: list[DocEntry], gaps: list[DocGap]) -> float:
        total = len(entries) + len([g for g in gaps if g.quality == DocQuality.MISSING])
        # Prefer entries-only denominator when entries already include missing as MISSING quality.
        if entries:
            documented = sum(1 for e in entries if e.quality != DocQuality.MISSING)
            return round(documented / len(entries), 4)
        return 0.0 if total == 0 else 0.0

    @staticmethod
    def _symbol_kind(kind: SymbolKind) -> DocTargetKind:
        return {
            SymbolKind.CLASS: DocTargetKind.CLASS,
            SymbolKind.FUNCTION: DocTargetKind.FUNCTION,
            SymbolKind.METHOD: DocTargetKind.METHOD,
            SymbolKind.NESTED_FUNCTION: DocTargetKind.FUNCTION,
            SymbolKind.MODULE: DocTargetKind.MODULE,
        }.get(kind, DocTargetKind.UNKNOWN)

    @staticmethod
    def _split_qualified(symbol: str) -> tuple[str | None, str]:
        text = (symbol or "").strip()
        if "." in text and not text.endswith(".py"):
            parent, name = text.rsplit(".", 1)
            if parent and name:
                return parent, name
        return None, text

    @staticmethod
    def _norm(path: str) -> str:
        return path.replace("\\", "/").lstrip("./")
