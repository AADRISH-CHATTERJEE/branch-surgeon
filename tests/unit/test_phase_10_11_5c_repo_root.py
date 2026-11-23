"""Phase 10.11.5C — repository root resolution and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from git import Repo

from refactory.api.repo_root import (
    choose_repo_root,
    validate_repository_root,
)
from refactory.core.exceptions import RepositoryNotFound


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = Repo.init(tmp_path)
    sample = tmp_path / "README.md"
    sample.write_text("demo\n", encoding="utf-8")
    repo.index.add([str(sample)])
    repo.index.commit("init")
    return tmp_path


class TestChooseRepoRoot:
    def test_header_wins_over_query_and_cwd(self, git_repo: Path, monkeypatch):
        monkeypatch.chdir(Path.cwd())
        path, source = choose_repo_root(
            x_repo_root=str(git_repo),
            query_root=str(Path.cwd()),
        )
        assert source == "x-repo-root"
        assert path == git_repo.resolve()

    def test_query_used_when_header_missing(self, git_repo: Path):
        path, source = choose_repo_root(x_repo_root=None, query_root=str(git_repo))
        assert source == "query.root"
        assert path == git_repo.resolve()

    def test_configured_before_cwd(self, git_repo: Path, monkeypatch):
        from refactory.core.config import get_settings

        monkeypatch.setenv("REFACTORY_REPO_ROOT", str(git_repo))
        get_settings.cache_clear()
        try:
            path, source = choose_repo_root(x_repo_root=None, query_root=None)
            assert source == "configured"
            assert path == git_repo.resolve()
        finally:
            monkeypatch.delenv("REFACTORY_REPO_ROOT", raising=False)
            get_settings.cache_clear()


class TestValidateRepositoryRoot:
    def test_valid_repo(self, git_repo: Path):
        assert validate_repository_root(git_repo) == git_repo.resolve()

    def test_missing_path(self, tmp_path: Path):
        missing = tmp_path / "nope"
        with pytest.raises(RepositoryNotFound, match="does not exist"):
            validate_repository_root(missing)

    def test_not_a_git_root(self, tmp_path: Path):
        with pytest.raises(RepositoryNotFound, match="not a Git repository"):
            validate_repository_root(tmp_path)

    def test_empty_git_no_head(self, tmp_path: Path):
        Repo.init(tmp_path)
        with pytest.raises(RepositoryNotFound, match="Unable to determine HEAD"):
            validate_repository_root(tmp_path)

    def test_rejects_parent_walk_trap(self, git_repo: Path, tmp_path: Path):
        """A nested non-git folder must not silently attach to a parent repo."""
        nested = git_repo / "nested_pkg"
        nested.mkdir()
        # validate requires .git on the path itself
        with pytest.raises(RepositoryNotFound, match="not a Git repository"):
            validate_repository_root(nested)
