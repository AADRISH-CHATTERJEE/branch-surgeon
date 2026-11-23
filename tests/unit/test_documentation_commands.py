"""CLI presentation tests for documentation intelligence."""

from __future__ import annotations

from unittest.mock import MagicMock

from typer.testing import CliRunner

from refactory.cli.app import app
from refactory.documentation.models import (
    DocGap,
    DocTargetKind,
    DocumentationCoverage,
    FileDocsReport,
    ModuleSummary,
    PackageNode,
    RepositoryDocsReport,
    RepositoryStructure,
    StaleDoc,
)

runner = CliRunner()


def test_docs_repo_command(mocker):
    service = MagicMock()
    service.analyze_repository_docs.return_value = RepositoryDocsReport(
        root="/tmp/demo",
        coverage=DocumentationCoverage(overall_coverage=0.55, module_coverage=0.6),
        missing_docstrings=[
            DocGap(path="auth.py", symbol="login", kind=DocTargetKind.FUNCTION, reason="missing")
        ],
        module_count=3,
    )
    container = MagicMock()
    container.documentation_service = service
    mocker.patch("refactory.cli.commands.docs.get_container", return_value=container)

    result = runner.invoke(app, ["docs"])
    assert result.exit_code == 0, result.output
    assert "Documentation Overview" in result.output
    assert "auth.py" in result.output


def test_docs_file_command(mocker):
    service = MagicMock()
    service.analyze_file_docs.return_value = FileDocsReport(
        path="auth.py",
        module=ModuleSummary(path="auth.py", module_name="auth", docstring="Auth module"),
        gaps=[],
        coverage=1.0,
    )
    container = MagicMock()
    container.documentation_service = service
    mocker.patch("refactory.cli.commands.docs.get_container", return_value=container)

    result = runner.invoke(app, ["docs", "auth.py"])
    assert result.exit_code == 0, result.output
    service.analyze_file_docs.assert_called_once_with("auth.py")
    assert "auth.py" in result.output


def test_missing_docs_command(mocker):
    service = MagicMock()
    service.find_missing_docstrings.return_value = [
        DocGap(path="a.py", symbol="f", kind=DocTargetKind.FUNCTION)
    ]
    service.find_missing_readmes.return_value = [
        DocGap(path="pkg", kind=DocTargetKind.README)
    ]
    container = MagicMock()
    container.documentation_service = service
    mocker.patch("refactory.cli.commands.missing_docs.get_container", return_value=container)

    result = runner.invoke(app, ["missing-docs"])
    assert result.exit_code == 0, result.output
    assert "a.py" in result.output
    assert "pkg" in result.output


def test_stale_docs_command(mocker):
    service = MagicMock()
    service.find_stale_documentation.return_value = [
        StaleDoc(path="README.md", related_source="auth.py", confidence=0.8, reason="older")
    ]
    container = MagicMock()
    container.documentation_service = service
    mocker.patch("refactory.cli.commands.stale_docs.get_container", return_value=container)

    result = runner.invoke(app, ["stale-docs"])
    assert result.exit_code == 0, result.output
    assert "README.md" in result.output


def test_api_docs_command(mocker):
    service = MagicMock()
    service.find_public_api_without_docs.return_value = [
        DocGap(path="auth.py", symbol="User", kind=DocTargetKind.CLASS)
    ]
    service.find_documentation_coverage.return_value = DocumentationCoverage(
        public_api_coverage=0.4
    )
    container = MagicMock()
    container.documentation_service = service
    mocker.patch("refactory.cli.commands.api_docs.get_container", return_value=container)

    result = runner.invoke(app, ["api-docs"])
    assert result.exit_code == 0, result.output
    assert "User" in result.output


def test_repo_structure_command(mocker):
    service = MagicMock()
    service.build_repository_structure.return_value = RepositoryStructure(
        root="/tmp/demo",
        packages=[PackageNode(path="pkg", modules=["pkg/util.py"], has_readme=True)],
        top_level_modules=["auth.py"],
        readme_files=["README.md", "pkg/README.md"],
    )
    container = MagicMock()
    container.documentation_service = service
    mocker.patch("refactory.cli.commands.repo_structure.get_container", return_value=container)

    result = runner.invoke(app, ["repo-structure"])
    assert result.exit_code == 0, result.output
    assert "pkg" in result.output


def test_help_lists_docs_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("docs", "missing-docs", "stale-docs", "api-docs", "repo-structure"):
        assert name in result.output
