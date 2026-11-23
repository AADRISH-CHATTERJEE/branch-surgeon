"""`refactory testgen` — AI-powered test skeleton generation."""

from __future__ import annotations

from pathlib import Path

import typer

from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading


def testgen_cmd(
    file: str = typer.Argument(..., help="Source file to generate tests for."),
    output: str = typer.Option(None, "--output", "-o", help="Write tests to file instead of stdout."),
) -> None:
    """Generate pytest test skeletons for a source file."""
    try:
        container = get_container()
        root = Path(container.git_service.get_root_path()).resolve()
        target = root / file

        if not target.exists():
            console.print(f"[red]File not found: {file}[/red]")
            raise typer.Exit(1)

        content = target.read_text(encoding="utf-8", errors="replace")

        with loading("Generating tests…"):
            result = container.ai_intelligence_service.generate_tests(file, content)

        for test in result.tests:
            if output:
                Path(output).write_text(test.test_code, encoding="utf-8")
                console.print(f"Tests written to {output}")
            else:
                console.print(f"\n# {test.file_path}\n")
                console.print(test.test_code)

        console.print(f"\nModel: {result.model}")

    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
