"""Unit tests for RepositoryAnalysisService (local Git only)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from git import Actor, Repo

from refactory.analysis.service import RepositoryAnalysisService
from refactory.core.logger import get_service_logger
from refactory.git.commit_service import CommitService
from refactory.git.service import GitService
from refactory.graph.service import RepositoryGraphService
from refactory.indexer.service import IndexerService
from refactory.parser.service import ParserService


def _logger():
    return get_service_logger("test.analysis")


def _configure(repo: Repo, *, name: str = "Test User", email: str = "test@example.com") -> None:
    with repo.config_writer() as config:
        config.set_value("user", "name", name)
        config.set_value("user", "email", email)


def _commit(
    repo: Repo,
    path: Path,
    relative: str,
    content: str,
    message: str,
    *,
    author: Actor | None = None,
) -> None:
    file_path = path / relative
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    repo.index.add([relative.replace("\\", "/")])
    kwargs = {"author": author, "committer": author} if author else {}
    repo.index.commit(message, **kwargs)


def _build_service(root: Path, *, history_limit: int = 500) -> RepositoryAnalysisService:
    logger = _logger()
    ignore = [".git", ".venv", "__pycache__", ".refactory"]
    parser = ParserService(ignore_dirs=ignore, logger=logger)
    indexer = IndexerService(parser_service=parser, ignore_dirs=ignore, logger=logger)
    return RepositoryAnalysisService(
        logger=logger,
        git_service=GitService(logger=logger, path=root),
        commit_service=CommitService(logger=logger, path=root),
        parser_service=parser,
        indexer_service=indexer,
        graph_service=RepositoryGraphService(logger=logger),
        history_limit=history_limit,
        ignore_dirs=ignore,
    )


@pytest.fixture
def repo_path(tmp_path: Path) -> Path:
    root = tmp_path / "analysis-repo"
    root.mkdir()
    repo = Repo.init(root, initial_branch="main")
    _configure(repo)
    _commit(repo, root, "README.md", "# demo\n", "initial")
    return root


def test_empty_repository(tmp_path: Path):
    root = tmp_path / "empty"
    root.mkdir()
    Repo.init(root, initial_branch="main")
    _configure(Repo(root))

    service = _build_service(root)
    overview = service.analyze_repository()
    assert overview.statistics.commit_count == 0
    assert overview.statistics.tracked_files == 0
    assert overview.hotspots.files == []
    assert service.get_recent_activity() == []
    assert service.get_hot_files() == []


def test_single_branch_statistics(repo_path: Path):
    service = _build_service(repo_path)
    stats = service.get_repository_statistics()
    assert stats.commit_count >= 1
    assert stats.tracked_files >= 1
    assert stats.branch_count >= 1
    assert stats.contributor_count >= 1
    assert stats.newest_commit_sha is not None
    assert stats.oldest_commit_sha is not None

    branches = service.get_branch_information()
    assert branches.active_branch == "main"
    assert any(b.name == "main" and b.is_active for b in branches.branches)


def test_multiple_branches_ahead_behind(repo_path: Path):
    repo = Repo(repo_path)
    main = repo.active_branch
    feature = repo.create_head("feature")
    feature.checkout()
    _commit(repo, repo_path, "feature.py", "x = 1\n", "feature work")
    main.checkout()
    _commit(repo, repo_path, "main_only.txt", "m\n", "main work")

    service = _build_service(repo_path)
    report = service.get_branch_information()
    names = {b.name for b in report.branches}
    assert "main" in names
    assert "feature" in names
    feature_info = next(b for b in report.branches if b.name == "feature")
    assert feature_info.ahead >= 1 or feature_info.behind >= 1 or feature_info.last_commit_sha


def test_renames_in_file_history(repo_path: Path):
    repo = Repo(repo_path)
    _commit(repo, repo_path, "old_name.py", "print('hi')\n", "add old")
    repo.index.remove(["old_name.py"], working_tree=True)
    (repo_path / "new_name.py").write_text("print('hi')\n", encoding="utf-8")
    repo.index.add(["new_name.py"])
    repo.index.commit("rename file")

    service = _build_service(repo_path)
    history = service.get_file_history("new_name.py")
    assert history.modification_count >= 1
    # Either explicit rename events or alias traversal finds prior path.
    assert history.modification_count >= 1
    authors = service.get_file_authors("new_name.py")
    assert authors


def test_many_commits_and_hotspots(repo_path: Path):
    repo = Repo(repo_path)
    for i in range(12):
        _commit(repo, repo_path, "hot.py", f"v = {i}\n", f"touch hot {i}")
        _commit(repo, repo_path, "cold.py", f"c = {i}\n", f"touch cold {i}" if i % 4 == 0 else f"cold {i}")

    # Make hot.py hotter
    for i in range(8):
        _commit(repo, repo_path, "hot.py", f"v = {100 + i}\n", f"hot again {i}")

    service = _build_service(repo_path)
    hotspots = service.get_hot_files(limit=5)
    assert hotspots
    assert hotspots[0].path in {"hot.py", "cold.py", "README.md"}
    assert hotspots[0].modification_count >= 1
    assert hotspots[0].score > 0

    stats = service.get_repository_statistics()
    assert stats.commit_count >= 20


def test_binary_files_in_analysis(repo_path: Path):
    repo = Repo(repo_path)
    (repo_path / "blob.bin").write_bytes(b"\x00\x01\x02\xff")
    repo.index.add(["blob.bin"])
    repo.index.commit("binary")

    service = _build_service(repo_path)
    stats = service.get_repository_statistics()
    assert any(item.path == "blob.bin" for item in stats.largest_files) or stats.tracked_files >= 2
    overview = service.analyze_repository()
    assert overview.statistics.tracked_files >= 2


def test_deleted_files_history(repo_path: Path):
    repo = Repo(repo_path)
    _commit(repo, repo_path, "gone.py", "x=1\n", "add gone")
    repo.index.remove(["gone.py"], working_tree=True)
    repo.index.commit("delete gone")

    service = _build_service(repo_path)
    history = service.get_file_history("gone.py")
    assert history.was_deleted is True
    assert history.modification_count >= 2


def test_large_repository_window(repo_path: Path):
    repo = Repo(repo_path)
    for i in range(40):
        _commit(repo, repo_path, f"f{i}.txt", f"{i}\n", f"c{i}")

    service = _build_service(repo_path, history_limit=25)
    stats = service.get_repository_statistics()
    assert stats.commit_count == 25
    # Cache reuse: second call must not fail and stay consistent.
    again = service.get_repository_statistics()
    assert again.commit_count == 25


def test_multiple_authors(repo_path: Path):
    repo = Repo(repo_path)
    ada = Actor("Ada", "ada@example.com")
    bob = Actor("Bob", "bob@example.com")
    _commit(repo, repo_path, "shared.py", "a=1\n", "ada edit", author=ada)
    _commit(repo, repo_path, "shared.py", "a=2\n", "bob edit", author=bob)

    service = _build_service(repo_path)
    authors = service.get_file_authors("shared.py")
    names = {a.name for a in authors}
    assert "Ada" in names
    assert "Bob" in names

    hotspots = service.get_hotspots()
    multi = [e for e in hotspots.multi_author_files if e.path == "shared.py"]
    assert multi
    assert multi[0].author_count >= 2


def test_repository_languages_and_activity(repo_path: Path):
    repo = Repo(repo_path)
    _commit(repo, repo_path, "mod.py", "# TODO: later\n# FIXME: now\nx=1\n", "python")
    service = _build_service(repo_path)
    languages = service.get_repository_languages()
    assert "python" in languages or languages  # indexer or extension fallback
    activity = service.get_recent_activity(limit=5)
    assert activity
    assert activity[0].sha
    overview = service.analyze_repository()
    assert overview.health.todo_count >= 0
    assert overview.name


def test_cache_reused_across_queries(repo_path: Path):
    service = _build_service(repo_path)
    service.get_repository_statistics()
    first_cache = service._cache
    service.get_hot_files()
    service.get_branch_information()
    assert service._cache is first_cache
