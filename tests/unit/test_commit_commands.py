"""CLI presentation tests for commit / history commands."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from typer.testing import CliRunner

from refactory.cli.app import app
from refactory.git.models import (
    ChangeKind,
    CommitDetail,
    CommitDiff,
    CommitFileChange,
    CommitStatistics,
    CommitSummary,
)

runner = CliRunner()


def test_commit_command_renders_metadata_and_diff(mocker):
    detail = CommitDetail(
        sha="a" * 40,
        short_sha="aaaaaaa",
        message="fix login",
        author_name="Ada",
        author_email="ada@example.com",
        committed_at=datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc),
        parent_shas=["b" * 40],
        is_merge=False,
    )
    diff = CommitDiff(
        sha=detail.sha,
        patch="diff --git a/auth.py b/auth.py\n+pass\n",
        files=[
            CommitFileChange(
                path="auth.py",
                kind=ChangeKind.MODIFIED,
                insertions=1,
                deletions=0,
                patch="+pass\n",
            )
        ],
        statistics=CommitStatistics(files_changed=1, insertions=1, deletions=0),
    )
    service = MagicMock()
    service.get_commit.return_value = detail
    service.get_commit_diff.return_value = diff
    container = MagicMock()
    container.commit_service = service
    mocker.patch("refactory.cli.commands.commit.get_container", return_value=container)

    result = runner.invoke(app, ["commit", "aaaaaaa"])

    assert result.exit_code == 0, result.output
    service.get_commit.assert_called_once_with("aaaaaaa")
    service.get_commit_diff.assert_called_once_with("aaaaaaa")
    assert "fix login" in result.output
    assert "Ada <ada@example.com>" in result.output
    assert "auth.py" in result.output
    assert "Files changed: 1" in result.output
    assert "Diff Summary" in result.output


def test_history_command_lists_commits(mocker):
    commits = [
        CommitSummary(
            sha="c" * 40,
            short_sha="ccccccc",
            message="latest",
            author_name="Bob",
            author_email="bob@example.com",
            committed_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        ),
        CommitSummary(
            sha="d" * 40,
            short_sha="ddddddd",
            message="earlier",
            author_name="Bob",
            author_email="bob@example.com",
            committed_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        ),
    ]
    service = MagicMock()
    service.get_recent_commits.return_value = commits
    container = MagicMock()
    container.commit_service = service
    mocker.patch("refactory.cli.commands.history.get_container", return_value=container)

    result = runner.invoke(app, ["history", "--limit", "5"])

    assert result.exit_code == 0, result.output
    service.get_recent_commits.assert_called_once_with(limit=5)
    assert "ccccccc" in result.output
    assert "latest" in result.output
    assert "Bob <bob@example.com>" in result.output
    assert "earlier" in result.output


def test_history_empty_repository(mocker):
    service = MagicMock()
    service.get_recent_commits.return_value = []
    container = MagicMock()
    container.commit_service = service
    mocker.patch("refactory.cli.commands.history.get_container", return_value=container)

    result = runner.invoke(app, ["history"])

    assert result.exit_code == 0, result.output
    assert "(no commits)" in result.output
