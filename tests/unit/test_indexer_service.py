"""Unit tests for IndexerService (deterministic indexing, no embeddings)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from refactory.core.exceptions import ParserError
from refactory.core.logger import get_service_logger
from refactory.indexer.service import INDEX_FILENAME, IndexerService
from refactory.parser.models import (
    CommentTag,
    FileMetadata,
    ParsedClass,
    ParsedComment,
    ParsedFile,
    ParsedFunction,
    ParsedImport,
    ParsedModule,
    ParsedReference,
    ImportKind,
)
from refactory.parser.service import ParserService
from refactory.review.models import Repository


def _logger():
    return get_service_logger("test.indexer")


def _real_indexer(tmp_path: Path) -> IndexerService:
    parser = ParserService(
        ignore_dirs=[".git", "venv", ".venv", "node_modules", "__pycache__", ".refactory"],
        logger=get_service_logger("test.parser"),
    )
    return IndexerService(
        parser_service=parser,
        ignore_dirs=[".git", "venv", ".venv", "node_modules", "__pycache__", ".refactory"],
        logger=_logger(),
    )


def _write_tree(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "auth.py").write_text(
        '''\
"""Auth module."""
# TODO: harden tokens
from middleware import require_auth

def validate():
    return True

class AuthService:
    def login(self):
        def nested():
            return 1
        return nested()
''',
        encoding="utf-8",
    )
    (root / "src" / "util.py").write_text("def helper():\n    return 42\n", encoding="utf-8")
    (root / "readme.md").write_text("# docs\n", encoding="utf-8")
    (root / "venv" / "lib").mkdir(parents=True)
    (root / "venv" / "lib" / "site.py").write_text("x=1\n", encoding="utf-8")
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "node_modules" / "pkg" / "index.js").write_text("export default 1\n", encoding="utf-8")


def test_nested_directories_are_indexed(tmp_path: Path):
    _write_tree(tmp_path)
    index = _real_indexer(tmp_path).build_index(tmp_path, repository_name="demo-repo")
    paths = {f.relative_path.replace("\\", "/") for f in index.files if f.parse_error is None}
    assert "src/auth.py" in paths
    assert "src/util.py" in paths
    assert index.summary.total_indexed_files == 2
    assert index.statistics.files_parsed == 2
    assert index.statistics.newly_added_files == 2


def test_ignored_folders_skipped(tmp_path: Path):
    _write_tree(tmp_path)
    index = _real_indexer(tmp_path).build_index(tmp_path, repository_name="demo")
    paths = {f.relative_path.replace("\\", "/") for f in index.files}
    assert not any(p.startswith("venv/") for p in paths)
    assert not any(p.startswith("node_modules/") for p in paths)
    assert index.summary.ignored_file_count >= 2
    assert index.statistics.ignored_files == index.summary.ignored_file_count


def test_empty_repository(tmp_path: Path):
    index = _real_indexer(tmp_path).build_index(tmp_path, repository_name="empty")
    assert index.summary.total_indexed_files == 0
    assert index.summary.total_functions == 0
    assert index.files == []


def test_unsupported_file_types_ignored(tmp_path: Path):
    (tmp_path / "notes.md").write_text("# hi\n", encoding="utf-8")
    (tmp_path / "data.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    index = _real_indexer(tmp_path).build_index(tmp_path, repository_name="mixed")
    assert index.summary.total_indexed_files == 1
    assert index.statistics.unsupported_file_count >= 2


def test_syntax_errors_still_indexed(tmp_path: Path):
    (tmp_path / "broken.py").write_text("def broken(\n", encoding="utf-8")
    index = _real_indexer(tmp_path).build_index(tmp_path, repository_name="broken")
    assert index.summary.total_indexed_files == 1
    assert index.files[0].has_syntax_errors is True


def test_hash_calculation_and_persistence(tmp_path: Path):
    (tmp_path / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    service = _real_indexer(tmp_path)
    index = service.build_index(tmp_path, repository_name="hashdemo")
    assert len(index.files[0].content_hash) == 64
    assert index.file_hashes["a.py"] == index.files[0].content_hash

    persisted = tmp_path / ".refactory" / INDEX_FILENAME
    assert persisted.is_file()
    loaded = service.load_index(tmp_path)
    assert loaded is not None
    assert loaded.summary.repository_name == "hashdemo"


def test_incremental_reuse_when_hash_unchanged(tmp_path: Path):
    (tmp_path / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    service = _real_indexer(tmp_path)
    first = service.build_index(tmp_path, repository_name="inc")
    assert first.statistics.files_parsed == 1
    assert first.statistics.newly_added_files == 1
    assert first.statistics.reused_unchanged_files == 0

    second = service.build_index(tmp_path, repository_name="inc", force=False)
    assert second.summary.total_indexed_files == 1
    assert second.statistics.reused_unchanged_files == 1
    assert second.statistics.files_parsed == 0
    assert second.statistics.newly_added_files == 0
    assert second.statistics.modified_files == 0
    assert first.file_hashes == second.file_hashes


def test_modified_and_deleted_tracked_this_run(tmp_path: Path):
    (tmp_path / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def b():\n    return 1\n", encoding="utf-8")
    service = _real_indexer(tmp_path)
    service.build_index(tmp_path, repository_name="delta", force=True)

    (tmp_path / "a.py").write_text("def a():\n    return 2\n", encoding="utf-8")
    (tmp_path / "b.py").unlink()
    (tmp_path / "c.py").write_text("def c():\n    return 3\n", encoding="utf-8")

    result = service.build_index(tmp_path, repository_name="delta", force=False)
    assert result.summary.total_indexed_files == 2
    assert result.statistics.modified_files == 1
    assert result.statistics.newly_added_files == 1
    assert result.statistics.deleted_files == 1
    assert result.statistics.files_parsed == 2


def test_statistics_and_summary(tmp_path: Path):
    _write_tree(tmp_path)
    index = _real_indexer(tmp_path).build_index(tmp_path, repository_name="demo-repo")
    summary = index.summary
    assert summary.repository_name == "demo-repo"
    assert summary.total_indexed_files == 2
    assert summary.total_functions >= 3  # validate, login, nested, helper
    assert summary.total_classes >= 1
    assert summary.total_imports >= 1
    assert summary.todo_count >= 1
    assert summary.timestamp is not None
    assert index.statistics.indexing_duration_seconds >= 0


def test_query_helpers(tmp_path: Path):
    _write_tree(tmp_path)
    service = _real_indexer(tmp_path)
    index = service.build_index(tmp_path, repository_name="demo")
    assert any("auth.py" in p for p in service.find_files_defining("validate", index))
    assert service.find_files_with_todos(index)
    importers = service.find_files_importing("middleware", index)
    assert any("auth.py" in p for p in importers)


def test_changed_files_since_previous_index(tmp_path: Path):
    (tmp_path / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    service = _real_indexer(tmp_path)
    previous = service.build_index(tmp_path, repository_name="chg")
    (tmp_path / "a.py").write_text("def a():\n    return 2\n", encoding="utf-8")
    current = service.build_index(tmp_path, repository_name="chg", force=True)
    changed = service.changed_files_since(previous, current)
    assert "a.py" in changed


def test_port_methods(tmp_path: Path):
    (tmp_path / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    service = _real_indexer(tmp_path)
    repo = Repository(name="demo", root_path=str(tmp_path), current_branch="main")
    count = service.index_repository(repo, force=True)
    assert count == 1
    assert service.has_index(repo) is True
    assert service.ensure_index(repo) == 1
    service.clear_index(repo)
    assert service.has_index(repo) is False


def test_parse_failures_counted(tmp_path: Path):
    parser = MagicMock(spec=ParserService)
    parser.supported_extensions.return_value = {".py"}
    parser.parse_file.side_effect = ParserError("boom")
    service = IndexerService(parser_service=parser, ignore_dirs=[".git"], logger=_logger())
    (tmp_path / "bad.py").write_text("def x():\n    pass\n", encoding="utf-8")
    index = service.build_index(tmp_path, repository_name="fail")
    assert index.statistics.parse_failures == 1
    assert index.summary.total_indexed_files == 0


def test_large_repository_mocked(tmp_path: Path):
    parser = MagicMock(spec=ParserService)
    parser.supported_extensions.return_value = {".py"}

    def _fake_parse(path, repo_root=None):
        rel = Path(path).name
        return ParsedFile(
            metadata=FileMetadata(path=rel, language="python", content_hash="x", line_count=2),
            module=ParsedModule(
                name=Path(rel).stem,
                functions=[ParsedFunction(name="f", start_line=1, end_line=2)],
                classes=[ParsedClass(name="C", start_line=1, end_line=2)],
                imports=[
                    ParsedImport(
                        module="os",
                        names=["os"],
                        kind=ImportKind.STDLIB,
                        start_line=1,
                        end_line=1,
                    )
                ],
                comments=[
                    ParsedComment(text="# TODO: later", start_line=1, end_line=1, tag=CommentTag.TODO)
                ],
                references=[
                    ParsedReference(source_module=Path(rel).stem, target_module="os", symbol="os")
                ],
            ),
        )

    parser.parse_file.side_effect = _fake_parse
    service = IndexerService(parser_service=parser, ignore_dirs=[".git"], logger=_logger())

    for i in range(50):
        (tmp_path / f"mod_{i}.py").write_text(f"def f_{i}():\n    return {i}\n", encoding="utf-8")

    index = service.build_index(tmp_path, repository_name="large")
    assert index.summary.total_indexed_files == 50
    assert index.statistics.files_parsed == 50
    assert parser.parse_file.call_count == 50
    assert index.summary.total_functions >= 50
