"""`refactory missing-docs` — missing docstrings / READMEs."""

from __future__ import annotations

import time

from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading
from refactory.cli.ui.style import format_ms


def missing_docs_cmd() -> None:
    """List missing module/class/function docstrings and package READMEs."""
    try:
        container = get_container()
        service = container.documentation_service
        started = time.perf_counter()
        with loading("Finding missing documentation…"):
            gaps = service.find_missing_docstrings()
            readmes = service.find_missing_readmes()
        lines = [
            "====================================",
            "",
            "Missing Documentation",
            "",
            "====================================",
            "",
            f"Docstring gaps: {len(gaps)}",
            f"Missing READMEs: {len(readmes)}",
            f"Elapsed: {format_ms((time.perf_counter() - started) * 1000.0)}",
            "",
            "Docstrings",
            "",
        ]
        if gaps:
            for gap in gaps[:50]:
                sym = f"::{gap.symbol}" if gap.symbol else ""
                lines.append(f"  {gap.path}{sym}  [{gap.kind.value}]")
        else:
            lines.append("  (none)")
        lines.extend(["", "READMEs", ""])
        if readmes:
            for gap in readmes[:50]:
                lines.append(f"  {gap.path}/")
        else:
            lines.append("  (none)")
        lines.extend(["", "===================================="])
        console.print("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
