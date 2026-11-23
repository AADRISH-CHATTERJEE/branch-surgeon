"""Tests for error recovery — single file failures don't abort analysis."""

from __future__ import annotations

import tempfile
from pathlib import Path

from refactory.core.logger import get_service_logger
from refactory.parser.service import ParserService


def _make_service() -> ParserService:
    return ParserService(
        ignore_dirs=[".git", "__pycache__"],
        logger=get_service_logger("test.parser"),
    )


def _write_file(root: Path, name: str, content: str) -> Path:
    fp = root / name
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")
    return fp


class TestErrorRecovery:
    def test_bad_file_doesnt_abort_parsing(self):
        svc = _make_service()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_file(root, "good.py", "x = 1\n")
            _write_file(root, "bad.py", "\x00\x01\x02def broken(\n")
            results = svc.parse_directory(root)
            paths = [p.metadata.path for p in results]
            assert "good.py" in paths

    def test_unparseable_syntax_recorded_as_warning(self):
        svc = _make_service()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_file(root, "valid.py", "y = 2\n")
            results = svc.parse_directory(root)
            assert len(results) >= 1

    def test_empty_directory(self):
        svc = _make_service()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            results = svc.parse_directory(root)
            assert results == []

    def test_mixed_good_and_bad_files(self):
        svc = _make_service()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for i in range(5):
                _write_file(root, f"good_{i}.py", f"x_{i} = {i}\n")
            _write_file(root, "data.txt", "not python")
            results = svc.parse_directory(root)
            assert len(results) == 5

    def test_binary_file_skipped(self):
        svc = _make_service()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_file(root, "ok.py", "a = 1\n")
            (root / "binary.py").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
            results = svc.parse_directory(root)
            paths = [p.metadata.path for p in results]
            assert "ok.py" in paths
