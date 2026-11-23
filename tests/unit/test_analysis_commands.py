"""CLI presentation tests for repository intelligence commands."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from typer.testing import CliRunner

from refactory.analysis.models import (
    AnalysisStatistics,
    BranchAnalysis,
    BranchInsight,
    FileAuthor,
    FileHistory,
    HotspotEntry,
    HotspotReport,
    RepositoryHealth,
    RepositoryOverview,
)
from refactory.cli.app import app

runner = CliRunner()


def test_repo_command(mocker):
    overview = RepositoryOverview(
        name="demo",
        root_path="/tmp/demo",
        current_branch="main",
        head_sha="a" * 40,
        statistics=AnalysisStatistics(tracked_files=3, commit_count=10, contributor_count=2),
        hotspots=HotspotReport(
            files=[HotspotEntry(path="a.py", score=9.5, modification_count=4, author_count=2)]
        ),
        health=RepositoryHealth(todo_count=1, todo_density=0.5),
        languages={"python": 2},
    )
    service = MagicMock()
    service.analyze_repository.return_value = overview
    container = MagicMock()
    container.repository_analysis_service = service
    mocker.patch("refactory.cli.commands.repo.get_container", return_value=container)

    result = runner.invoke(app, ["repo"])
    assert result.exit_code == 0, result.output
    assert "demo" in result.output
    assert "Tracked files" in result.output
    assert "a.py" in result.output


def test_hotspots_command(mocker):
    report = HotspotReport(
        files=[HotspotEntry(path="hot.py", score=12.0, modification_count=9, author_count=3, churn=40)],
        directories=[HotspotEntry(path="src", score=5.0, modification_count=4, is_directory=True)],
        high_churn_files=[HotspotEntry(path="hot.py", score=12.0, churn=40)],
    )
    service = MagicMock()
    service.get_hotspots.return_value = report
    container = MagicMock()
    container.repository_analysis_service = service
    mocker.patch("refactory.cli.commands.hotspots.get_container", return_value=container)

    result = runner.invoke(app, ["hotspots", "--limit", "5"])
    assert result.exit_code == 0, result.output
    service.get_hotspots.assert_called_once_with(limit=5)
    assert "hot.py" in result.output
    assert "High churn" in result.output


def test_branches_command(mocker):
    report = BranchAnalysis(
        active_branch="main",
        default_branch="main",
        branches=[
            BranchInsight(
                name="main",
                is_active=True,
                last_commit_sha="b" * 40,
                last_author="Ada <ada@example.com>",
                last_commit_message="init",
            ),
            BranchInsight(name="feature", ahead=2, behind=1, last_commit_sha="c" * 40),
        ],
        merged_branches=[],
        stale_branches=["old"],
    )
    service = MagicMock()
    service.get_branch_information.return_value = report
    container = MagicMock()
    container.repository_analysis_service = service
    mocker.patch("refactory.cli.commands.branches.get_container", return_value=container)

    result = runner.invoke(app, ["branches"])
    assert result.exit_code == 0, result.output
    assert "main" in result.output
    assert "feature" in result.output
    assert "Stale:" in result.output


def test_file_history_command(mocker):
    history = FileHistory(
        path="auth.py",
        exists=True,
        creation_sha="d" * 40,
        creation_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_modification_sha="e" * 40,
        last_modification_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        modification_count=3,
        authors=[FileAuthor(name="Ada", email="ada@example.com", commits=2)],
    )
    service = MagicMock()
    service.get_file_history.return_value = history
    container = MagicMock()
    container.repository_analysis_service = service
    mocker.patch("refactory.cli.commands.file_history.get_container", return_value=container)

    result = runner.invoke(app, ["file-history", "auth.py"])
    assert result.exit_code == 0, result.output
    service.get_file_history.assert_called_once_with("auth.py")
    assert "auth.py" in result.output
    assert "Ada" in result.output


def test_regression_review_commit_history_still_registered():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("review", "commit", "history", "parse", "status", "repo", "hotspots", "branches"):
        assert name in result.output
