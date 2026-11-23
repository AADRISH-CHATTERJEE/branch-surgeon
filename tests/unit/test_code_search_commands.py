"""CLI tests for definition / references / callers / callees / todos."""

from __future__ import annotations

from unittest.mock import MagicMock

from typer.testing import CliRunner

from refactory.cli.app import app
from refactory.codesearch.models import CodeSearchHit, CodeSearchResult

runner = CliRunner()


def _result(query: str, **hit_fields: object) -> CodeSearchResult:
    base = dict(
        file="auth.py",
        line=10,
        symbol="login",
        type="method",
        snippet="def login(self):",
        score=0.95,
        confidence=0.95,
    )
    base.update(hit_fields)
    return CodeSearchResult(
        query=query,
        hits=[CodeSearchHit(**base)],  # type: ignore[arg-type]
        structural_hits=1,
    )


def test_definition_command(mocker):
    service = MagicMock()
    service.find_definition.return_value = _result("validate_token", symbol="validate_token", type="function")
    container = MagicMock()
    container.code_search_service = service
    mocker.patch("refactory.cli.commands.definition.get_container", return_value=container)

    result = runner.invoke(app, ["definition", "validate_token"])
    assert result.exit_code == 0, result.output
    service.find_definition.assert_called_once_with("validate_token")
    assert "validate_token" in result.output
    assert "auth.py" in result.output


def test_references_command(mocker):
    service = MagicMock()
    service.find_references.return_value = _result("User", symbol="User", type="reference", file="models.py")
    container = MagicMock()
    container.code_search_service = service
    mocker.patch("refactory.cli.commands.references.get_container", return_value=container)

    result = runner.invoke(app, ["references", "User"])
    assert result.exit_code == 0, result.output
    assert "User" in result.output


def test_callers_command(mocker):
    service = MagicMock()
    service.find_callers.return_value = _result("login", file="handlers.py", type="caller")
    container = MagicMock()
    container.code_search_service = service
    mocker.patch("refactory.cli.commands.callers.get_container", return_value=container)

    result = runner.invoke(app, ["callers", "login"])
    assert result.exit_code == 0, result.output
    assert "handlers.py" in result.output


def test_callees_command(mocker):
    service = MagicMock()
    service.find_callees.return_value = _result(
        "AuthService.login",
        symbol="validate_token",
        type="callee",
    )
    container = MagicMock()
    container.code_search_service = service
    mocker.patch("refactory.cli.commands.callees.get_container", return_value=container)

    result = runner.invoke(app, ["callees", "AuthService.login"])
    assert result.exit_code == 0, result.output
    service.find_callees.assert_called_once_with("AuthService.login")
    assert "validate_token" in result.output


def test_todos_command(mocker):
    service = MagicMock()
    service.search_todos.return_value = CodeSearchResult(
        query="TODO",
        hits=[
            CodeSearchHit(
                file="auth.py",
                line=None,
                symbol="TODO",
                type="todo",
                snippet="# TODO: later",
                score=1.0,
                confidence=1.0,
            )
        ],
        structural_hits=1,
    )
    container = MagicMock()
    container.code_search_service = service
    mocker.patch("refactory.cli.commands.todos.get_container", return_value=container)

    result = runner.invoke(app, ["todos"])
    assert result.exit_code == 0, result.output
    assert "TODO" in result.output
    assert "auth.py" in result.output


def test_help_lists_navigation_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("search", "definition", "references", "callers", "callees", "todos"):
        assert name in result.output
