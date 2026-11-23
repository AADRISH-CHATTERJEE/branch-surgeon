"""Graph analysis: cycles, orphans, unused symbols, inheritance."""

from __future__ import annotations

from datetime import datetime, timezone

from refactory.core.logger import get_service_logger
from refactory.graph.models import RelationshipType
from refactory.graph.service import RepositoryGraphService
from refactory.indexer.models import (
    ImportReference,
    IndexedFile,
    IndexedSymbol,
    RepositoryIndex,
    RepositoryStatistics,
    RepositorySummary,
    SymbolKind,
)


def _stem(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".py")


def _file(
    path: str,
    *,
    symbols: list[IndexedSymbol] | None = None,
    imports: list[ImportReference] | None = None,
) -> IndexedFile:
    return IndexedFile(
        relative_path=path,
        language="python",
        content_hash=f"hash-{path}",
        module_name=_stem(path),
        symbols=symbols or [],
        import_references=imports or [],
    )


def _index(files: list[IndexedFile]) -> RepositoryIndex:
    symbols: list[IndexedSymbol] = []
    refs: list[ImportReference] = []
    for f in files:
        symbols.extend(f.symbols)
        refs.extend(f.import_references)
    return RepositoryIndex(
        summary=RepositorySummary(
            repository_root="/tmp/demo",
            repository_name="demo",
            total_indexed_files=len(files),
            timestamp=datetime(2026, 7, 23, tzinfo=timezone.utc),
        ),
        statistics=RepositoryStatistics(),
        files=files,
        symbols=symbols,
        import_references=refs,
        file_hashes={f.relative_path: f.content_hash for f in files},
    )


def test_inheritance_cycles_orphans_unused():
    base = _file(
        "pkg/base.py",
        symbols=[
            IndexedSymbol(
                name="Base",
                kind=SymbolKind.CLASS,
                file_path="pkg/base.py",
                start_line=1,
                end_line=3,
            )
        ],
    )
    child = _file(
        "pkg/child.py",
        symbols=[
            IndexedSymbol(
                name="Child",
                kind=SymbolKind.CLASS,
                file_path="pkg/child.py",
                start_line=1,
                end_line=4,
                bases=["Base"],
            ),
            IndexedSymbol(
                name="unused_helper",
                kind=SymbolKind.FUNCTION,
                file_path="pkg/child.py",
                start_line=6,
                end_line=8,
            ),
        ],
        imports=[
            ImportReference(
                source_file="pkg/child.py",
                source_module="child",
                target_module="base",
                symbol="Base",
                kind="import",
            )
        ],
    )
    a = _file(
        "a.py",
        symbols=[
            IndexedSymbol(
                name="fa",
                kind=SymbolKind.FUNCTION,
                file_path="a.py",
                start_line=1,
                end_line=2,
            )
        ],
        imports=[
            ImportReference(
                source_file="a.py",
                source_module="a",
                target_module="b",
                kind="import",
            )
        ],
    )
    b = _file(
        "b.py",
        symbols=[
            IndexedSymbol(
                name="fb",
                kind=SymbolKind.FUNCTION,
                file_path="b.py",
                start_line=1,
                end_line=2,
            )
        ],
        imports=[
            ImportReference(
                source_file="b.py",
                source_module="b",
                target_module="a",
                kind="import",
            )
        ],
    )
    orphan = _file(
        "lonely.py",
        symbols=[
            IndexedSymbol(
                name="Lonely",
                kind=SymbolKind.CLASS,
                file_path="lonely.py",
                start_line=1,
                end_line=2,
            )
        ],
    )

    svc = RepositoryGraphService(logger=get_service_logger("test.graph"))
    graph = svc.build_graph(_index([base, child, a, b, orphan]))

    assert any(e.relationship == RelationshipType.INHERITS_FROM for e in graph.edges)
    assert svc.base_classes_of("Child") == ["Base"]
    assert "Child" in svc.subclasses_of("Base")
    assert graph.statistics.inheritance_edges >= 1
    assert graph.statistics.hierarchy_edges >= 1

    cycles = svc.find_cycles()
    assert any(set(c.files) >= {"a.py", "b.py"} for c in cycles)

    orphans = {o.file_path for o in svc.orphan_modules()}
    assert "lonely.py" in orphans

    unused_names = {u.name for u in svc.unused_symbols()}
    assert "unused_helper" in unused_names
    assert graph.statistics.cyclic_dependency_count >= 1
    assert graph.statistics.orphan_module_count >= 1
