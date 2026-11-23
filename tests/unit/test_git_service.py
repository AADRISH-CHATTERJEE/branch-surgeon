"""Unit tests for GitService (local Git only)."""

from __future__ import annotations

from pathlib import Path

import pytest
from git import Repo

from refactory.core.exceptions import RefactoryError, RepositoryNotFound
from refactory.core.logger import get_service_logger
from refactory.git.models import ChangeKind, ChangedPath
from refactory.git.service import GitService


def _logger():
    return get_service_logger("test.git")


def _init_repo(path: Path, *, branch: str = "main") -> Repo:
    repo = Repo.init(path, initial_branch=branch)
    # Configure identity for commits inside temp repos.
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test User")
        config.set_value("user", "email", "test@example.com")
    (path / "README.md").write_text("# demo\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("initial commit")
    return repo


@pytest.fixture
def repo_path(tmp_path: Path) -> Path:
    root = tmp_path / "demo-repo"
    root.mkdir()
    _init_repo(root)
    return root


def test_existing_repository_metadata(repo_path: Path):
    service = GitService(logger=_logger(), path=repo_path)
    meta = service.get_repository_metadata()

    assert meta.root_path == str(repo_path.resolve())
    assert meta.name == "demo-repo"
    assert meta.current_branch == "main"
    assert meta.default_branch == "main"
    assert meta.remote_url is None


def test_require_repository_returns_repository(repo_path: Path):
    service = GitService(logger=_logger(), path=repo_path)
    repo = service.require_repository()
    assert repo.root_path == str(repo_path.resolve())


def test_missing_repository_raises(tmp_path: Path):
    empty = tmp_path / "not-a-repo"
    empty.mkdir()
    service = GitService(logger=_logger(), path=empty)

    assert service.is_git_repository() is False
    assert service.repository_exists() is False
    with pytest.raises(RepositoryNotFound):
        service.require_repository()
    with pytest.raises(RepositoryNotFound):
        service.repository_root()


def test_nested_directory_discovery(repo_path: Path):
    nested = repo_path / "src" / "auth"
    nested.mkdir(parents=True)
    service = GitService(logger=_logger(), path=nested)

    assert service.is_git_repository() is True
    assert service.repository_root() == repo_path.resolve()
    assert service.get_repository_metadata().root_path == str(repo_path.resolve())


def test_detached_head(repo_path: Path):
    repo = Repo(repo_path)
    repo.git.checkout("--detach", "HEAD")

    service = GitService(logger=_logger(), path=repo_path)
    info = service.get_repository_info()

    assert info.is_detached is True
    assert service.is_detached_head() is True
    assert info.current_branch.startswith("HEAD (detached")
    assert info.head_sha is not None
    assert len(info.head_sha) == 40


def test_clean_repository(repo_path: Path):
    service = GitService(logger=_logger(), path=repo_path)
    assert service.is_clean_working_tree() is True
    assert service.has_uncommitted_changes() is False
    status = service.get_working_tree_status()
    assert status.is_dirty is False
    assert status.changed_file_count == 0


def test_dirty_working_tree_modified_and_untracked(repo_path: Path):
    service = GitService(logger=_logger(), path=repo_path)
    (repo_path / "README.md").write_text("# dirty\n", encoding="utf-8")
    (repo_path / "tests").mkdir()
    (repo_path / "tests" / "test_auth.py").write_text("def test_x(): ...\n", encoding="utf-8")

    assert service.is_clean_working_tree() is False
    assert service.has_uncommitted_changes() is True

    modified = {item.path for item in service.get_modified_files()}
    assert "README.md" in modified
    assert "tests/test_auth.py" in service.get_untracked_files() or any(
        path.replace("\\", "/").endswith("tests/test_auth.py")
        for path in service.get_untracked_files()
    )


def test_deleted_files(repo_path: Path):
    (repo_path / "README.md").unlink()
    service = GitService(logger=_logger(), path=repo_path)
    deleted = {item.path for item in service.get_deleted_files()}
    assert "README.md" in deleted


def test_repository_with_no_remote(repo_path: Path):
    service = GitService(logger=_logger(), path=repo_path)
    assert service.has_remote_origin() is False
    assert service.get_remote_origin_url() is None
    info = service.get_repository_info()
    assert info.remote_url is None
    assert info.owner is None


def test_repository_with_remote_origin(repo_path: Path):
    repo = Repo(repo_path)
    repo.create_remote("origin", "https://github.com/acme/demo.git")

    service = GitService(logger=_logger(), path=repo_path)
    assert service.has_remote_origin() is True
    assert service.get_remote_origin_url() == "https://github.com/acme/demo.git"

    meta = service.get_repository_metadata()
    assert meta.owner == "acme"
    assert meta.name == "demo"
    assert meta.full_name == "acme/demo"


def test_staged_files(repo_path: Path):
    (repo_path / "staged.py").write_text("print(1)\n", encoding="utf-8")
    repo = Repo(repo_path)
    repo.index.add(["staged.py"])

    service = GitService(logger=_logger(), path=repo_path)
    staged = service.get_staged_files()
    assert all(isinstance(item, ChangedPath) for item in staged)
    assert "staged.py" in {item.path for item in staged}


def test_commit_metadata(repo_path: Path):
    service = GitService(logger=_logger(), path=repo_path)
    commit = service.get_current_commit()
    assert commit is not None
    assert commit.message == "initial commit"
    assert commit.author_name == "Test User"
    assert commit.author_email == "test@example.com"
    assert len(commit.sha) == 40
    assert len(commit.short_sha) == 7
    assert commit.committed_at is not None


def test_local_branches(repo_path: Path):
    repo = Repo(repo_path)
    repo.create_head("feature/login")
    service = GitService(logger=_logger(), path=repo_path)
    branches = service.get_local_branches()
    assert "main" in branches
    assert "feature/login" in branches


def test_changed_files_vs_default_branch(repo_path: Path):
    repo = Repo(repo_path)
    repo.git.checkout("-b", "feature/login")
    (repo_path / "auth.py").write_text("def login(): ...\n", encoding="utf-8")
    repo.index.add(["auth.py"])
    repo.index.commit("add auth")

    service = GitService(logger=_logger(), path=repo_path)
    assert service.get_current_branch() == "feature/login"

    changes = service.get_changed_files_vs_default_branch()
    paths = {change.path for change in changes}
    assert "auth.py" in paths


def test_unified_diff_vs_default_branch(repo_path: Path):
    repo = Repo(repo_path)
    (repo_path / "auth.py").write_text("def login():\n    return False\n", encoding="utf-8")
    repo.index.add(["auth.py"])
    repo.index.commit("add auth baseline")

    repo.git.checkout("-b", "feature/login")
    (repo_path / "auth.py").write_text(
        "def login():\n    return True\n",
        encoding="utf-8",
    )
    repo.index.add(["auth.py"])
    repo.index.commit("flip login return")

    service = GitService(logger=_logger(), path=repo_path)
    diff = service.get_unified_diff_vs_default_branch()
    assert diff.strip()
    assert "diff --git" in diff
    assert "auth.py" in diff
    assert "-    return False" in diff or "-    return False\n" in diff
    assert "+    return True" in diff or "+    return True\n" in diff


def test_invalid_git_repository_error_is_mapped(repo_path: Path, mocker):
    from git import InvalidGitRepositoryError

    service = GitService(logger=_logger(), path=repo_path)
    mocker.patch(
        "refactory.git.service.Repo",
        side_effect=InvalidGitRepositoryError("nope"),
    )
    with pytest.raises(RepositoryNotFound):
        service.require_repository()

    mocker.patch(
        "refactory.git.service.Repo",
        side_effect=RuntimeError("unexpected git failure"),
    )
    with pytest.raises(RefactoryError, match="Failed to open Git repository"):
        service.require_repository()


def test_get_repository_info_includes_working_tree(repo_path: Path):
    (repo_path / "auth.py").write_text("x = 1\n", encoding="utf-8")
    service = GitService(logger=_logger(), path=repo_path)
    info = service.get_repository_info()
    assert info.working_tree.is_dirty is True
    assert info.working_tree.changed_file_count >= 1
    assert info.commit is not None
    assert info.commit.message == "initial commit"


def test_uses_cwd_when_path_omitted(repo_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(repo_path)
    service = GitService(logger=_logger())
    assert service.repository_root() == repo_path.resolve()
    assert service.get_repository_name() == "demo-repo"


def test_change_kind_enum_values():
    assert ChangeKind.MODIFIED.value == "modified"
