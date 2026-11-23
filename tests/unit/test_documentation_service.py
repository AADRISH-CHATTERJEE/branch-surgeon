"""Unit tests for DocumentationService (local only — no LLM/network)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from git import Repo

from refactory.codesearch.models import CodeSearchResult
from refactory.core.exceptions import IndexError_
from refactory.core.logger import get_service_logger
from refactory.documentation.models import DocQuality
from refactory.documentation.service import DocumentationService
from refactory.git.commit_service import CommitService
from refactory.git.service import GitService
from refactory.graph.service import RepositoryGraphService
from refactory.indexer.models import (
    IndexedFile,
    IndexedSymbol,
    RepositoryIndex,
    RepositoryStatistics,
    RepositorySummary,
    SymbolKind,
)
from refactory.indexer.service import IndexerService
from refactory.parser.service import ParserService


def _logger():
    return get_service_logger("test.documentation")


def _summary(**kwargs: object) -> RepositorySummary:
    base = dict(
        repository_root="/tmp/docs",
        repository_name="docs-demo",
        total_indexed_files=0,
        ignored_file_count=0,
        total_functions=0,
        total_classes=0,
        total_imports=0,
        todo_count=0,
        timestamp=datetime.now(timezone.utc),
    )
    base.update(kwargs)
    return RepositorySummary(**base)  # type: ignore[arg-type]


def _index_for(files: dict[str, str], *, comments: dict[str, list[str]] | None = None) -> RepositoryIndex:
    comments = comments or {}
    indexed_files: list[IndexedFile] = []
    symbols: list[IndexedSymbol] = []
    for path, _source in files.items():
        if not path.endswith(".py"):
            continue
        file_symbols = [
            IndexedSymbol(
                name=Path(path).stem,
                kind=SymbolKind.MODULE,
                file_path=path,
                start_line=1,
                end_line=1,
            )
        ]
        # Heuristic symbols for index queries (parser is source of truth for docs).
        if "class User" in files[path]:
            file_symbols.append(
                IndexedSymbol(
                    name="User",
                    kind=SymbolKind.CLASS,
                    file_path=path,
                    start_line=2,
                    end_line=10,
                )
            )
        if "def login" in files[path]:
            file_symbols.append(
                IndexedSymbol(
                    name="login",
                    kind=SymbolKind.FUNCTION,
                    file_path=path,
                    start_line=3,
                    end_line=6,
                )
            )
        if "def undocumented" in files[path]:
            file_symbols.append(
                IndexedSymbol(
                    name="undocumented",
                    kind=SymbolKind.FUNCTION,
                    file_path=path,
                    start_line=3,
                    end_line=4,
                )
            )
        item = IndexedFile(
            relative_path=path,
            language="python",
            content_hash=(path + "x" * 64)[:64],
            module_name=Path(path).stem,
            symbols=file_symbols,
            comments=comments.get(path, []),
            todo_tags=["TODO"] if any("TODO" in c.upper() for c in comments.get(path, [])) else [],
        )
        indexed_files.append(item)
        symbols.extend(file_symbols)
    return RepositoryIndex(
        summary=_summary(total_indexed_files=len(indexed_files)),
        statistics=RepositoryStatistics(),
        files=indexed_files,
        symbols=symbols,
        file_hashes={f.relative_path: f.content_hash for f in indexed_files},
    )


def _build_service(tmp_path: Path, files: dict[str, str], **kwargs: object) -> DocumentationService:
    root = tmp_path / "docs-repo"
    root.mkdir(exist_ok=True)
    repo = Repo.init(root, initial_branch="main")
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "t@example.com")

    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    (root / "README.md").write_text("# root\n", encoding="utf-8") if "README.md" not in files else None
    # Ensure root README exists for some tests unless explicitly omitted.
    if "README.md" in files:
        (root / "README.md").write_text(files["README.md"], encoding="utf-8")

    repo.index.add([p for p in files.keys()] + (["README.md"] if (root / "README.md").exists() else []))
    try:
        repo.index.commit("init")
    except Exception:
        # Empty commit edge — create a file.
        (root / ".keep").write_text("x\n", encoding="utf-8")
        repo.index.add([".keep"])
        repo.index.commit("init")

    index = _index_for(
        {k: v for k, v in files.items() if k.endswith(".py")},
        comments=kwargs.get("comments") if isinstance(kwargs.get("comments"), dict) else None,
    )
    loaded = index.model_copy(
        update={"summary": index.summary.model_copy(update={"repository_root": str(root)})}
    )

    logger = _logger()
    indexer = MagicMock(spec=IndexerService)
    indexer.load_index.return_value = loaded
    indexer.get_last_index.return_value = loaded
    indexer.build_index.side_effect = AssertionError("must never rebuild")

    analysis = MagicMock()
    analysis.get_file_authors.return_value = []
    analysis.get_file_history.return_value = MagicMock(
        last_modification_at=None,
    )

    return DocumentationService(
        logger=logger,
        git_service=GitService(logger=logger, path=root),
        commit_service=MagicMock(spec=CommitService, get_recent_commits=MagicMock(return_value=[])),
        parser_service=ParserService(ignore_dirs=[".git", ".refactory"], logger=logger),
        indexer_service=indexer,
        graph_service=RepositoryGraphService(logger=logger),
        repository_analysis_service=analysis,
        impact_analysis_service=MagicMock(analyze_file=MagicMock(return_value=MagicMock())),
        code_search_service=MagicMock(find_definition=MagicMock(return_value=CodeSearchResult(hits=[]))),
        test_intelligence_service=MagicMock(find_orphan_tests=MagicMock(return_value=[])),
        ignore_dirs=[".git", ".refactory", ".venv"],
    )


DOCUMENTED = '''\
"""Module docs for auth."""

class User:
    """A user entity."""

    def login(self):
        """Authenticate the user."""
        return True


def helper():
    """Public helper."""
    return 1
'''

UNDOCUMENTED = '''\
class User:
    def login(self):
        return True


def undocumented():
    return 2
'''

PARTIAL = '''\
"""Module has docs."""

class User:
    pass


def login():
    return True
'''


@pytest.fixture
def documented_service(tmp_path: Path) -> DocumentationService:
    return _build_service(
        tmp_path,
        {
            "auth.py": DOCUMENTED,
            "pkg/__init__.py": '"""pkg"""\n',
            "pkg/util.py": '"""util module."""\n\ndef run():\n    """Run util."""\n    return 1\n',
            "pkg/README.md": "# pkg\n",
            "README.md": "# root\n",
        },
    )


def test_missing_docstrings(tmp_path: Path):
    service = _build_service(tmp_path, {"auth.py": UNDOCUMENTED, "README.md": "# r\n"})
    gaps = service.find_missing_docstrings()
    symbols = {g.symbol for g in gaps if g.symbol}
    assert "User" in symbols or any(g.kind.value == "class" for g in gaps)
    assert any("undocumented" in (g.symbol or "") for g in gaps)


def test_partial_documentation(tmp_path: Path):
    service = _build_service(tmp_path, {"auth.py": PARTIAL, "README.md": "# r\n"})
    report = service.analyze_file_docs("auth.py")
    assert report.coverage < 1.0
    assert report.coverage > 0.0
    assert any(e.kind.value == "module" and e.quality != DocQuality.MISSING for e in report.entries)


def test_readme_detection(tmp_path: Path):
    service = _build_service(
        tmp_path,
        {
            "auth.py": DOCUMENTED,
            "orphanpkg/mod.py": "def x():\n    return 1\n",
            "README.md": "# root\n",
        },
    )
    missing = service.find_missing_readmes()
    paths = {g.path for g in missing}
    assert "orphanpkg" in paths


def test_nested_packages(documented_service: DocumentationService):
    structure = documented_service.build_repository_structure()
    package_paths = {p.path for p in structure.packages}
    assert "pkg" in package_paths
    summary = documented_service.build_module_summary("pkg/util.py")
    assert summary.module_name
    assert summary.has_readme is True


def test_module_summaries_and_api(documented_service: DocumentationService):
    summary = documented_service.build_module_summary("auth.py")
    assert summary.docstring
    assert "User" in summary.classes or "User" in summary.public_api
    report = documented_service.analyze_symbol_docs("User")
    assert report.found or report.entries or report.gaps is not None


def test_coverage_calculation(documented_service: DocumentationService):
    coverage = documented_service.find_documentation_coverage()
    assert coverage.total_modules >= 1
    assert 0.0 <= coverage.overall_coverage <= 1.0
    assert coverage.documented_modules >= 1


def test_public_api_without_docs(tmp_path: Path):
    service = _build_service(tmp_path, {"auth.py": UNDOCUMENTED, "README.md": "# r\n"})
    gaps = service.find_public_api_without_docs()
    assert gaps


def test_todo_documentation(tmp_path: Path):
    service = _build_service(
        tmp_path,
        {"auth.py": '"""docs"""\n\ndef f():\n    return 1\n', "README.md": "# r\n"},
        comments={"auth.py": ["# TODO: document public API"]},
    )
    # Force comments onto loaded index
    service._cache = None
    index = service._indexer.load_index.return_value
    for f in index.files:
        if f.relative_path == "auth.py":
            f.comments = ["# TODO: document public API"]
            f.todo_tags = ["TODO"]
    todos = service.find_todo_documentation()
    assert todos


def test_stale_docs(tmp_path: Path):
    root_files = {
        "pkg/mod.py": '"""m"""\n\ndef f():\n    """f"""\n    return 1\n',
        "pkg/README.md": "# old\n",
        "README.md": "# root\n",
    }
    service = _build_service(tmp_path, root_files)
    # Make source newer than README.
    readme = service._git.get_root_path() / "pkg" / "README.md"
    mod = service._git.get_root_path() / "pkg" / "mod.py"
    older = 1_600_000_000
    newer = 1_700_000_000
    import os

    os.utime(readme, (older, older))
    os.utime(mod, (newer, newer))
    stale = service.find_stale_documentation()
    assert any(s.path.endswith("pkg/README.md") or "README" in s.path for s in stale)


def test_large_repository(tmp_path: Path):
    files = {"README.md": "# root\n"}
    for i in range(25):
        files[f"m{i}.py"] = f'"""mod {i}"""\n\ndef f{i}():\n    """f{i}"""\n    return {i}\n'
    service = _build_service(tmp_path, files)
    report = service.analyze_repository_docs()
    assert report.module_count >= 25
    assert report.coverage.overall_coverage > 0


def test_cache_reuse(documented_service: DocumentationService):
    documented_service.analyze_file_docs("auth.py")
    first = documented_service._cache
    documented_service.find_missing_docstrings()
    documented_service.build_repository_structure()
    assert documented_service._cache is first
    # Parsed cache hit
    documented_service.analyze_file_docs("auth.py")
    assert "auth.py" in documented_service._cache.parsed


def test_never_rebuilds_index(documented_service: DocumentationService):
    documented_service.analyze_repository_docs()
    documented_service._indexer.build_index.assert_not_called()


def test_missing_index_raises(tmp_path: Path):
    root = tmp_path / "empty"
    root.mkdir()
    repo = Repo.init(root, initial_branch="main")
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "t@example.com")
    (root / "README.md").write_text("x\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("init")
    logger = _logger()
    indexer = MagicMock(spec=IndexerService)
    indexer.load_index.return_value = None
    indexer.get_last_index.return_value = None
    service = DocumentationService(
        logger=logger,
        git_service=GitService(logger=logger, path=root),
        commit_service=MagicMock(),
        parser_service=ParserService(ignore_dirs=[".git"], logger=logger),
        indexer_service=indexer,
        graph_service=RepositoryGraphService(logger=logger),
        repository_analysis_service=MagicMock(),
        impact_analysis_service=MagicMock(),
        code_search_service=MagicMock(),
        test_intelligence_service=MagicMock(),
    )
    with pytest.raises(IndexError_):
        service.analyze_repository_docs()
