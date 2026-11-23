"""Tests for the temporary `refactory git-info` CLI command."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from typer.testing import CliRunner

from refactory.cli.app import app
from refactory.git.models import GitCommitInfo, GitRepositoryInfo, WorkingTreeStatus


runner = CliRunner()


def test_git_info_command_renders_repository_snapshot(mocker):
    info = GitRepositoryInfo(
        root_path=r"C:\Users\ADMIN\Documents\demo-repo",
        name="demo-repo",
        current_branch="feature/login",
        head_sha="3f9b27abcdef",
        commit=GitCommitInfo(
            sha="3f9b27abcdef0000000000000000000000000000",
            short_sha="3f9b27a",
            message="add login",
            author_name="Ada",
            author_email="ada@example.com",
            committed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        remote_url=None,
        default_branch="main",
        is_dirty=True,
        working_tree=WorkingTreeStatus(
            is_dirty=True,
            modified_files=[],
            untracked_files=["tests/test_auth.py"],
            changed_file_count=1,
        ),
    )
    # Attach a modified file model after import to avoid circular typing in fixture.
    from refactory.git.models import ChangedPath, ChangeKind

    info.working_tree.modified_files = [
        ChangedPath(path="auth.py", kind=ChangeKind.MODIFIED)
    ]

    git_service = MagicMock()
    git_service.get_repository_info.return_value = info
    container = MagicMock()
    container.git_service = git_service
    mocker.patch("refactory.cli.commands.git_info.get_container", return_value=container)

    result = runner.invoke(app, ["git-info"])

    assert result.exit_code == 0
    assert "demo-repo" in result.stdout
    assert "feature/login" in result.stdout
    assert "3f9b27a" in result.stdout
    assert "auth.py" in result.stdout
    assert "tests/test_auth.py" in result.stdout
    assert "Dirty" in result.stdout
    git_service.get_repository_info.assert_called_once()
