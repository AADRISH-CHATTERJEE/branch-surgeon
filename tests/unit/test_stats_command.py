"""Tests for the refactory stats command."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from refactory.cli.commands.stats import _collect_stats, _render
from refactory.indexer.models import (
    ImportReference,
    IndexedFile,
    RepositoryIndex,
    RepositoryStatistics,
    RepositorySummary,
)

_NOW = datetime.now(timezone.utc)


def _make_index(files: list[IndexedFile]) -> RepositoryIndex:
    return RepositoryIndex(
        summary=RepositorySummary(
            repository_name="test",
            repository_root="/tmp/test",
            total_indexed_files=len(files),
            timestamp=_NOW,
        ),
        statistics=RepositoryStatistics(),
        files=files,
        file_hashes={f.relative_path: f.content_hash for f in files},
    )


def _make_file(
    path: str,
    language: str = "python",
    classes: int = 0,
    functions: int = 1,
    imports: int = 2,
) -> IndexedFile:
    cls_list = [f"Class{i}" for i in range(classes)]
    fn_list = [f"func{i}" for i in range(functions)]
    imp_list = [
        ImportReference(
            source_file=path,
            source_module=path.removesuffix(".py"),
            target_module=f"mod{i}",
            symbol=f"sym{i}",
        )
        for i in range(imports)
    ]
    return IndexedFile(
        relative_path=path,
        language=language,
        file_size=2500,
        content_hash=f"hash_{path}",
        module_name=path.replace("/", ".").removesuffix(".py"),
        classes=cls_list,
        functions=fn_list,
        import_references=imp_list,
    )


class TestCollectStats:
    def test_basic_stats(self):
        files = [
            _make_file("app.py", classes=2, functions=5),
            _make_file("utils.py", functions=3),
        ]
        stats = _collect_stats(_make_index(files))
        assert stats["total_files"] == 2
        assert stats["total_classes"] == 2
        assert stats["total_functions"] == 8

    def test_languages_counted(self):
        files = [
            _make_file("a.py", language="python"),
            _make_file("b.py", language="python"),
            _make_file("c.js", language="javascript"),
        ]
        stats = _collect_stats(_make_index(files))
        langs = stats["languages"]
        assert langs["python"] == 2
        assert langs["javascript"] == 1

    def test_test_files_detected(self):
        files = [
            _make_file("app.py"),
            _make_file("tests/test_app.py"),
            _make_file("test_utils.py"),
        ]
        stats = _collect_stats(_make_index(files))
        assert stats["test_files"] == 2
        assert stats["production_files"] == 1

    def test_empty_index(self):
        stats = _collect_stats(_make_index([]))
        assert stats["total_files"] == 0


class TestRender:
    def test_render_basic(self):
        stats = {
            "total_files": 10,
            "total_classes": 5,
            "total_functions": 20,
            "total_imports": 30,
            "test_files": 3,
            "production_files": 7,
            "languages": {"python": 10},
            "graph": {
                "total_nodes": 50,
                "total_edges": 80,
                "cyclic_dependencies": 1,
                "orphan_modules": 2,
                "unused_symbols": 5,
            },
        }
        _render(stats, 123.4)

    def test_render_without_graph(self):
        stats = {
            "total_files": 5,
            "total_classes": 1,
            "total_functions": 10,
            "total_imports": 15,
            "test_files": 1,
            "production_files": 4,
            "languages": {},
        }
        _render(stats, 50.0)
