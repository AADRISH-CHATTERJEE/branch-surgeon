"""`refactory patch` — generate unified git patches via AI."""

from __future__ import annotations

from pathlib import Path

import typer

from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading


def patch_cmd(
    file: str = typer.Argument(..., help="File to generate a patch for."),
    suggestion: str = typer.Option(
        "Improve code quality",
        "--suggestion", "-s",
        help="Description of the change to generate.",
    ),
    output: str = typer.Option(None, "--output", "-o", help="Write patch to file instead of stdout."),
) -> None:
    """Generate a unified git patch for a file (never modifies files directly)."""
    try:
        container = get_container()
        root = Path(container.git_service.get_root_path()).resolve()
        target = root / file

        if not target.exists():
            console.print(f"[red]File not found: {file}[/red]")
            raise typer.Exit(1)

        content = target.read_text(encoding="utf-8", errors="replace")

        with loading("Generating patch…"):
            result = container.ai_intelligence_service.generate_patch(
                file, content, suggestion,
            )

        for patch in result.patches:
            if output:
                Path(output).write_text(patch.unified_diff, encoding="utf-8")
                console.print(f"Patch written to {output}")
            else:
                console.print(patch.unified_diff)

    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
