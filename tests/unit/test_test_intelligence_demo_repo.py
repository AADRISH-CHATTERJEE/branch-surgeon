"""Regression: demo-repo layout — tests under tests/ must be classified after index load.

Mirrors C:\\Users\\ADMIN\\Documents\\demo-repo (production *.py + tests/test_*.py).
Exercises the real IndexerService persist → load_index path used by CLI commands.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from git import Repo

from refactory.core.logger import get_service_logger
from refactory.git.commit_service import CommitService
from refactory.git.service import GitService
from refactory.graph.service import RepositoryGraphService
from refactory.indexer.service import IndexerService
from refactory.parser.service import ParserService
from refactory.testing.service import TestIntelligenceService, _TEST_PATH_RE


def _logger():
    return get_service_logger("test.testing.demo_repo")


def _init_repo(root: Path) -> None:
    repo = Repo.init(root, initial_branch="main")
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "t@example.com")


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _demo_repo(tmp_path: Path) -> Path:
    """Minimal stand-in for Documents/demo-repo (10 prod / 10 test)."""
    root = tmp_path / "demo-repo"
    root.mkdir()
    _init_repo(root)

    production = {
        "auth.py": (
            "def validate_token(token: str) -> bool:\n"
            "    return token == 'secret'\n"
            "\n"
            "class User:\n"
            "    def login(self) -> str:\n"
            "        return 'ok'\n"
        ),
        "login.py": "def login(user: str) -> bool:\n    return bool(user)\n",
        "user.py": "class User:\n    def __init__(self, name: str) -> None:\n        self.name = name\n",
        "service.py": "def run() -> None:\n    return None\n",
        "jwt.py": "def encode(payload: dict) -> str:\n    return 'jwt'\n",
        "async_demo.py": "async def fetch() -> int:\n    return 1\n",
        "decorator_demo.py": "def deco(fn):\n    return fn\n",
        "imports_demo.py": "import os\n",
        "nested_demo.py": "def outer():\n    def inner():\n        return 1\n    return inner()\n",
        "todo_demo.py": "def work() -> None:\n    # TODO: finish\n    pass\n",
    }
    for name, body in production.items():
        _write(root, name, body)

    tests = {
        "tests/conftest.py": (
            "import pytest\n"
            "\n"
            "@pytest.fixture\n"
            "def valid_token():\n"
            "    return 'secret'\n"
        ),
        "tests/test_auth.py": (
            "from auth import validate_token\n"
            "\n"
            "def test_validate_token_accepts_secret(valid_token):\n"
            "    assert validate_token(valid_token) is True\n"
            "\n"
            "def test_validate_token_rejects_unknown():\n"
            "    assert validate_token('nope') is False\n"
        ),
        "tests/test_login.py": (
            "from login import login\n"
            "\n"
            "def test_login_ok():\n"
            "    assert login('a') is True\n"
        ),
        "tests/test_user.py": (
            "from user import User\n"
            "\n"
            "def test_user_name():\n"
            "    assert User('a').name == 'a'\n"
        ),
        "tests/test_service.py": (
            "from service import run\n"
            "\n"
            "def test_run():\n"
            "    assert run() is None\n"
        ),
        "tests/test_async_demo.py": (
            "from async_demo import fetch\n"
            "\n"
            "import pytest\n"
            "\n"
            "@pytest.mark.asyncio\n"
            "async def test_fetch():\n"
            "    assert await fetch() == 1\n"
        ),
        "tests/test_nested_demo.py": (
            "from nested_demo import outer\n"
            "\n"
            "def test_outer():\n"
            "    assert outer() == 1\n"
        ),
        "tests/test_duplicate_login.py": (
            "from login import login\n"
            "\n"
            "def test_login_ok():\n"
            "    assert login('b') is True\n"
        ),
        "tests/test_integration.py": (
            "from auth import validate_token\n"
            "from service import run\n"
            "\n"
            "def test_validate_token():\n"
            "    assert validate_token('secret') is True\n"
            "\n"
            "def test_run_integration():\n"
            "    assert run() is None\n"
        ),
        "tests/orphan_test.py": (
            "def test_unrelated_math():\n"
            "    assert 1 + 1 == 2\n"
        ),
    }
    for name, body in tests.items():
        _write(root, name, body)

    repo = Repo(root)
    repo.index.add([str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*.py")])
    repo.index.commit("demo suite")
    return root


def _build_service_from_disk(root: Path) -> TestIntelligenceService:
    """Wire TI like production: load persisted index only (never rebuild)."""
    logger = _logger()
    ignore = [".git", ".venv", "__pycache__", ".refactory"]
    parser = ParserService(ignore_dirs=ignore, logger=logger)
    indexer = IndexerService(parser_service=parser, ignore_dirs=ignore, logger=logger)
    built = indexer.build_index(root, repository_name="demo-repo", force=True)
    assert built.summary.total_indexed_files == 20
    assert any(f.relative_path == "tests/test_auth.py" for f in built.files)

    # Fresh indexer instance — only load_index from disk (CLI process boundary).
    loader = IndexerService(parser_service=parser, ignore_dirs=ignore, logger=logger)
    loaded = loader.load_index(root)
    assert loaded is not None
    assert len(loaded.files) == 20

    return TestIntelligenceService(
        logger=logger,
        git_service=GitService(logger=logger, path=root),
        commit_service=CommitService(logger=logger, path=root),
        parser_service=parser,
        indexer_service=loader,
        graph_service=RepositoryGraphService(logger=logger),
        impact_analysis_service=MagicMock(),
        repository_analysis_service=MagicMock(),
        code_search_service=MagicMock(),
    )


def test_is_test_path_recognizes_demo_repo_layout():
    for path in (
        "tests/test_auth.py",
        "tests/conftest.py",
        "tests/orphan_test.py",
        "test_auth.py",
        "auth_test.py",
    ):
        assert _TEST_PATH_RE.search(path.replace("\\", "/")), path


def test_demo_repo_index_classifies_production_and_tests(tmp_path: Path):
    root = _demo_repo(tmp_path)
    service = _build_service_from_disk(root)
    cache = service._ensure_ready()

    assert len(cache.production_files) == 10
    assert len(cache.test_files) == 10
    assert "tests/test_auth.py" in cache.test_files
    assert "auth.py" in cache.production_files
    assert "auth.py" not in cache.test_files


def test_demo_repo_related_tests_for_auth(tmp_path: Path):
    service = _build_service_from_disk(_demo_repo(tmp_path))
    report = service.find_related_tests("auth.py")
    paths = {t.path for t in report.tests}
    assert "tests/test_auth.py" in paths
    assert report.coverage_confidence > 0


def test_demo_repo_coverage_map(tmp_path: Path):
    service = _build_service_from_disk(_demo_repo(tmp_path))
    mapping = service.compute_test_coverage_map()
    assert len(mapping.test_files) == 10
    assert len(mapping.production_files) == 10
    assert mapping.coverage_ratio > 0
    assert "tests/test_auth.py" in mapping.test_files


def test_demo_repo_duplicate_and_orphan_tests(tmp_path: Path):
    service = _build_service_from_disk(_demo_repo(tmp_path))
    orphans = {o.path for o in service.find_orphan_tests()}
    assert "tests/orphan_test.py" in orphans or "tests/conftest.py" in orphans

    groups = service.find_duplicate_tests()
    assert groups
    flat = {t.path for g in groups for t in g.tests}
    assert "tests/test_login.py" in flat or "tests/test_auth.py" in flat


def test_prod_only_index_yields_zero_tests(tmp_path: Path):
    """Exact historical failure mode: 10 production / 0 test when tests absent from index."""
    root = _demo_repo(tmp_path)
    logger = _logger()
    ignore = [".git", ".venv", "__pycache__", ".refactory"]
    parser = ParserService(ignore_dirs=ignore, logger=logger)
    indexer = IndexerService(parser_service=parser, ignore_dirs=ignore, logger=logger)
    full = indexer.build_index(root, repository_name="demo-repo", force=True)
    prod_only = [f for f in full.files if not f.relative_path.startswith("tests/")]
    stale = full.model_copy(
        update={
            "files": prod_only,
            "summary": full.summary.model_copy(
                update={"total_indexed_files": len(prod_only)}
            ),
            "file_hashes": {f.relative_path: f.content_hash for f in prod_only},
            "symbols": [s for f in prod_only for s in f.symbols],
        }
    )
    loader = MagicMock(spec=IndexerService)
    loader.load_index.return_value = stale
    loader.get_last_index.return_value = None
    service = TestIntelligenceService(
        logger=logger,
        git_service=GitService(logger=logger, path=root),
        commit_service=CommitService(logger=logger, path=root),
        parser_service=parser,
        indexer_service=loader,
        graph_service=RepositoryGraphService(logger=logger),
        impact_analysis_service=MagicMock(),
        repository_analysis_service=MagicMock(),
        code_search_service=MagicMock(),
    )
    cache = service._ensure_ready()
    assert len(cache.production_files) == 10
    assert len(cache.test_files) == 0
