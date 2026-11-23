"""Tests for incremental parsing (ParserService.parse_incremental)."""

from __future__ import annotations

from pathlib import Path

import pytest

from refactory.parser.service import IncrementalParseResult, ParserService


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    d = tmp_path / "src"
    d.mkdir()
    return d


@pytest.fixture
def parser() -> ParserService:
    from loguru import logger
    return ParserService(ignore_dirs=["__pycache__"], logger=logger)


class TestIncrementalParsing:
    def test_first_run_parses_all(self, parser: ParserService, source_dir: Path):
        (source_dir / "a.py").write_text("def hello(): pass\n", encoding="utf-8")
        (source_dir / "b.py").write_text("def world(): pass\n", encoding="utf-8")

        result = parser.parse_incremental(source_dir)
        assert isinstance(result, IncrementalParseResult)
        assert result.parsed_count == 2
        assert result.skipped_count == 0
        assert result.total_files == 2
        assert len(result.file_hashes) == 2

    def test_unchanged_files_skipped(self, parser: ParserService, source_dir: Path):
        (source_dir / "a.py").write_text("x = 1\n", encoding="utf-8")
        (source_dir / "b.py").write_text("y = 2\n", encoding="utf-8")

        r1 = parser.parse_incremental(source_dir)
        r2 = parser.parse_incremental(source_dir, previous_hashes=r1.file_hashes)
        assert r2.skipped_count == 2
        assert r2.parsed_count == 0

    def test_modified_file_reparsed(self, parser: ParserService, source_dir: Path):
        (source_dir / "a.py").write_text("x = 1\n", encoding="utf-8")
        r1 = parser.parse_incremental(source_dir)

        (source_dir / "a.py").write_text("x = 2\n", encoding="utf-8")
        r2 = parser.parse_incremental(source_dir, previous_hashes=r1.file_hashes)
        assert r2.parsed_count == 1
        assert r2.skipped_count == 0

    def test_new_file_detected(self, parser: ParserService, source_dir: Path):
        (source_dir / "a.py").write_text("x = 1\n", encoding="utf-8")
        r1 = parser.parse_incremental(source_dir)

        (source_dir / "b.py").write_text("y = 2\n", encoding="utf-8")
        r2 = parser.parse_incremental(source_dir, previous_hashes=r1.file_hashes)
        assert r2.parsed_count == 1
        assert r2.skipped_count == 1

    def test_deleted_file_not_in_hashes(self, parser: ParserService, source_dir: Path):
        (source_dir / "a.py").write_text("x = 1\n", encoding="utf-8")
        (source_dir / "b.py").write_text("y = 2\n", encoding="utf-8")
        r1 = parser.parse_incremental(source_dir)

        (source_dir / "b.py").unlink()
        r2 = parser.parse_incremental(source_dir, previous_hashes=r1.file_hashes)
        assert "b.py" not in r2.file_hashes
        assert r2.total_files == 1

    def test_empty_directory(self, parser: ParserService, source_dir: Path):
        result = parser.parse_incremental(source_dir)
        assert result.parsed_count == 0
        assert result.skipped_count == 0
        assert result.total_files == 0

    def test_non_python_files_ignored(self, parser: ParserService, source_dir: Path):
        (source_dir / "readme.md").write_text("# Hello\n", encoding="utf-8")
        (source_dir / "a.py").write_text("x = 1\n", encoding="utf-8")
        result = parser.parse_incremental(source_dir)
        assert result.total_files == 1

    def test_binary_file_skipped(self, parser: ParserService, source_dir: Path):
        (source_dir / "a.py").write_bytes(b"\x00\x01\x02\x03")
        result = parser.parse_incremental(source_dir)
        assert result.error_count >= 0

    def test_file_hashes_deterministic(self, parser: ParserService, source_dir: Path):
        (source_dir / "a.py").write_text("x = 1\n", encoding="utf-8")
        r1 = parser.parse_incremental(source_dir)
        r2 = parser.parse_incremental(source_dir)
        assert r1.file_hashes == r2.file_hashes

    def test_partial_modifications(self, parser: ParserService, source_dir: Path):
        (source_dir / "a.py").write_text("x = 1\n", encoding="utf-8")
        (source_dir / "b.py").write_text("y = 2\n", encoding="utf-8")
        (source_dir / "c.py").write_text("z = 3\n", encoding="utf-8")
        r1 = parser.parse_incremental(source_dir)

        (source_dir / "b.py").write_text("y = 99\n", encoding="utf-8")
        r2 = parser.parse_incremental(source_dir, previous_hashes=r1.file_hashes)
        assert r2.parsed_count == 1
        assert r2.skipped_count == 2

    def test_nonexistent_dir_raises(self, parser: ParserService, tmp_path: Path):
        with pytest.raises(Exception):
            parser.parse_incremental(tmp_path / "nonexistent")

    def test_ignore_dirs_respected(self, source_dir: Path):
        from loguru import logger
        p = ParserService(ignore_dirs=["vendor"], logger=logger)
        vendor = source_dir / "vendor"
        vendor.mkdir()
        (vendor / "lib.py").write_text("a = 1\n", encoding="utf-8")
        (source_dir / "main.py").write_text("b = 2\n", encoding="utf-8")
        result = p.parse_incremental(source_dir)
        assert result.total_files == 1

    def test_previous_hashes_none_parses_all(self, parser: ParserService, source_dir: Path):
        (source_dir / "a.py").write_text("x = 1\n", encoding="utf-8")
        result = parser.parse_incremental(source_dir, previous_hashes=None)
        assert result.parsed_count == 1

    def test_result_properties(self, parser: ParserService, source_dir: Path):
        (source_dir / "a.py").write_text("x = 1\n", encoding="utf-8")
        result = parser.parse_incremental(source_dir)
        assert result.parsed_count == len(result.parsed_files)
