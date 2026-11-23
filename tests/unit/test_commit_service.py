"""Unit tests for CommitService (local Git only — no GitHub / network)."""

from __future__ import annotations

from pathlib import Path

import pytest
from git import Repo

from refactory.core.exceptions import CommitNotFound, RepositoryNotFound
from refactory.core.logger import get_service_logger
from refactory.git.commit_service import CommitService
from refactory.git.models import ChangeKind


def _logger():
    return get_service_logger("test.commit")


def _configure(repo: Repo) -> None:
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test User")
        config.set_value("user", "email", "test@example.com")


def _init_repo(path: Path, *, branch: str = "main") -> Repo:
    repo = Repo.init(path, initial_branch=branch)
    _configure(repo)
    (path / "README.md").write_text("# demo\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("initial commit")
    return repo


@pytest.fixture
def repo_path(tmp_path: Path) -> Path:
    root = tmp_path / "commit-repo"
    root.mkdir()
    _init_repo(root)
    return root


def test_commit_lookup(repo_path: Path):
    repo = Repo(repo_path)
    sha = repo.head.commit.hexsha
    service = CommitService(logger=_logger(), path=repo_path)

    detail = service.get_commit(sha)
    assert detail.sha == sha
    assert detail.short_sha == sha[:7]
    assert detail.message == "initial commit"
    assert detail.author_name == "Test User"
    assert detail.author_email == "test@example.com"
    assert detail.parent_shas == []
    assert detail.is_merge is False

    by_short = service.get_commit(sha[:7])
    assert by_short.sha == sha


def test_invalid_hash(repo_path: Path):
    service = CommitService(logger=_logger(), path=repo_path)
    with pytest.raises(CommitNotFound):
        service.get_commit("deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")
    with pytest.raises(CommitNotFound):
        service.get_commit("not-a-real-rev")
    with pytest.raises(CommitNotFound):
        service.get_commit("")


def test_initial_commit(repo_path: Path):
    repo = Repo(repo_path)
    sha = repo.head.commit.hexsha
    service = CommitService(logger=_logger(), path=repo_path)

    detail = service.get_commit(sha)
    assert detail.parent_shas == []
    files = service.get_commit_files(sha)
    assert any(item.path == "README.md" for item in files)
    assert any(item.kind == ChangeKind.ADDED for item in files)
    diff = service.get_commit_diff(sha)
    assert "README.md" in diff.patch or any(f.path == "README.md" for f in diff.files)
    stats = service.get_commit_statistics(sha)
    assert stats.files_changed >= 1
    assert stats.insertions >= 1


def test_merge_commit(repo_path: Path):
    repo = Repo(repo_path)
    main = repo.active_branch
    feature = repo.create_head("feature")
    feature.checkout()
    (repo_path / "feature.py").write_text("x = 1\n", encoding="utf-8")
    repo.index.add(["feature.py"])
    repo.index.commit("feature work")

    main.checkout()
    (repo_path / "main_only.txt").write_text("main\n", encoding="utf-8")
    repo.index.add(["main_only.txt"])
    repo.index.commit("main work")

    # Merge feature into main (creates a merge commit with two parents).
    repo.git.merge("feature", "--no-ff", "-m", "merge feature")
    merge = repo.head.commit
    assert len(merge.parents) == 2

    service = CommitService(logger=_logger(), path=repo_path)
    detail = service.get_commit(merge.hexsha)
    assert detail.is_merge is True
    assert len(detail.parent_shas) == 2
    assert set(detail.parent_shas) == {p.hexsha for p in merge.parents}

    parents = detail.parent_shas
    assert service.get_commit(parents[0]).sha == parents[0]


def test_rename_detection(repo_path: Path):
    repo = Repo(repo_path)
    (repo_path / "old_name.py").write_text("print('hello')\n", encoding="utf-8")
    repo.index.add(["old_name.py"])
    repo.index.commit("add old_name")

    repo.index.remove(["old_name.py"], working_tree=True)
    (repo_path / "new_name.py").write_text("print('hello')\n", encoding="utf-8")
    repo.index.add(["new_name.py"])
    rename_commit = repo.index.commit("rename old_name to new_name")

    service = CommitService(logger=_logger(), path=repo_path)
    files = service.get_commit_files(rename_commit.hexsha)
    kinds = {item.kind for item in files}
    paths = {item.path for item in files}

    # Prefer rename detection; accept delete+add as a fallback signal.
    if ChangeKind.RENAMED in kinds:
        renamed = next(item for item in files if item.kind == ChangeKind.RENAMED)
        assert renamed.path == "new_name.py"
        assert renamed.old_path in {None, "old_name.py"} or renamed.old_path == "old_name.py"
    else:
        assert "new_name.py" in paths
        assert any(item.kind == ChangeKind.ADDED for item in files) or "old_name.py" in {
            item.old_path for item in files
        }


def test_binary_file(repo_path: Path):
    repo = Repo(repo_path)
    blob = bytes([0x00, 0x01, 0x02, 0xFF, 0xFE]) + b"\x00binary"
    (repo_path / "data.bin").write_bytes(blob)
    repo.index.add(["data.bin"])
    commit = repo.index.commit("add binary")

    service = CommitService(logger=_logger(), path=repo_path)
    files = service.get_commit_files(commit.hexsha)
    binary = next(item for item in files if item.path == "data.bin")
    assert binary.is_binary is True
    assert binary.patch is None

    diff = service.get_commit_diff(commit.hexsha)
    assert "data.bin" in diff.patch
    assert "Binary files" in diff.patch


def test_empty_repository(tmp_path: Path):
    root = tmp_path / "empty-repo"
    root.mkdir()
    repo = Repo.init(root, initial_branch="main")
    _configure(repo)

    service = CommitService(logger=_logger(), path=root)
    assert service.get_recent_commits() == []
    with pytest.raises(CommitNotFound):
        service.get_commit("HEAD")
    with pytest.raises(CommitNotFound):
        service.get_commit_diff("HEAD")
    with pytest.raises(CommitNotFound):
        service.get_commit_files("abc1234")
    with pytest.raises(CommitNotFound):
        service.get_commit_statistics("abc1234")


def test_commit_statistics(repo_path: Path):
    repo = Repo(repo_path)
    (repo_path / "a.py").write_text("a = 1\nb = 2\n", encoding="utf-8")
    (repo_path / "b.py").write_text("x = 1\n", encoding="utf-8")
    repo.index.add(["a.py", "b.py"])
    commit = repo.index.commit("add two files")

    service = CommitService(logger=_logger(), path=repo_path)
    stats = service.get_commit_statistics(commit.hexsha)
    assert stats.files_changed == 2
    assert stats.insertions >= 3
    assert stats.deletions == 0


def test_patch_retrieval(repo_path: Path):
    repo = Repo(repo_path)
    (repo_path / "README.md").write_text("# demo\n\nline two\n", encoding="utf-8")
    repo.index.add(["README.md"])
    commit = repo.index.commit("extend readme")

    service = CommitService(logger=_logger(), path=repo_path)
    diff = service.get_commit_diff(commit.hexsha)
    assert diff.sha == commit.hexsha
    assert "README.md" in diff.patch
    assert "+" in diff.patch
    files = service.get_commit_files(commit.hexsha)
    readme = next(item for item in files if item.path == "README.md")
    assert readme.patch is not None
    assert "line two" in readme.patch or readme.insertions >= 1


def test_parent_commit_retrieval(repo_path: Path):
    repo = Repo(repo_path)
    (repo_path / "next.txt").write_text("next\n", encoding="utf-8")
    repo.index.add(["next.txt"])
    child = repo.index.commit("second commit")
    parent_sha = child.parents[0].hexsha

    service = CommitService(logger=_logger(), path=repo_path)
    detail = service.get_commit(child.hexsha)
    assert detail.parent_shas == [parent_sha]
    parent = service.get_commit(parent_sha)
    assert parent.sha == parent_sha
    assert parent.message == "initial commit"


def test_recent_commits_order_and_limit(repo_path: Path):
    repo = Repo(repo_path)
    for i in range(3):
        path = repo_path / f"f{i}.txt"
        path.write_text(f"{i}\n", encoding="utf-8")
        repo.index.add([path.name])
        repo.index.commit(f"commit {i}")

    service = CommitService(logger=_logger(), path=repo_path)
    recent = service.get_recent_commits(limit=2)
    assert len(recent) == 2
    assert recent[0].message == "commit 2"
    assert recent[1].message == "commit 1"
    all_commits = service.get_recent_commits(limit=50)
    assert len(all_commits) == 4  # initial + 3


def test_missing_repository(tmp_path: Path):
    empty = tmp_path / "not-a-repo"
    empty.mkdir()
    service = CommitService(logger=_logger(), path=empty)
    with pytest.raises(RepositoryNotFound):
        service.get_recent_commits()
