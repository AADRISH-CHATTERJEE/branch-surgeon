"""Tests for RefactoringAnalyzer — all 10 analyzers, edge cases, false-positive guards."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from refactory.core.logger import get_service_logger
from refactory.documentation.models import DocGap, DocTargetKind
from refactory.documentation.service import DocumentationService
from refactory.graph.models import DeadCodeCandidate, DependencyCycle, NodeKind
from refactory.graph.service import RepositoryGraphService
from refactory.indexer.models import ImportReference, IndexedFile, IndexedSymbol, RepositoryIndex, RepositoryStatistics, RepositorySummary
from refactory.indexer.service import IndexerService
from refactory.parser.models import (
    FileMetadata,
    ParsedClass,
    ParsedFile,
    ParsedFunction,
    ParsedImport,
    ParsedModule,
    ParsedParameter,
    ParsedReference,
    ParsedVariable,
)
from refactory.parser.service import ParserService
from refactory.refactor.analyzer import RefactoringAnalyzer
from refactory.refactor.models import RefactorCategory, RefactorSeverity

from datetime import datetime


def _logger():
    return get_service_logger("test.refactor")


def _make_index(files: list[IndexedFile] | None = None) -> RepositoryIndex:
    return RepositoryIndex(
        summary=RepositorySummary(
            repository_root="/repo",
            repository_name="test",
            timestamp=datetime(2025, 1, 1),
        ),
        statistics=RepositoryStatistics(),
        files=files or [],
    )


def _make_indexed_file(
    path: str = "mod.py",
    functions: list[str] | None = None,
    classes: list[str] | None = None,
    nested: list[str] | None = None,
    imports: list[str] | None = None,
    import_refs: list[ImportReference] | None = None,
    file_size: int = 0,
) -> IndexedFile:
    return IndexedFile(
        relative_path=path,
        language="python",
        content_hash="abc",
        module_name=path.removesuffix(".py").replace("/", "."),
        functions=functions or [],
        classes=classes or [],
        nested_functions=nested or [],
        imports=imports or [],
        import_references=import_refs or [],
        file_size=file_size,
    )


def _make_parsed_file(
    path: str = "mod.py",
    line_count: int = 50,
    functions: list[ParsedFunction] | None = None,
    classes: list[ParsedClass] | None = None,
    imports: list[ParsedImport] | None = None,
    variables: list[ParsedVariable] | None = None,
    references: list[ParsedReference] | None = None,
) -> ParsedFile:
    return ParsedFile(
        metadata=FileMetadata(path=path, language="python", line_count=line_count),
        module=ParsedModule(
            name=path.removesuffix(".py"),
            functions=functions or [],
            classes=classes or [],
            imports=imports or [],
            variables=variables or [],
            references=references or [],
        ),
    )


def _func(name: str, start: int = 1, end: int = 10, params: list[str] | None = None,
          return_type: str | None = None, is_method: bool = False,
          parent_class: str | None = None, nested: list[ParsedFunction] | None = None) -> ParsedFunction:
    return ParsedFunction(
        name=name,
        start_line=start,
        end_line=end,
        parameters=[ParsedParameter(name=p) for p in (params or [])],
        return_type=return_type,
        is_method=is_method,
        parent_class=parent_class,
        nested_functions=nested or [],
    )


def _cls(name: str, methods: list[ParsedFunction] | None = None,
         properties: list[str] | None = None, bases: list[str] | None = None,
         start: int = 1, end: int = 50) -> ParsedClass:
    return ParsedClass(
        name=name,
        start_line=start,
        end_line=end,
        methods=methods or [],
        properties=properties or [],
        bases=bases or [],
    )


def _import(module: str, names: list[str] | None = None, alias: str | None = None,
            is_from: bool = True) -> ParsedImport:
    return ParsedImport(
        module=module,
        names=names or [],
        alias=alias,
        is_from_import=is_from,
        start_line=1,
        end_line=1,
    )


def _build_analyzer(**overrides) -> RefactoringAnalyzer:
    parser = MagicMock(spec=ParserService)
    indexer = MagicMock(spec=IndexerService)
    graph = MagicMock(spec=RepositoryGraphService)
    docs = MagicMock(spec=DocumentationService)
    graph.dead_code_candidates.return_value = []
    graph.find_cycles.return_value = []
    docs.find_missing_docstrings.return_value = []
    defaults = dict(
        logger=_logger(),
        parser_service=parser,
        indexer_service=indexer,
        graph_service=graph,
        documentation_service=docs,
    )
    defaults.update(overrides)
    return RefactoringAnalyzer(**defaults)


class TestLargeFileDetector:
    def test_file_below_threshold_no_issue(self):
        analyzer = _build_analyzer(large_file_lines=300)
        idx = _make_index([_make_indexed_file("small.py")])
        parsed = {"small.py": _make_parsed_file("small.py", line_count=100)}
        issues = analyzer.analyze_all(idx, parsed)
        assert not any(i.category == RefactorCategory.LARGE_FILE for i in issues)

    def test_file_above_threshold(self):
        analyzer = _build_analyzer(large_file_lines=100)
        idx = _make_index([_make_indexed_file("big.py")])
        parsed = {"big.py": _make_parsed_file("big.py", line_count=200)}
        issues = analyzer.analyze_all(idx, parsed)
        large = [i for i in issues if i.category == RefactorCategory.LARGE_FILE]
        assert len(large) == 1
        assert large[0].severity == RefactorSeverity.MEDIUM

    def test_very_large_file_high_severity(self):
        analyzer = _build_analyzer(large_file_lines=100)
        idx = _make_index([_make_indexed_file("huge.py")])
        parsed = {"huge.py": _make_parsed_file("huge.py", line_count=250)}
        issues = analyzer.analyze_all(idx, parsed)
        large = [i for i in issues if i.category == RefactorCategory.LARGE_FILE]
        assert large[0].severity == RefactorSeverity.HIGH

    def test_too_many_functions(self):
        fns = [f"fn_{i}" for i in range(20)]
        analyzer = _build_analyzer(large_file_functions=15)
        idx = _make_index([_make_indexed_file("many_fns.py", functions=fns)])
        parsed = {"many_fns.py": _make_parsed_file("many_fns.py", line_count=50)}
        issues = analyzer.analyze_all(idx, parsed)
        large = [i for i in issues if i.category == RefactorCategory.LARGE_FILE]
        assert len(large) == 1

    def test_too_many_classes(self):
        classes = [f"Cls{i}" for i in range(8)]
        analyzer = _build_analyzer(large_file_classes=5)
        idx = _make_index([_make_indexed_file("many_cls.py", classes=classes)])
        parsed = {"many_cls.py": _make_parsed_file("many_cls.py", line_count=50)}
        issues = analyzer.analyze_all(idx, parsed)
        large = [i for i in issues if i.category == RefactorCategory.LARGE_FILE]
        assert len(large) == 1

    def test_no_parsed_file_uses_size_estimate(self):
        analyzer = _build_analyzer(large_file_lines=100)
        idx = _make_index([_make_indexed_file("noparse.py", file_size=8000)])
        issues = analyzer.analyze_all(idx, {})
        large = [i for i in issues if i.category == RefactorCategory.LARGE_FILE]
        assert len(large) == 1


class TestLongFunctionDetector:
    def test_short_function_no_issue(self):
        analyzer = _build_analyzer(long_function_lines=50)
        idx = _make_index([_make_indexed_file("mod.py")])
        parsed = {"mod.py": _make_parsed_file("mod.py", functions=[_func("short", 1, 20)])}
        issues = analyzer.analyze_all(idx, parsed)
        assert not any(i.category == RefactorCategory.LONG_FUNCTION for i in issues)

    def test_long_function_detected(self):
        analyzer = _build_analyzer(long_function_lines=50)
        idx = _make_index([_make_indexed_file("mod.py")])
        parsed = {"mod.py": _make_parsed_file("mod.py", functions=[_func("big", 1, 80)])}
        issues = analyzer.analyze_all(idx, parsed)
        long = [i for i in issues if i.category == RefactorCategory.LONG_FUNCTION]
        assert len(long) == 1
        assert long[0].symbol == "big"

    def test_very_long_function_high_severity(self):
        analyzer = _build_analyzer(long_function_lines=50)
        idx = _make_index([_make_indexed_file("mod.py")])
        parsed = {"mod.py": _make_parsed_file("mod.py", functions=[_func("huge", 1, 150)])}
        issues = analyzer.analyze_all(idx, parsed)
        long = [i for i in issues if i.category == RefactorCategory.LONG_FUNCTION]
        assert long[0].severity == RefactorSeverity.HIGH

    def test_method_in_class_detected(self):
        analyzer = _build_analyzer(long_function_lines=10)
        cls = _cls("Foo", methods=[_func("long_method", 5, 60, is_method=True)])
        idx = _make_index([_make_indexed_file("mod.py")])
        parsed = {"mod.py": _make_parsed_file("mod.py", classes=[cls])}
        issues = analyzer.analyze_all(idx, parsed)
        long = [i for i in issues if i.category == RefactorCategory.LONG_FUNCTION]
        assert any(i.symbol == "long_method" for i in long)


class TestDuplicateLogicDetector:
    def test_no_duplicates_for_unique_functions(self):
        analyzer = _build_analyzer()
        f1 = _func("a", 1, 20, params=["x"], return_type="int")
        f2 = _func("b", 1, 20, params=["x", "y"], return_type="str")
        idx = _make_index([_make_indexed_file("m.py")])
        parsed = {"m.py": _make_parsed_file("m.py", functions=[f1, f2])}
        issues = analyzer.analyze_all(idx, parsed)
        assert not any(i.category == RefactorCategory.DUPLICATE_LOGIC for i in issues)

    def test_duplicates_detected_same_file(self):
        analyzer = _build_analyzer()
        f1 = _func("validate_a", 1, 20, params=["x"], return_type="bool")
        f2 = _func("validate_b", 30, 49, params=["y"], return_type="bool")
        idx = _make_index([_make_indexed_file("m.py")])
        parsed = {"m.py": _make_parsed_file("m.py", functions=[f1, f2])}
        issues = analyzer.analyze_all(idx, parsed)
        dupes = [i for i in issues if i.category == RefactorCategory.DUPLICATE_LOGIC]
        assert len(dupes) == 1

    def test_duplicates_across_files(self):
        analyzer = _build_analyzer()
        f1 = _func("do_work", 1, 20, params=["data"], return_type="list")
        f2 = _func("do_thing", 1, 20, params=["data"], return_type="list")
        idx = _make_index([_make_indexed_file("a.py"), _make_indexed_file("b.py")])
        parsed = {
            "a.py": _make_parsed_file("a.py", functions=[f1]),
            "b.py": _make_parsed_file("b.py", functions=[f2]),
        }
        issues = analyzer.analyze_all(idx, parsed)
        dupes = [i for i in issues if i.category == RefactorCategory.DUPLICATE_LOGIC]
        assert len(dupes) == 1

    def test_tiny_functions_not_flagged(self):
        analyzer = _build_analyzer()
        f1 = _func("get_a", 1, 3, return_type="int")
        f2 = _func("get_b", 1, 3, return_type="int")
        idx = _make_index([_make_indexed_file("m.py")])
        parsed = {"m.py": _make_parsed_file("m.py", functions=[f1, f2])}
        issues = analyzer.analyze_all(idx, parsed)
        assert not any(i.category == RefactorCategory.DUPLICATE_LOGIC for i in issues)


class TestDeadCodeDetector:
    def test_dead_code_from_graph(self):
        graph = MagicMock(spec=RepositoryGraphService)
        graph.dead_code_candidates.return_value = [
            DeadCodeCandidate(name="_helper", kind=NodeKind.FUNCTION, file_path="utils.py", reason="private, no refs"),
        ]
        graph.find_cycles.return_value = []
        docs = MagicMock(spec=DocumentationService)
        docs.find_missing_docstrings.return_value = []
        analyzer = _build_analyzer(graph_service=graph, documentation_service=docs)
        idx = _make_index([_make_indexed_file("utils.py")])
        parsed = {"utils.py": _make_parsed_file("utils.py")}
        issues = analyzer.analyze_all(idx, parsed)
        dead = [i for i in issues if i.category == RefactorCategory.DEAD_CODE]
        assert len(dead) == 1
        assert dead[0].symbol == "_helper"

    def test_dead_code_graph_error_graceful(self):
        graph = MagicMock(spec=RepositoryGraphService)
        graph.dead_code_candidates.side_effect = RuntimeError("no graph")
        graph.find_cycles.return_value = []
        docs = MagicMock(spec=DocumentationService)
        docs.find_missing_docstrings.return_value = []
        analyzer = _build_analyzer(graph_service=graph, documentation_service=docs)
        idx = _make_index([_make_indexed_file("mod.py")])
        parsed = {"mod.py": _make_parsed_file("mod.py")}
        issues = analyzer.analyze_all(idx, parsed)
        assert not any(i.category == RefactorCategory.DEAD_CODE for i in issues)

    def test_dead_code_file_filter(self):
        graph = MagicMock(spec=RepositoryGraphService)
        graph.dead_code_candidates.return_value = [
            DeadCodeCandidate(name="_a", kind=NodeKind.FUNCTION, file_path="a.py", reason="no refs"),
            DeadCodeCandidate(name="_b", kind=NodeKind.FUNCTION, file_path="b.py", reason="no refs"),
        ]
        graph.find_cycles.return_value = []
        docs = MagicMock(spec=DocumentationService)
        docs.find_missing_docstrings.return_value = []
        analyzer = _build_analyzer(graph_service=graph, documentation_service=docs)
        idx = _make_index([_make_indexed_file("a.py"), _make_indexed_file("b.py")])
        parsed = {
            "a.py": _make_parsed_file("a.py"),
            "b.py": _make_parsed_file("b.py"),
        }
        issues = analyzer.analyze_all(idx, parsed, target_file="a.py")
        dead = [i for i in issues if i.category == RefactorCategory.DEAD_CODE]
        assert len(dead) == 1
        assert dead[0].file == "a.py"


class TestUnusedImports:
    def test_used_import_no_issue(self):
        analyzer = _build_analyzer()
        imp = _import("os", names=["path"])
        func = _func("foo", params=["p"], return_type="path")
        idx = _make_index([_make_indexed_file("m.py")])
        parsed = {"m.py": _make_parsed_file("m.py", functions=[func], imports=[imp])}
        issues = analyzer.analyze_all(idx, parsed)
        assert not any(i.category == RefactorCategory.UNUSED_IMPORT for i in issues)

    def test_unused_import_detected(self):
        analyzer = _build_analyzer()
        imp = _import("os", names=["getcwd"])
        idx = _make_index([_make_indexed_file("m.py")])
        parsed = {"m.py": _make_parsed_file("m.py", imports=[imp])}
        issues = analyzer.analyze_all(idx, parsed)
        unused = [i for i in issues if i.category == RefactorCategory.UNUSED_IMPORT]
        assert len(unused) == 1
        assert unused[0].symbol == "getcwd"

    def test_star_import_not_flagged(self):
        analyzer = _build_analyzer()
        imp = _import("os", names=["*"])
        idx = _make_index([_make_indexed_file("m.py")])
        parsed = {"m.py": _make_parsed_file("m.py", imports=[imp])}
        issues = analyzer.analyze_all(idx, parsed)
        assert not any(i.category == RefactorCategory.UNUSED_IMPORT for i in issues)

    def test_plain_import_unused(self):
        analyzer = _build_analyzer()
        imp = _import("json", names=[], is_from=False)
        idx = _make_index([_make_indexed_file("m.py")])
        parsed = {"m.py": _make_parsed_file("m.py", imports=[imp])}
        issues = analyzer.analyze_all(idx, parsed)
        unused = [i for i in issues if i.category == RefactorCategory.UNUSED_IMPORT]
        assert len(unused) == 1

    def test_aliased_import_used(self):
        analyzer = _build_analyzer()
        imp = _import("numpy", names=[], alias="np", is_from=False)
        var = ParsedVariable(name="np", start_line=2, end_line=2)
        idx = _make_index([_make_indexed_file("m.py")])
        parsed = {"m.py": _make_parsed_file("m.py", imports=[imp], variables=[var])}
        issues = analyzer.analyze_all(idx, parsed)
        assert not any(
            i.category == RefactorCategory.UNUSED_IMPORT and i.symbol == "numpy"
            for i in issues
        )


class TestCircularDependencyDetector:
    def test_cycle_detected(self):
        graph = MagicMock(spec=RepositoryGraphService)
        graph.find_cycles.return_value = [
            DependencyCycle(files=["a.py", "b.py"]),
        ]
        graph.dead_code_candidates.return_value = []
        docs = MagicMock(spec=DocumentationService)
        docs.find_missing_docstrings.return_value = []
        analyzer = _build_analyzer(graph_service=graph, documentation_service=docs)
        idx = _make_index([_make_indexed_file("a.py"), _make_indexed_file("b.py")])
        parsed = {
            "a.py": _make_parsed_file("a.py"),
            "b.py": _make_parsed_file("b.py"),
        }
        issues = analyzer.analyze_all(idx, parsed)
        cycles = [i for i in issues if i.category == RefactorCategory.CIRCULAR_DEPENDENCY]
        assert len(cycles) == 1

    def test_large_cycle_high_severity(self):
        graph = MagicMock(spec=RepositoryGraphService)
        graph.find_cycles.return_value = [
            DependencyCycle(files=["a.py", "b.py", "c.py"]),
        ]
        graph.dead_code_candidates.return_value = []
        docs = MagicMock(spec=DocumentationService)
        docs.find_missing_docstrings.return_value = []
        analyzer = _build_analyzer(graph_service=graph, documentation_service=docs)
        idx = _make_index()
        issues = analyzer.analyze_all(idx, {})
        cycles = [i for i in issues if i.category == RefactorCategory.CIRCULAR_DEPENDENCY]
        assert cycles[0].severity == RefactorSeverity.HIGH

    def test_cycle_detection_error_graceful(self):
        graph = MagicMock(spec=RepositoryGraphService)
        graph.find_cycles.side_effect = RuntimeError("boom")
        graph.dead_code_candidates.return_value = []
        docs = MagicMock(spec=DocumentationService)
        docs.find_missing_docstrings.return_value = []
        analyzer = _build_analyzer(graph_service=graph, documentation_service=docs)
        idx = _make_index()
        issues = analyzer.analyze_all(idx, {})
        assert not any(i.category == RefactorCategory.CIRCULAR_DEPENDENCY for i in issues)


class TestGodClassDetector:
    def test_small_class_no_issue(self):
        analyzer = _build_analyzer(god_class_methods=10)
        cls = _cls("Small", methods=[_func(f"m{i}", is_method=True) for i in range(3)])
        idx = _make_index([_make_indexed_file("m.py")])
        parsed = {"m.py": _make_parsed_file("m.py", classes=[cls])}
        issues = analyzer.analyze_all(idx, parsed)
        assert not any(i.category == RefactorCategory.GOD_CLASS for i in issues)

    def test_god_class_detected(self):
        analyzer = _build_analyzer(god_class_methods=5)
        methods = [_func(f"m{i}", is_method=True) for i in range(8)]
        cls = _cls("BigClass", methods=methods)
        idx = _make_index([_make_indexed_file("m.py")])
        parsed = {"m.py": _make_parsed_file("m.py", classes=[cls])}
        issues = analyzer.analyze_all(idx, parsed)
        gods = [i for i in issues if i.category == RefactorCategory.GOD_CLASS]
        assert len(gods) == 1
        assert gods[0].symbol == "BigClass"

    def test_very_large_god_class_high_severity(self):
        analyzer = _build_analyzer(god_class_methods=5)
        methods = [_func(f"m{i}", is_method=True) for i in range(12)]
        cls = _cls("Huge", methods=methods)
        idx = _make_index([_make_indexed_file("m.py")])
        parsed = {"m.py": _make_parsed_file("m.py", classes=[cls])}
        issues = analyzer.analyze_all(idx, parsed)
        gods = [i for i in issues if i.category == RefactorCategory.GOD_CLASS]
        assert gods[0].severity == RefactorSeverity.HIGH

    def test_high_fan_out_detected(self):
        analyzer = _build_analyzer(god_class_fan_out=3)
        methods = [
            _func("a", is_method=True, params=["self"],
                   return_type="Foo"),
            _func("b", is_method=True, params=["self"],
                   return_type="Bar"),
        ]
        methods[0].parameters.append(ParsedParameter(name="x", type_hint="Baz"))
        methods[1].parameters.append(ParsedParameter(name="y", type_hint="Qux"))
        cls = _cls("Wide", methods=methods, bases=["Base"])
        idx = _make_index([_make_indexed_file("m.py")])
        parsed = {"m.py": _make_parsed_file("m.py", classes=[cls])}
        issues = analyzer.analyze_all(idx, parsed)
        gods = [i for i in issues if i.category == RefactorCategory.GOD_CLASS]
        assert len(gods) >= 1


class TestLayerViolationDetector:
    def test_no_violation_same_layer(self):
        analyzer = _build_analyzer()
        f1 = _make_indexed_file("service/auth.py")
        f2 = _make_indexed_file("service/users.py")
        idx = _make_index([f1, f2])
        parsed = {
            "service/auth.py": _make_parsed_file("service/auth.py"),
            "service/users.py": _make_parsed_file("service/users.py"),
        }
        issues = analyzer.analyze_all(idx, parsed)
        assert not any(i.category == RefactorCategory.LAYER_VIOLATION for i in issues)

    def test_violation_model_imports_cli(self):
        ref = ImportReference(
            source_file="models/user.py",
            source_module="models.user",
            target_module="cli.commands",
            start_line=1,
        )
        f1 = _make_indexed_file("models/user.py", import_refs=[ref])
        f2 = _make_indexed_file("cli/commands.py")
        idx = _make_index([f1, f2])
        parsed = {
            "models/user.py": _make_parsed_file("models/user.py"),
            "cli/commands.py": _make_parsed_file("cli/commands.py"),
        }
        a = _build_analyzer()
        issues = a.analyze_all(idx, parsed)
        assert any(i.category == RefactorCategory.LAYER_VIOLATION for i in issues)


class TestNamingConsistency:
    def test_snake_case_function_ok(self):
        analyzer = _build_analyzer()
        idx = _make_index([_make_indexed_file("m.py")])
        parsed = {"m.py": _make_parsed_file("m.py", functions=[_func("do_work")])}
        issues = analyzer.analyze_all(idx, parsed)
        assert not any(i.category == RefactorCategory.NAMING_CONSISTENCY for i in issues)

    def test_camel_case_function_flagged(self):
        analyzer = _build_analyzer()
        idx = _make_index([_make_indexed_file("m.py")])
        parsed = {"m.py": _make_parsed_file("m.py", functions=[_func("doWork")])}
        issues = analyzer.analyze_all(idx, parsed)
        naming = [i for i in issues if i.category == RefactorCategory.NAMING_CONSISTENCY]
        assert any(i.symbol == "doWork" for i in naming)

    def test_pascal_case_class_ok(self):
        analyzer = _build_analyzer()
        idx = _make_index([_make_indexed_file("m.py")])
        parsed = {"m.py": _make_parsed_file("m.py", classes=[_cls("MyClass")])}
        issues = analyzer.analyze_all(idx, parsed)
        assert not any(
            i.category == RefactorCategory.NAMING_CONSISTENCY and i.symbol == "MyClass"
            for i in issues
        )

    def test_non_pascal_class_flagged(self):
        analyzer = _build_analyzer()
        idx = _make_index([_make_indexed_file("m.py")])
        parsed = {"m.py": _make_parsed_file("m.py", classes=[_cls("my_class")])}
        issues = analyzer.analyze_all(idx, parsed)
        naming = [i for i in issues if i.category == RefactorCategory.NAMING_CONSISTENCY]
        assert any(i.symbol == "my_class" for i in naming)

    def test_dunder_methods_not_flagged(self):
        analyzer = _build_analyzer()
        m = _func("__init__", is_method=True)
        cls = _cls("Foo", methods=[m])
        idx = _make_index([_make_indexed_file("m.py")])
        parsed = {"m.py": _make_parsed_file("m.py", classes=[cls])}
        issues = analyzer.analyze_all(idx, parsed)
        assert not any(
            i.category == RefactorCategory.NAMING_CONSISTENCY and i.symbol == "__init__"
            for i in issues
        )

    def test_private_function_underscore_ok(self):
        analyzer = _build_analyzer()
        idx = _make_index([_make_indexed_file("m.py")])
        parsed = {"m.py": _make_parsed_file("m.py", functions=[_func("_helper")])}
        issues = analyzer.analyze_all(idx, parsed)
        assert not any(
            i.category == RefactorCategory.NAMING_CONSISTENCY and i.symbol == "_helper"
            for i in issues
        )


class TestDocumentationDrift:
    def test_gap_detected(self):
        docs = MagicMock(spec=DocumentationService)
        docs.find_missing_docstrings.return_value = [
            DocGap(path="api.py", symbol="get_users", kind=DocTargetKind.FUNCTION, reason="missing docstring"),
        ]
        graph = MagicMock(spec=RepositoryGraphService)
        graph.dead_code_candidates.return_value = []
        graph.find_cycles.return_value = []
        analyzer = _build_analyzer(graph_service=graph, documentation_service=docs)
        idx = _make_index([_make_indexed_file("api.py")])
        parsed = {"api.py": _make_parsed_file("api.py")}
        issues = analyzer.analyze_all(idx, parsed)
        doc_issues = [i for i in issues if i.category == RefactorCategory.DOCUMENTATION_DRIFT]
        assert len(doc_issues) == 1

    def test_doc_drift_error_graceful(self):
        docs = MagicMock(spec=DocumentationService)
        docs.find_missing_docstrings.side_effect = RuntimeError("no index")
        graph = MagicMock(spec=RepositoryGraphService)
        graph.dead_code_candidates.return_value = []
        graph.find_cycles.return_value = []
        analyzer = _build_analyzer(graph_service=graph, documentation_service=docs)
        idx = _make_index()
        issues = analyzer.analyze_all(idx, {})
        assert not any(i.category == RefactorCategory.DOCUMENTATION_DRIFT for i in issues)


class TestTargetFileFiltering:
    def test_file_filter_limits_scope(self):
        analyzer = _build_analyzer(large_file_lines=50)
        idx = _make_index([
            _make_indexed_file("a.py"),
            _make_indexed_file("b.py"),
        ])
        parsed = {
            "a.py": _make_parsed_file("a.py", line_count=200),
            "b.py": _make_parsed_file("b.py", line_count=200),
        }
        issues = analyzer.analyze_all(idx, parsed, target_file="a.py")
        files = {i.file for i in issues if i.category == RefactorCategory.LARGE_FILE}
        assert "a.py" in files
        assert "b.py" not in files

    def test_filter_by_basename(self):
        analyzer = _build_analyzer(large_file_lines=50)
        idx = _make_index([_make_indexed_file("some/path/auth.py")])
        parsed = {"some/path/auth.py": _make_parsed_file("some/path/auth.py", line_count=200)}
        issues = analyzer.analyze_all(idx, parsed, target_file="auth.py")
        assert any(i.category == RefactorCategory.LARGE_FILE for i in issues)


class TestEmptyRepository:
    def test_no_files_no_issues(self):
        analyzer = _build_analyzer()
        idx = _make_index([])
        issues = analyzer.analyze_all(idx, {})
        assert issues == []

    def test_all_unparsed_files(self):
        analyzer = _build_analyzer()
        idx = _make_index([_make_indexed_file("a.py")])
        issues = analyzer.analyze_all(idx, {})
        large = [i for i in issues if i.category == RefactorCategory.LARGE_FILE]
        assert not large


class TestIssueOrdering:
    def test_issues_sorted_by_severity(self):
        analyzer = _build_analyzer(large_file_lines=50, long_function_lines=10)
        idx = _make_index([_make_indexed_file("m.py")])
        parsed = {"m.py": _make_parsed_file(
            "m.py",
            line_count=200,
            functions=[_func("long", 1, 30)],
        )}
        issues = analyzer.analyze_all(idx, parsed)
        if len(issues) >= 2:
            severities = [
                {"critical": 0, "high": 1, "medium": 2, "low": 3}[i.severity.value]
                for i in issues
            ]
            assert severities == sorted(severities)
