"""Temporary development command: `refactory parse <file>`.

Presentation-only — invokes ParserService and prints structured results.
"""

from __future__ import annotations

from pathlib import Path

import typer

from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console
from refactory.parser.models import ParsedFile, ParsedFunction


def parse(
    file: Path = typer.Argument(..., exists=False, help="Source file to parse, e.g. auth.py"),
) -> None:
    """Parse a source file and print module structure (no AI)."""
    try:
        container = get_container()
        path = file if file.is_absolute() else (Path.cwd() / file)
        parsed = container.parser_service.parse_file(path, repo_root=Path.cwd())
        _render(parsed)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _format_function(fn: ParsedFunction) -> str:
    suffix = " (async)" if fn.is_async else ""
    gen = " [generator]" if fn.is_generator else ""
    parent = f"  parent={fn.parent_function}" if fn.parent_function else ""
    return f"{fn.name}(){suffix}{gen}{parent}"


def _render_function_tree(fn: ParsedFunction, *, indent: int, lines: list[str]) -> None:
    prefix = "  " * indent
    for decorator in fn.decorators:
        lines.append(f"{prefix}@{decorator}")
    lines.append(f"{prefix}{_format_function(fn)}")
    for nested in fn.nested_functions:
        _render_function_tree(nested, indent=indent + 1, lines=lines)


def _render(parsed: ParsedFile) -> None:
    module = parsed.module
    lines = [
        "====================================",
        "",
        "Parsed File",
        "",
        "====================================",
        "",
        "Module",
        "",
        module.name,
        "",
        "Language",
        "",
        parsed.metadata.language,
        "",
        "Functions",
        "",
    ]
    if module.functions:
        for fn in module.functions:
            _render_function_tree(fn, indent=0, lines=lines)
    else:
        lines.append("(none)")

    lines.extend(["", "Classes", ""])
    if module.classes:
        for cls in module.classes:
            for decorator in cls.decorators:
                lines.append(f"@{decorator}")
            lines.append(cls.name)
            for method in cls.methods:
                for decorator in method.decorators:
                    lines.append(f"  @{decorator}")
                lines.append(f"  .{_format_function(method)}")
                for nested in method.nested_functions:
                    _render_function_tree(nested, indent=2, lines=lines)
    else:
        lines.append("(none)")

    lines.extend(["", "Imports", ""])
    if module.imports:
        for item in module.imports:
            if item.is_from_import:
                names = ", ".join(item.names) if item.names else "*"
                lines.append(f"from {item.module} import {names}  [{item.kind.value}]")
            else:
                alias = f" as {item.alias}" if item.alias else ""
                lines.append(f"import {item.module}{alias}  [{item.kind.value}]")
    else:
        lines.append("(none)")

    lines.extend(["", "Comments / Tags", ""])
    tagged = [c for c in module.comments if c.tag.value != "NONE"]
    if tagged:
        for comment in tagged:
            lines.append(f"{comment.tag.value}: {comment.text}")
    else:
        lines.append("(none)")

    lines.extend(
        [
            "",
            f"Lines: {parsed.metadata.line_count}",
            f"Syntax errors: {parsed.has_syntax_errors}",
            "",
            "====================================",
        ]
    )
    console.print("\n".join(lines))
