"""Tests for parallel parsing and parse caching in ParserService."""

from __future__ import annotations

import tempfile
from pathlib import Path

from refactory.core.logger import get_service_logger
from refactory.parser.service import ParserService


def _make_service(*, max_workers: int = 2) -> ParserService:
    return ParserService(
        ignore_dirs=[".git", "__pycache__"],
        logger=get_service_logger("test.parser"),
        max_workers=max_workers,
    )


def _write_file(root: Path, name: str, content: str) -> Path:
    fp = root / name
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")
    return fp


class TestParseCaching:
    def test_same_content_returns_same_object(self):
        svc = _make_service()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_file(root, "module.py", "def hello(): pass\n")
            first = svc.parse_file(root / "module.py", repo_root=root)
            second = svc.parse_file(root / "module.py", repo_root=root)
            assert first is second

    def test_changed_content_reparsed(self):
        svc = _make_service()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fp = _write_file(root, "module.py", "def hello(): pass\n")
            first = svc.parse_file(fp, repo_root=root)
            fp.write_text("def goodbye(): pass\n", encoding="utf-8")
            second = svc.parse_file(fp, repo_root=root)
            assert first is not second

    def test_clear_cache(self):
        svc = _make_service()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fp = _write_file(root, "module.py", "x = 1\n")
            first = svc.parse_file(fp, repo_root=root)
            svc.clear_cache()
            second = svc.parse_file(fp, repo_root=root)
            assert first is not second


class TestParallelParsing:
    def test_parallel_produces_same_as_serial(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for i in range(10):
                _write_file(root, f"mod_{i:02d}.py", f"x_{i} = {i}\n")

            serial = _make_service(max_workers=1)
            serial_results = serial.parse_directory(root, max_workers=1)

            parallel = _make_service(max_workers=4)
            parallel_results = parallel.parse_directory(root, max_workers=4)

            serial_names = sorted(p.metadata.path for p in serial_results)
            parallel_names = sorted(p.metadata.path for p in parallel_results)
            assert serial_names == parallel_names

    def test_deterministic_ordering(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for name in ["c.py", "a.py", "b.py"]:
                _write_file(root, name, f"x = '{name}'\n")

            svc = _make_service(max_workers=4)
            r1 = svc.parse_directory(root, max_workers=4)
            r2 = svc.parse_directory(root, max_workers=4)
            names1 = [p.metadata.path for p in r1]
            names2 = [p.metadata.path for p in r2]
            assert names1 == names2

    def test_skip_unparseable_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_file(root, "good.py", "x = 1\n")
            _write_file(root, "data.txt", "not code")
            svc = _make_service()
            results = svc.parse_directory(root)
            assert len(results) >= 1
            parsed_paths = [p.metadata.path for p in results]
            assert "good.py" in parsed_paths

    def test_parallel_handles_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            svc = _make_service()
            results = svc.parse_directory(root)
            assert results == []

    def test_max_workers_clamp(self):
        svc = ParserService(
            ignore_dirs=[],
            logger=get_service_logger("test"),
            max_workers=0,
        )
        assert svc._max_workers == 1


class TestParserServiceConstructor:
    def test_new_max_workers_param_optional(self):
        svc = ParserService(
            ignore_dirs=[],
            logger=get_service_logger("test"),
        )
        assert svc._max_workers == 4

    def test_cache_starts_empty(self):
        svc = _make_service()
        assert len(svc._cache) == 0
