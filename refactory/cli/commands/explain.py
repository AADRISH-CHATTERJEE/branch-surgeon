"""`refactory explain` — explain a file's purpose and role."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from refactory.cli.commands._common import get_container, handle_error, warn_if_index_stale
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading


def explain_cmd(
    file: str = typer.Argument(..., help="File to explain."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Explain a file's purpose, dependencies, callers, and business role."""
    try:
        container = get_container()
        warn_if_index_stale(container)

        root = Path(container.git_service.get_root_path()).resolve()

        with loading("Analyzing…"):
            index = container.indexer_service.load_index(root)
            if index is None:
                index = container.indexer_service.build_index(root)
            container.graph_service.build_graph(index)
            explanation = container.ai_intelligence_service.explain_file(file, root)

        if json_output:
            console.print(json.dumps(explanation.model_dump(), indent=2, default=str))
        else:
            lines: list[str] = [
                "",
                f"File: {explanation.file_path}",
                "",
                f"Purpose: {explanation.purpose}",
                f"Business Role: {explanation.business_role}",
                "",
            ]
            if explanation.dependencies:
                lines.append(f"Dependencies ({len(explanation.dependencies)}):")
                for dep in explanation.dependencies[:15]:
                    lines.append(f"  {dep}")
                lines.append("")
            if explanation.callers:
                lines.append(f"Callers ({len(explanation.callers)}):")
                for caller in explanation.callers[:15]:
                    lines.append(f"  {caller}")
                lines.append("")
            if explanation.callees:
                lines.append(f"Callees ({len(explanation.callees)}):")
                for callee in explanation.callees[:15]:
                    lines.append(f"  {callee}")
                lines.append("")
            console.print("\n".join(lines))

    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
