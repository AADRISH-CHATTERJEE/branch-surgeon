"""Tests for IndexerService → PersistenceService integration.

Verifies that:
  - Successful indexing persists repository, files, symbols, imports to DB
  - PersistenceService APIs are called correctly
  - Database failures never cause indexing to fail
  - Existing JSON persistence and IndexerService behaviour is unchanged
  - Persistence is skipped when PersistenceService is None
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from refactory.core.logger import get_service_logger
from refactory.indexer.models import (
    ImportReference,
    IndexedFile,
    IndexedSymbol,
    RepositoryIndex,
    RepositoryStatistics,
    RepositorySummary,
    SymbolKind,
)
from refactory.indexer.service import INDEX_FILENAME, IndexerService
from refactory.parser.models import (
    CommentTag,
    FileMetadata,
    ImportKind,
    ParsedClass,
    ParsedComment,
    ParsedFile,
    ParsedFunction,
    ParsedImport,
    ParsedModule,
    ParsedReference,
)
from refactory.parser.service import ParserService
from refactory.review.models import Repository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _logger():
    return get_service_logger("test.indexer.persist")


def _make_persistence_mock() -> MagicMock:
    """Create a fresh PersistenceService mock."""
    mock = MagicMock()
    mock.get_or_create_repository.return_value = {
        "id": "repo-001",
        "name": "test-repo",
        "root_path": "/test",
        "default_branch": "main",
        "remote_url": None,
        "created_at": None,
        "updated_at": None,
    }
    mock.persist_files_bulk.return_value = 2

    uow = MagicMock()
    file_model = MagicMock()
    file_model.id = "file-001"
    uow.files.get_by_repo_path.return_value = file_model
    uow.symbols.delete_by_file.return_value = 0
    uow.symbols.bulk_insert.return_value = []
    uow.imports.delete_by_file.return_value = 0
    uow.imports.bulk_insert.return_value = []
    uow.__enter__ = MagicMock(return_value=uow)
    uow.__exit__ = MagicMock(return_value=False)
    mock.unit_of_work.return_value = uow
    mock._uow = uow
    return mock


def _fake_parse(path, repo_root=None):
    """Produce a realistic ParsedFile from a .py file."""
    rel = Path(path).name
    stem = Path(rel).stem
    return ParsedFile(
        metadata=FileMetadata(path=rel, language="python", content_hash="abc123", line_count=10),
        module=ParsedModule(
            name=stem,
            functions=[ParsedFunction(name=f"func_{stem}", start_line=1, end_line=5)],
            classes=[ParsedClass(name=f"Class_{stem}", start_line=6, end_line=10)],
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
                ParsedComment(text="# TODO: fix", start_line=1, end_line=1, tag=CommentTag.TODO)
            ],
            references=[
                ParsedReference(source_module=stem, target_module="os", symbol="path")
            ],
        ),
    )


def _indexer_with_persistence(
    tmp_path: Path,
    *,
    persistence: MagicMock | None = "DEFAULT",
    file_count: int = 2,
) -> tuple[IndexerService, MagicMock | None]:
    """Create an IndexerService with mocked parser and optional persistence."""
    if persistence == "DEFAULT":
        persistence = _make_persistence_mock()

    parser = MagicMock(spec=ParserService)
    parser.supported_extensions.return_value = {".py"}
    parser.parse_file.side_effect = _fake_parse

    for i in range(file_count):
        (tmp_path / f"mod_{i}.py").write_text(f"def f_{i}():\n    return {i}\n", encoding="utf-8")

    service = IndexerService(
        parser_service=parser,
        ignore_dirs=[".git", "__pycache__", ".refactory"],
        logger=_logger(),
        persistence_service=persistence,
    )
    return service, persistence


# ---------------------------------------------------------------------------
# Tests: Successful persistence
# ---------------------------------------------------------------------------

class TestIndexerPersistence:
    """Core persistence integration tests."""

    def test_get_or_create_repository_called(self, tmp_path):
        service, persistence = _indexer_with_persistence(tmp_path)
        service.build_index(tmp_path, repository_name="my-repo")
        persistence.get_or_create_repository.assert_called_once_with(
            name="my-repo",
            root_path=str(tmp_path.resolve()),
            default_branch="main",
        )

    def test_persist_files_bulk_called(self, tmp_path):
        service, persistence = _indexer_with_persistence(tmp_path, file_count=3)
        service.build_index(tmp_path, repository_name="bulk-test")
        persistence.persist_files_bulk.assert_called_once()
        call_args = persistence.persist_files_bulk.call_args
        assert call_args[0][0] == "repo-001"
        assert len(call_args[0][1]) == 3

    def test_file_dicts_contain_required_fields(self, tmp_path):
        service, persistence = _indexer_with_persistence(tmp_path, file_count=1)
        service.build_index(tmp_path, repository_name="fields")
        file_dicts = persistence.persist_files_bulk.call_args[0][1]
        f = file_dicts[0]
        assert "path" in f
        assert "language" in f
        assert "sha256" in f
        assert "size" in f
        assert f["language"] == "python"
        assert len(f["sha256"]) == 64

    def test_symbols_persisted_via_uow(self, tmp_path):
        service, persistence = _indexer_with_persistence(tmp_path, file_count=1)
        service.build_index(tmp_path, repository_name="syms")
        uow = persistence._uow
        uow.symbols.delete_by_file.assert_called()
        uow.symbols.bulk_insert.assert_called()
        sym_dicts = uow.symbols.bulk_insert.call_args[0][0]
        assert len(sym_dicts) > 0
        s = sym_dicts[0]
        assert "file_id" in s
        assert "name" in s
        assert "type" in s
        assert "line" in s

    def test_imports_persisted_via_uow(self, tmp_path):
        service, persistence = _indexer_with_persistence(tmp_path, file_count=1)
        service.build_index(tmp_path, repository_name="imps")
        uow = persistence._uow
        uow.imports.delete_by_file.assert_called()
        uow.imports.bulk_insert.assert_called()
        imp_dicts = uow.imports.bulk_insert.call_args[0][0]
        assert len(imp_dicts) > 0
        i = imp_dicts[0]
        assert i["file_id"] == "file-001"
        assert i["module"] == "os"
        assert i["symbol"] == "path"

    def test_unit_of_work_used_for_symbols_and_imports(self, tmp_path):
        service, persistence = _indexer_with_persistence(tmp_path, file_count=2)
        service.build_index(tmp_path, repository_name="uow-test")
        persistence.unit_of_work.assert_called_once()
        uow = persistence._uow
        uow.__enter__.assert_called_once()
        uow.__exit__.assert_called_once()


class TestBulkPersistence:
    """Tests for bulk operations with multiple files."""

    def test_multiple_files_persisted(self, tmp_path):
        service, persistence = _indexer_with_persistence(tmp_path, file_count=5)
        service.build_index(tmp_path, repository_name="multi")
        file_dicts = persistence.persist_files_bulk.call_args[0][1]
        assert len(file_dicts) == 5

    def test_symbols_persisted_per_file(self, tmp_path):
        service, persistence = _indexer_with_persistence(tmp_path, file_count=3)
        service.build_index(tmp_path, repository_name="per-file")
        uow = persistence._uow
        assert uow.files.get_by_repo_path.call_count == 3
        assert uow.symbols.delete_by_file.call_count == 3
        assert uow.symbols.bulk_insert.call_count == 3

    def test_imports_persisted_per_file(self, tmp_path):
        service, persistence = _indexer_with_persistence(tmp_path, file_count=3)
        service.build_index(tmp_path, repository_name="per-file")
        uow = persistence._uow
        assert uow.imports.delete_by_file.call_count == 3
        assert uow.imports.bulk_insert.call_count == 3


class TestFailureHandling:
    """Database failures never break the indexing pipeline."""

    def test_repository_creation_failure_does_not_fail_indexing(self, tmp_path):
        service, persistence = _indexer_with_persistence(tmp_path)
        persistence.get_or_create_repository.side_effect = ConnectionError("db down")
        index = service.build_index(tmp_path, repository_name="fail-repo")
        assert index.summary.total_indexed_files == 2
        assert index.files is not None

    def test_persist_files_bulk_failure_does_not_fail_indexing(self, tmp_path):
        service, persistence = _indexer_with_persistence(tmp_path)
        persistence.persist_files_bulk.side_effect = RuntimeError("insert failed")
        index = service.build_index(tmp_path, repository_name="fail-files")
        assert index.summary.total_indexed_files == 2

    def test_uow_failure_does_not_fail_indexing(self, tmp_path):
        service, persistence = _indexer_with_persistence(tmp_path)
        persistence.unit_of_work.side_effect = RuntimeError("session exploded")
        index = service.build_index(tmp_path, repository_name="fail-uow")
        assert index.summary.total_indexed_files == 2

    def test_json_index_still_written_on_db_failure(self, tmp_path):
        service, persistence = _indexer_with_persistence(tmp_path)
        persistence.get_or_create_repository.side_effect = Exception("db error")
        service.build_index(tmp_path, repository_name="json-ok")
        json_path = tmp_path.resolve() / ".refactory" / INDEX_FILENAME
        assert json_path.is_file()

    def test_index_result_unchanged_on_db_failure(self, tmp_path):
        service_ok, _ = _indexer_with_persistence(tmp_path, file_count=2)
        service_fail, persistence_fail = _indexer_with_persistence(tmp_path, file_count=2)
        persistence_fail.get_or_create_repository.side_effect = Exception("boom")

        result_ok = service_ok.build_index(tmp_path, repository_name="cmp")
        result_fail = service_fail.build_index(tmp_path, repository_name="cmp")

        assert result_ok.summary.total_indexed_files == result_fail.summary.total_indexed_files
        assert len(result_ok.files) == len(result_fail.files)


class TestFailureLogging:
    """Verify error logging on persistence failure."""

    def test_db_failure_logged_with_error(self, tmp_path):
        mock_logger = MagicMock()
        persistence = _make_persistence_mock()
        persistence.get_or_create_repository.side_effect = RuntimeError("disk full")
        parser = MagicMock(spec=ParserService)
        parser.supported_extensions.return_value = {".py"}
        parser.parse_file.side_effect = _fake_parse
        (tmp_path / "a.py").write_text("x=1\n", encoding="utf-8")

        service = IndexerService(
            parser_service=parser,
            ignore_dirs=[".git", ".refactory"],
            logger=mock_logger,
            persistence_service=persistence,
        )
        service.build_index(tmp_path, repository_name="err-repo")

        mock_logger.error.assert_called_once()
        error_str = str(mock_logger.error.call_args)
        assert "disk full" in error_str
        assert "err-repo" in error_str

    def test_db_failure_log_includes_traceback(self, tmp_path):
        mock_logger = MagicMock()
        persistence = _make_persistence_mock()
        persistence.persist_files_bulk.side_effect = ValueError("bad data")
        parser = MagicMock(spec=ParserService)
        parser.supported_extensions.return_value = {".py"}
        parser.parse_file.side_effect = _fake_parse
        (tmp_path / "a.py").write_text("x=1\n", encoding="utf-8")

        service = IndexerService(
            parser_service=parser,
            ignore_dirs=[".git", ".refactory"],
            logger=mock_logger,
            persistence_service=persistence,
        )
        service.build_index(tmp_path, repository_name="tb-repo")

        error_str = str(mock_logger.error.call_args)
        assert "ValueError" in error_str or "bad data" in error_str


class TestNoPersistenceService:
    """Verify backward compat when PersistenceService is None."""

    def test_indexing_works_without_persistence(self, tmp_path):
        service, _ = _indexer_with_persistence(tmp_path, persistence=None, file_count=2)
        index = service.build_index(tmp_path, repository_name="no-persist")
        assert index.summary.total_indexed_files == 2

    def test_no_persistence_no_errors(self, tmp_path):
        service, _ = _indexer_with_persistence(tmp_path, persistence=None)
        index = service.build_index(tmp_path, repository_name="safe")
        assert index.files is not None

    def test_engine_instantiates_without_persistence(self):
        service = IndexerService(
            parser_service=MagicMock(spec=ParserService),
            ignore_dirs=[],
            logger=_logger(),
        )
        assert service._persistence is None

    def test_json_index_written_without_persistence(self, tmp_path):
        service, _ = _indexer_with_persistence(tmp_path, persistence=None, file_count=1)
        service.build_index(tmp_path, repository_name="json-only")
        json_path = tmp_path.resolve() / ".refactory" / INDEX_FILENAME
        assert json_path.is_file()


class TestSuccessLogging:
    """Verify structured logs for successful DB persistence."""

    def test_persist_logs_repository(self, tmp_path):
        mock_logger = MagicMock()
        persistence = _make_persistence_mock()
        parser = MagicMock(spec=ParserService)
        parser.supported_extensions.return_value = {".py"}
        parser.parse_file.side_effect = _fake_parse
        (tmp_path / "a.py").write_text("x=1\n", encoding="utf-8")

        service = IndexerService(
            parser_service=parser,
            ignore_dirs=[".git", ".refactory"],
            logger=mock_logger,
            persistence_service=persistence,
        )
        service.build_index(tmp_path, repository_name="log-repo")

        info_calls = mock_logger.info.call_args_list
        persist_calls = [c for c in info_calls if "DB persist" in str(c)]
        assert len(persist_calls) >= 4

        repo_call = [c for c in persist_calls if "repo_id" in str(c)]
        assert len(repo_call) >= 1

    def test_persist_logs_files(self, tmp_path):
        mock_logger = MagicMock()
        persistence = _make_persistence_mock()
        parser = MagicMock(spec=ParserService)
        parser.supported_extensions.return_value = {".py"}
        parser.parse_file.side_effect = _fake_parse
        (tmp_path / "a.py").write_text("x=1\n", encoding="utf-8")

        service = IndexerService(
            parser_service=parser,
            ignore_dirs=[".git", ".refactory"],
            logger=mock_logger,
            persistence_service=persistence,
        )
        service.build_index(tmp_path, repository_name="log-files")

        info_calls = mock_logger.info.call_args_list
        file_calls = [c for c in info_calls if "files=" in str(c) and "DB persist" in str(c)]
        assert len(file_calls) >= 1

    def test_persist_logs_completion_with_elapsed(self, tmp_path):
        mock_logger = MagicMock()
        persistence = _make_persistence_mock()
        parser = MagicMock(spec=ParserService)
        parser.supported_extensions.return_value = {".py"}
        parser.parse_file.side_effect = _fake_parse
        (tmp_path / "a.py").write_text("x=1\n", encoding="utf-8")

        service = IndexerService(
            parser_service=parser,
            ignore_dirs=[".git", ".refactory"],
            logger=mock_logger,
            persistence_service=persistence,
        )
        service.build_index(tmp_path, repository_name="log-time")

        info_calls = mock_logger.info.call_args_list
        complete_calls = [c for c in info_calls if "complete" in str(c).lower() and "elapsed_ms" in str(c)]
        assert len(complete_calls) >= 1


class TestEdgeCases:
    """Edge cases for indexer persistence."""

    def test_empty_repository_persists_no_files(self, tmp_path):
        service, persistence = _indexer_with_persistence(tmp_path, file_count=0)
        index = service.build_index(tmp_path, repository_name="empty")
        persistence.persist_files_bulk.assert_called_once_with("repo-001", [])

    def test_parse_error_files_excluded_from_db(self, tmp_path):
        """Files with parse errors should not be persisted to DB."""
        persistence = _make_persistence_mock()
        parser = MagicMock(spec=ParserService)
        parser.supported_extensions.return_value = {".py"}
        from refactory.core.exceptions import ParserError
        parser.parse_file.side_effect = ParserError("syntax error")
        (tmp_path / "broken.py").write_text("def x(\n", encoding="utf-8")

        service = IndexerService(
            parser_service=parser,
            ignore_dirs=[".git", ".refactory"],
            logger=_logger(),
            persistence_service=persistence,
        )
        index = service.build_index(tmp_path, repository_name="broken")
        file_dicts = persistence.persist_files_bulk.call_args[0][1]
        assert len(file_dicts) == 0

    def test_file_not_found_in_db_skips_symbols(self, tmp_path):
        """If a file isn't found in DB after persist_files_bulk, symbols/imports are skipped."""
        service, persistence = _indexer_with_persistence(tmp_path, file_count=1)
        uow = persistence._uow
        uow.files.get_by_repo_path.return_value = None
        service.build_index(tmp_path, repository_name="missing")
        uow.symbols.bulk_insert.assert_not_called()
        uow.imports.bulk_insert.assert_not_called()

    def test_file_with_no_symbols_or_imports(self, tmp_path):
        """Files with no symbols or imports don't call bulk_insert unnecessarily."""
        persistence = _make_persistence_mock()
        parser = MagicMock(spec=ParserService)
        parser.supported_extensions.return_value = {".py"}

        def _bare_parse(path, repo_root=None):
            return ParsedFile(
                metadata=FileMetadata(
                    path=Path(path).name, language="python",
                    content_hash="abc", line_count=1,
                ),
                module=ParsedModule(name="bare"),
            )

        parser.parse_file.side_effect = _bare_parse
        (tmp_path / "bare.py").write_text("pass\n", encoding="utf-8")

        service = IndexerService(
            parser_service=parser,
            ignore_dirs=[".git", ".refactory"],
            logger=_logger(),
            persistence_service=persistence,
        )
        index = service.build_index(tmp_path, repository_name="bare")
        uow = persistence._uow
        assert uow.symbols.bulk_insert.call_count == 1
        sym_dicts = uow.symbols.bulk_insert.call_args[0][0]
        assert len(sym_dicts) == 1
        assert sym_dicts[0]["type"] == "module"
        uow.imports.bulk_insert.assert_not_called()


class TestBackwardCompatibility:
    """Ensure persistence does not alter existing behaviour."""

    def test_build_index_returns_same_type(self, tmp_path):
        service, _ = _indexer_with_persistence(tmp_path)
        index = service.build_index(tmp_path, repository_name="compat")
        assert isinstance(index, RepositoryIndex)

    def test_last_index_still_set(self, tmp_path):
        service, _ = _indexer_with_persistence(tmp_path)
        service.build_index(tmp_path, repository_name="compat")
        assert service.get_last_index() is not None

    def test_index_repository_port_unchanged(self, tmp_path):
        service, _ = _indexer_with_persistence(tmp_path, file_count=2)
        repo = Repository(name="port", root_path=str(tmp_path), current_branch="main")
        count = service.index_repository(repo, force=True)
        assert count == 2

    def test_ensure_index_port_unchanged(self, tmp_path):
        service, _ = _indexer_with_persistence(tmp_path, file_count=1)
        repo = Repository(name="port", root_path=str(tmp_path), current_branch="main")
        service.index_repository(repo, force=True)
        count = service.ensure_index(repo)
        assert count == 1
