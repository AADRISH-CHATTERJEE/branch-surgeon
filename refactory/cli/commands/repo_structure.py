"""`refactory repo-structure` — deterministic repository structure view."""

from __future__ import annotations

import time

from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading
from refactory.cli.ui.style import format_ms
from refactory.documentation.models import RepositoryStructure


def repo_structure_cmd() -> None:
    """Show package/module structure and README presence."""
    try:
        container = get_container()
        started = time.perf_counter()
        with loading("Building repository structure…"):
            structure = container.documentation_service.build_repository_structure()
        _render(structure, elapsed_ms=(time.perf_counter() - started) * 1000.0)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _render(structure: RepositoryStructure, *, elapsed_ms: float) -> None:
    lines = [
        "====================================",
        "",
        "Repository Structure",
        "",
        "====================================",
        "",
        "Root:",
        structure.root,
        "",
        f"Packages: {len(structure.packages)}",
        f"Top-level modules: {len(structure.top_level_modules)}",
        f"READMEs: {len(structure.readme_files)}",
        f"Elapsed: {format_ms(elapsed_ms)}",
        "",
        "====================================",
        "",
    ]
    for package in structure.packages[:40]:
        flags = []
        if package.has_readme:
            flags.append("readme")
        if package.has_init:
            flags.append("pkg")
        flag_text = f" [{', '.join(flags)}]" if flags else ""
        lines.append(f"{package.path}/{flag_text}")
        for module in package.modules[:8]:
            lines.append(f"  - {module}")
        if len(package.modules) > 8:
            lines.append(f"  … {len(package.modules) - 8} more")
        lines.append("")
    lines.append("====================================")
    console.print("\n".join(lines))
