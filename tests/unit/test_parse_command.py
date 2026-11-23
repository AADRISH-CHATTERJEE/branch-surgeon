"""Tests for temporary `refactory parse` CLI command."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from typer.testing import CliRunner

from refactory.cli.app import app
from refactory.parser.models import (
    FileMetadata,
    ParsedClass,
    ParsedFile,
    ParsedFunction,
    ParsedImport,
    ParsedModule,
    ImportKind,
)


runner = CliRunner()


def test_parse_command_renders_structure(mocker, tmp_path: Path):
    target = tmp_path / "auth.py"
    target.write_text("def validate():\n    pass\n", encoding="utf-8")

    parsed = ParsedFile(
        metadata=FileMetadata(
            path="auth.py",
            language="python",
            line_count=2,
            content_hash="abc",
            last_modified=datetime.now(timezone.utc),
        ),
        module=ParsedModule(
            name="auth",
            functions=[
                ParsedFunction(
                    name="outer",
                    start_line=1,
                    end_line=4,
                    nested_functions=[
                        ParsedFunction(
                            name="inner",
                            start_line=2,
                            end_line=3,
                            parent_function="outer",
                        )
                    ],
                ),
                ParsedFunction(
                    name="login",
                    start_line=5,
                    end_line=6,
                    decorators=['app.route("/login")'],
                ),
                ParsedFunction(name="validate", start_line=7, end_line=8),
                ParsedFunction(name="logout", start_line=9, end_line=10),
            ],
            classes=[
                ParsedClass(
                    name="AuthService",
                    start_line=12,
                    end_line=16,
                    methods=[
                        ParsedFunction(
                            name="login",
                            start_line=13,
                            end_line=15,
                            is_method=True,
                            decorators=["staticmethod"],
                        )
                    ],
                )
            ],
            imports=[
                ParsedImport(
                    module="jwt",
                    names=["jwt"],
                    kind=ImportKind.THIRD_PARTY,
                    start_line=1,
                    end_line=1,
                ),
                ParsedImport(
                    module="middleware",
                    names=["middleware"],
                    kind=ImportKind.LOCAL,
                    start_line=2,
                    end_line=2,
                ),
            ],
        ),
    )

    parser = MagicMock()
    parser.parse_file.return_value = parsed
    container = MagicMock()
    container.parser_service = parser
    mocker.patch("refactory.cli.commands.parse.get_container", return_value=container)

    result = runner.invoke(app, ["parse", str(target)])

    assert result.exit_code == 0
    assert "auth" in result.stdout
    assert "outer()" in result.stdout
    assert "inner()" in result.stdout
    assert "parent=outer" in result.stdout
    assert '@app.route("/login")' in result.stdout
    assert "login()" in result.stdout
    assert "validate()" in result.stdout
    assert "AuthService" in result.stdout
    assert "@staticmethod" in result.stdout
    assert "jwt" in result.stdout
    parser.parse_file.assert_called_once()
