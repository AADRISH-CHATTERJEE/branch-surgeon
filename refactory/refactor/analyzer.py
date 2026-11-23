"""Refactoring analyzers — 10 deterministic code-quality detectors.

Each analyzer appends issues to a shared list. All reuse existing services;
none duplicate graph traversal, parsing, or search logic.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from refactory.documentation.service import DocumentationService
from refactory.graph.models import (
    DependencyCycle,
    DeadCodeCandidate,
    FileNode,
    NodeKind,
    OrphanModule,
    UnusedSymbol,
)
from refactory.graph.service import RepositoryGraphService
from refactory.indexer.models import IndexedFile, RepositoryIndex
from refactory.indexer.service import IndexerService
from refactory.parser.models import ParsedClass, ParsedFile, ParsedFunction
from refactory.parser.service import ParserService
from refactory.refactor.models import (
    RefactorCategory,
    RefactorIssue,
    RefactorSeverity,
)

if TYPE_CHECKING:
    from loguru import Logger

# ---------------------------------------------------------------
# Naming conventions
# ---------------------------------------------------------------
_SNAKE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_CAMEL_RE = re.compile(r"^[a-z][a-zA-Z0-9]*$")
_PASCAL_RE = re.compile(r"^[A-Z][a-zA-Z0-9]*$")
_UPPER_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")

# Layer keywords for heuristic layer inference
_LAYER_KEYWORDS: dict[str, int] = {
    "model": 1, "models": 1, "schema": 1, "entity": 1, "domain": 1,
    "service": 2, "core": 2, "logic": 2, "engine": 2,
    "repository": 3, "dao": 3, "db": 3, "database": 3, "migration": 3,
    "api": 4, "route": 4, "router": 4, "controller": 4, "handler": 4,
    "view": 5, "template": 5, "ui": 5, "page": 5, "component": 5,
    "cli": 6, "command": 6, "commands": 6,
    "config": 0, "settings": 0, "util": 0, "utils": 0, "helper": 0,
    "test": -1, "tests": -1, "spec": -1,
}


class RefactoringAnalyzer:
    """Runs all 10 analyzers and collects issues."""

    def __init__(
        self,
        logger: "Logger",
        parser_service: ParserService,
        indexer_service: IndexerService,
        graph_service: RepositoryGraphService,
        documentation_service: DocumentationService,
        *,
        large_file_lines: int = 300,
        large_file_functions: int = 15,
        large_file_classes: int = 5,
        long_function_lines: int = 50,
        long_function_branches: int = 10,
        god_class_methods: int = 10,
        god_class_fan_out: int = 8,
        branch_age_stale: float = 30.0,
    ) -> None:
        self._logger = logger
        self._parser = parser_service
        self._indexer = indexer_service
        self._graph = graph_service
        self._docs = documentation_service
        self._large_file_lines = large_file_lines
        self._large_file_functions = large_file_functions
        self._large_file_classes = large_file_classes
        self._long_function_lines = long_function_lines
        self._long_function_branches = long_function_branches
        self._god_class_methods = god_class_methods
        self._god_class_fan_out = god_class_fan_out

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_all(
        self,
        index: RepositoryIndex,
        parsed_files: dict[str, ParsedFile],
        *,
        target_file: str | None = None,
    ) -> list[RefactorIssue]:
        """Run every analyzer and return combined issues."""
        issues: list[RefactorIssue] = []

        files = self._filter_files(index, target_file)

        self._check_large_files(files, parsed_files, issues)
        self._check_long_functions(files, parsed_files, issues)
        self._check_god_classes(files, parsed_files, issues)
        self._check_unused_imports(files, parsed_files, issues)
        self._check_naming_consistency(files, parsed_files, issues)
        self._check_dead_code(issues, target_file)
        self._check_circular_dependencies(issues, target_file)
        self._check_duplicate_logic(files, parsed_files, issues)
        self._check_layer_violations(files, index, issues)
        self._check_documentation_drift(issues, target_file)

        issues.sort(
            key=lambda i: (
                {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(i.severity.value, 4),
                i.category.value,
                i.file,
            )
        )
        return issues

    # ------------------------------------------------------------------
    # 1. Large file detection
    # ------------------------------------------------------------------

    def _check_large_files(
        self,
        files: list[IndexedFile],
        parsed: dict[str, ParsedFile],
        issues: list[RefactorIssue],
    ) -> None:
        for f in files:
            pf = parsed.get(f.relative_path)
            lines = pf.metadata.line_count if pf else f.file_size // 40
            n_funcs = len(f.functions) + len(f.nested_functions)
            n_classes = len(f.classes)

            reasons: list[str] = []
            if lines > self._large_file_lines:
                reasons.append(f"{lines} lines (threshold: {self._large_file_lines})")
            if n_funcs > self._large_file_functions:
                reasons.append(f"{n_funcs} functions (threshold: {self._large_file_functions})")
            if n_classes > self._large_file_classes:
                reasons.append(f"{n_classes} classes (threshold: {self._large_file_classes})")

            if not reasons:
                continue

            severity = RefactorSeverity.HIGH if lines > self._large_file_lines * 2 else RefactorSeverity.MEDIUM
            issues.append(RefactorIssue(
                category=RefactorCategory.LARGE_FILE,
                severity=severity,
                title=f"Large file: {f.relative_path}",
                detail="; ".join(reasons),
                file=f.relative_path,
                metrics={"lines": lines, "functions": n_funcs, "classes": n_classes},
            ))

    # ------------------------------------------------------------------
    # 2. Long function detection
    # ------------------------------------------------------------------

    def _check_long_functions(
        self,
        files: list[IndexedFile],
        parsed: dict[str, ParsedFile],
        issues: list[RefactorIssue],
    ) -> None:
        for f in files:
            pf = parsed.get(f.relative_path)
            if pf is None:
                continue
            for func in self._all_functions(pf):
                length = func.end_line - func.start_line + 1
                if length <= self._long_function_lines:
                    continue
                severity = RefactorSeverity.HIGH if length > self._long_function_lines * 2 else RefactorSeverity.MEDIUM
                issues.append(RefactorIssue(
                    category=RefactorCategory.LONG_FUNCTION,
                    severity=severity,
                    title=f"Long function: {func.name}",
                    detail=f"{length} lines in {f.relative_path} (threshold: {self._long_function_lines})",
                    file=f.relative_path,
                    symbol=func.name,
                    line=func.start_line,
                    metrics={"lines": length},
                ))

    # ------------------------------------------------------------------
    # 3. Duplicate logic detection
    # ------------------------------------------------------------------

    def _check_duplicate_logic(
        self,
        files: list[IndexedFile],
        parsed: dict[str, ParsedFile],
        issues: list[RefactorIssue],
    ) -> None:
        sig_map: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for f in files:
            pf = parsed.get(f.relative_path)
            if pf is None:
                continue
            for func in self._all_functions(pf):
                sig = self._function_signature(func)
                if sig:
                    sig_map[sig].append((f.relative_path, func.name))

        for sig, locations in sig_map.items():
            if len(locations) < 2:
                continue
            names = [f"{path}::{name}" for path, name in locations[:5]]
            issues.append(RefactorIssue(
                category=RefactorCategory.DUPLICATE_LOGIC,
                severity=RefactorSeverity.MEDIUM,
                title=f"Possible duplicate: {locations[0][1]}",
                detail=(
                    f"{len(locations)} functions share similar signature. "
                    f"Locations: {', '.join(names)}"
                ),
                file=locations[0][0],
                symbol=locations[0][1],
                metrics={"duplicate_count": len(locations)},
            ))

    # ------------------------------------------------------------------
    # 4. Dead code detection
    # ------------------------------------------------------------------

    def _check_dead_code(
        self,
        issues: list[RefactorIssue],
        target_file: str | None,
    ) -> None:
        try:
            candidates = self._graph.dead_code_candidates()
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("Dead code detection skipped: {}", exc)
            return

        for dc in candidates:
            if target_file and dc.file_path and not self._path_matches(dc.file_path, target_file):
                continue
            if self._is_pytest_test(dc):
                continue
            issues.append(RefactorIssue(
                category=RefactorCategory.DEAD_CODE,
                severity=RefactorSeverity.LOW,
                title=f"Dead code: {dc.name}",
                detail=f"{dc.reason} in {dc.file_path or 'unknown'}",
                file=dc.file_path or "",
                symbol=dc.name,
            ))

    # ------------------------------------------------------------------
    # 5. Unused imports
    # ------------------------------------------------------------------

    def _check_unused_imports(
        self,
        files: list[IndexedFile],
        parsed: dict[str, ParsedFile],
        issues: list[RefactorIssue],
    ) -> None:
        for f in files:
            pf = parsed.get(f.relative_path)
            if pf is None:
                continue
            used_names = self._collect_used_names(pf)
            for imp in pf.module.imports:
                for name in imp.names:
                    if name == "*":
                        continue
                    alias = imp.alias or name
                    if alias not in used_names:
                        issues.append(RefactorIssue(
                            category=RefactorCategory.UNUSED_IMPORT,
                            severity=RefactorSeverity.LOW,
                            title=f"Unused import: {name}",
                            detail=f"'{name}' imported but not referenced in {f.relative_path}",
                            file=f.relative_path,
                            symbol=name,
                            line=imp.start_line,
                        ))
                if not imp.names and not imp.is_from_import:
                    mod_short = imp.module.rsplit(".", 1)[-1]
                    alias = imp.alias or mod_short
                    if alias not in used_names:
                        issues.append(RefactorIssue(
                            category=RefactorCategory.UNUSED_IMPORT,
                            severity=RefactorSeverity.LOW,
                            title=f"Unused import: {imp.module}",
                            detail=f"'{imp.module}' imported but not referenced in {f.relative_path}",
                            file=f.relative_path,
                            symbol=imp.module,
                            line=imp.start_line,
                        ))

    # ------------------------------------------------------------------
    # 6. Circular dependency detection
    # ------------------------------------------------------------------

    def _check_circular_dependencies(
        self,
        issues: list[RefactorIssue],
        target_file: str | None,
    ) -> None:
        try:
            cycles = self._graph.find_cycles()
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("Cycle detection skipped: {}", exc)
            return

        for cycle in cycles:
            if target_file and not any(self._path_matches(f, target_file) for f in cycle.files):
                continue
            severity = RefactorSeverity.HIGH if len(cycle.files) >= 3 else RefactorSeverity.MEDIUM
            issues.append(RefactorIssue(
                category=RefactorCategory.CIRCULAR_DEPENDENCY,
                severity=severity,
                title=f"Circular dependency ({len(cycle.files)} files)",
                detail=" -> ".join(cycle.files) + f" -> {cycle.files[0]}",
                file=cycle.files[0] if cycle.files else "",
                metrics={"cycle_length": len(cycle.files)},
            ))

    # ------------------------------------------------------------------
    # 7. God class detection
    # ------------------------------------------------------------------

    def _check_god_classes(
        self,
        files: list[IndexedFile],
        parsed: dict[str, ParsedFile],
        issues: list[RefactorIssue],
    ) -> None:
        for f in files:
            pf = parsed.get(f.relative_path)
            if pf is None:
                continue
            for cls in pf.module.classes:
                n_methods = len(cls.methods)
                n_props = len(cls.properties)
                fan_out = self._class_fan_out(cls)

                is_god = (
                    n_methods >= self._god_class_methods
                    or fan_out >= self._god_class_fan_out
                )
                if not is_god:
                    continue
                severity = RefactorSeverity.HIGH if n_methods >= self._god_class_methods * 2 else RefactorSeverity.MEDIUM
                issues.append(RefactorIssue(
                    category=RefactorCategory.GOD_CLASS,
                    severity=severity,
                    title=f"God class: {cls.name}",
                    detail=(
                        f"{n_methods} methods, {n_props} properties, "
                        f"fan-out ~{fan_out} in {f.relative_path}"
                    ),
                    file=f.relative_path,
                    symbol=cls.name,
                    line=cls.start_line,
                    metrics={"methods": n_methods, "properties": n_props, "fan_out": fan_out},
                ))

    # ------------------------------------------------------------------
    # 8. Layer violation detection
    # ------------------------------------------------------------------

    def _check_layer_violations(
        self,
        files: list[IndexedFile],
        index: RepositoryIndex,
        issues: list[RefactorIssue],
    ) -> None:
        file_layer: dict[str, int] = {}
        for f in index.files:
            layer = self._infer_layer(f.relative_path)
            if layer is not None:
                file_layer[f.relative_path] = layer

        for f in files:
            src_layer = file_layer.get(f.relative_path)
            if src_layer is None or src_layer <= 0:
                continue
            for ref in f.import_references:
                target_path = self._resolve_import_path(ref.target_module, index)
                if target_path is None:
                    continue
                dst_layer = file_layer.get(target_path)
                if dst_layer is None or dst_layer <= 0:
                    continue
                # Lower layer number = deeper. Deeper importing shallower is a violation.
                if src_layer < dst_layer:
                    issues.append(RefactorIssue(
                        category=RefactorCategory.LAYER_VIOLATION,
                        severity=RefactorSeverity.MEDIUM,
                        title=f"Layer violation: {f.relative_path} -> {target_path}",
                        detail=(
                            f"Lower layer ({self._layer_name(src_layer)}) "
                            f"imports higher layer ({self._layer_name(dst_layer)})"
                        ),
                        file=f.relative_path,
                        line=ref.start_line,
                    ))

    # ------------------------------------------------------------------
    # 9. Naming consistency
    # ------------------------------------------------------------------

    def _check_naming_consistency(
        self,
        files: list[IndexedFile],
        parsed: dict[str, ParsedFile],
        issues: list[RefactorIssue],
    ) -> None:
        for f in files:
            pf = parsed.get(f.relative_path)
            if pf is None:
                continue
            for func in self._all_functions(pf):
                if func.is_method and func.name.startswith("__"):
                    continue
                if not _SNAKE_RE.match(func.name) and not func.name.startswith("_"):
                    issues.append(RefactorIssue(
                        category=RefactorCategory.NAMING_CONSISTENCY,
                        severity=RefactorSeverity.LOW,
                        title=f"Non-snake_case function: {func.name}",
                        detail=f"Function '{func.name}' in {f.relative_path} uses non-standard naming",
                        file=f.relative_path,
                        symbol=func.name,
                        line=func.start_line,
                    ))
            for cls in pf.module.classes:
                if not _PASCAL_RE.match(cls.name):
                    issues.append(RefactorIssue(
                        category=RefactorCategory.NAMING_CONSISTENCY,
                        severity=RefactorSeverity.LOW,
                        title=f"Non-PascalCase class: {cls.name}",
                        detail=f"Class '{cls.name}' in {f.relative_path} uses non-standard naming",
                        file=f.relative_path,
                        symbol=cls.name,
                        line=cls.start_line,
                    ))

    # ------------------------------------------------------------------
    # 10. Documentation drift
    # ------------------------------------------------------------------

    def _check_documentation_drift(
        self,
        issues: list[RefactorIssue],
        target_file: str | None,
    ) -> None:
        try:
            gaps = self._docs.find_missing_docstrings()
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("Doc drift detection skipped: {}", exc)
            return

        for gap in gaps:
            if target_file and not self._path_matches(gap.path, target_file):
                continue
            if self._skip_doc_check(gap.path):
                continue
            issues.append(RefactorIssue(
                category=RefactorCategory.DOCUMENTATION_DRIFT,
                severity=RefactorSeverity.LOW,
                title=f"Missing documentation: {gap.symbol or gap.path}",
                detail=gap.reason or f"Public API lacks docstring in {gap.path}",
                file=gap.path,
                symbol=gap.symbol or "",
            ))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_files(index: RepositoryIndex, target: str | None) -> list[IndexedFile]:
        if not target:
            return list(index.files)
        norm = target.replace("\\", "/").lstrip("./")
        return [
            f for f in index.files
            if f.relative_path == norm
            or f.relative_path.endswith("/" + norm)
            or Path(f.relative_path).name == norm
        ]

    @staticmethod
    def _all_functions(pf: ParsedFile) -> list[ParsedFunction]:
        result: list[ParsedFunction] = list(pf.module.functions)
        for cls in pf.module.classes:
            result.extend(cls.methods)
        for func in pf.module.functions:
            result.extend(func.nested_functions)
        return result

    @staticmethod
    def _function_signature(func: ParsedFunction) -> str:
        """Lightweight structural fingerprint: param count + return type + line count."""
        length = func.end_line - func.start_line + 1
        if length < 5:
            return ""
        n_params = len(func.parameters)
        ret = func.return_type or "None"
        bucket = length // 10
        return f"{n_params}:{ret}:{bucket}"

    @staticmethod
    def _collect_used_names(pf: ParsedFile) -> set[str]:
        """Collect all symbol names used in functions, classes, and variables."""
        names: set[str] = set()
        for func in pf.module.functions:
            names.add(func.name)
            for p in func.parameters:
                if p.type_hint:
                    names.update(re.findall(r"[A-Za-z_]\w*", p.type_hint))
            if func.return_type:
                names.update(re.findall(r"[A-Za-z_]\w*", func.return_type))
            for nested in func.nested_functions:
                names.add(nested.name)
        for cls in pf.module.classes:
            names.add(cls.name)
            names.update(cls.bases)
            for m in cls.methods:
                names.add(m.name)
                for p in m.parameters:
                    if p.type_hint:
                        names.update(re.findall(r"[A-Za-z_]\w*", p.type_hint))
                if m.return_type:
                    names.update(re.findall(r"[A-Za-z_]\w*", m.return_type))
        for var in pf.module.variables:
            names.add(var.name)
            if var.type_hint:
                names.update(re.findall(r"[A-Za-z_]\w*", var.type_hint))
        for ref in pf.module.references:
            if ref.symbol:
                names.add(ref.symbol)
            if ref.target_module:
                names.add(ref.target_module.rsplit(".", 1)[-1])
        for comment in pf.module.comments:
            pass  # comments don't count as usage
        if pf.module.docstring:
            names.update(re.findall(r"[A-Za-z_]\w*", pf.module.docstring))
        for func in pf.module.functions:
            if func.docstring:
                names.update(re.findall(r"[A-Za-z_]\w*", func.docstring))
        for cls in pf.module.classes:
            if cls.docstring:
                names.update(re.findall(r"[A-Za-z_]\w*", cls.docstring))
            for m in cls.methods:
                if m.docstring:
                    names.update(re.findall(r"[A-Za-z_]\w*", m.docstring))
        return names

    @staticmethod
    def _class_fan_out(cls: ParsedClass) -> int:
        """Heuristic fan-out: unique type hints and base classes."""
        types: set[str] = set(cls.bases)
        for m in cls.methods:
            for p in m.parameters:
                if p.type_hint and p.name != "self":
                    types.update(re.findall(r"[A-Z][a-zA-Z0-9]*", p.type_hint))
            if m.return_type:
                types.update(re.findall(r"[A-Z][a-zA-Z0-9]*", m.return_type))
        return len(types)

    @staticmethod
    def _infer_layer(path: str) -> int | None:
        parts = [p.lower() for p in Path(path).parts]
        stem = Path(path).stem.lower()
        for token, layer in _LAYER_KEYWORDS.items():
            if token in parts or token == stem:
                return layer
        return None

    @staticmethod
    def _layer_name(layer: int) -> str:
        return {
            0: "utility", 1: "domain/model", 2: "service/core",
            3: "data/repository", 4: "api/controller", 5: "view/ui",
            6: "cli",
        }.get(layer, f"layer-{layer}")

    @staticmethod
    def _resolve_import_path(module: str, index: RepositoryIndex) -> str | None:
        mod_parts = module.replace(".", "/")
        for f in index.files:
            if f.module_name == module:
                return f.relative_path
            if f.relative_path.replace("\\", "/").replace("/", ".").removesuffix(".py") == module:
                return f.relative_path
        return None

    @staticmethod
    def _skip_doc_check(path: str) -> bool:
        """Skip documentation checks for tests, fixtures, generated files, __init__.py."""
        fp = path.replace("\\", "/")
        parts = [p.lower() for p in Path(fp).parts]
        stem = Path(fp).stem.lower()
        name = Path(fp).name.lower()

        if name == "__init__.py":
            return True
        if name == "conftest.py":
            return True
        if any(t in parts for t in ("tests", "test", "spec", "specs", "fixtures")):
            return True
        if stem.startswith("test_") or stem.endswith("_test"):
            return True
        if stem.endswith("_generated") or "generated" in parts:
            return True
        return False

    @staticmethod
    def _is_pytest_test(dc: DeadCodeCandidate) -> bool:
        """Return True if the candidate is a pytest-discoverable test."""
        fp = (dc.file_path or "").replace("\\", "/")
        parts = [p.lower() for p in Path(fp).parts]
        stem = Path(fp).stem.lower()
        is_test_file = (
            any(t in parts for t in ("tests", "test", "spec"))
            or stem.startswith("test_")
            or stem.endswith("_test")
        )
        is_test_func = dc.name.startswith("test_") or dc.name.startswith("Test")
        return is_test_file or is_test_func

    @staticmethod
    def _path_matches(path: str, target: str) -> bool:
        norm_path = path.replace("\\", "/")
        norm_target = target.replace("\\", "/").lstrip("./")
        return (
            norm_path == norm_target
            or norm_path.endswith("/" + norm_target)
            or Path(norm_path).name == norm_target
        )
