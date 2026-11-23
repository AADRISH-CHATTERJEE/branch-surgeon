"""`refactory docgen` — AI-powered documentation generation."""

from __future__ import annotations

from pathlib import Path

import typer

from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading


def docgen_cmd(
    file: str = typer.Argument(..., help="Source file to generate documentation for."),
    kind: str = typer.Option("module", "--kind", "-k", help="Doc kind: module, function, class, api, readme."),
    output: str = typer.Option(None, "--output", "-o", help="Write docs to file instead of stdout."),
) -> None:
    """Generate documentation for a source file."""
    try:
        container = get_container()
        root = Path(container.git_service.get_root_path()).resolve()
        target = root / file

        if not target.exists():
            console.print(f"[red]File not found: {file}[/red]")
            raise typer.Exit(1)

        content = target.read_text(encoding="utf-8", errors="replace")

        with loading("Generating documentation…"):
            result = container.ai_intelligence_service.generate_docs(
                file, content, kind=kind,
            )

        for doc in result.docs:
            if output:
                Path(output).write_text(doc.content, encoding="utf-8")
                console.print(f"Documentation written to {output}")
            else:
                console.print(doc.content)

        console.print(f"\nModel: {result.model}")

    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
