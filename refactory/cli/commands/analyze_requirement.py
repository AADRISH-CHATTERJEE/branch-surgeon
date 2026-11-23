"""`refactory analyze-requirement` — Requirement Impact Analysis."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import typer
from typing_extensions import Annotated

from refactory.cli.commands._common import get_container, handle_error, warn_if_index_stale
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading
from refactory.cli.ui.style import format_ms
from refactory.requirement.models import (
    RequirementAnalysis,
    RequirementCandidate,
    RequirementImpact,
    RequirementRequest,
)


_DEFAULT_TRUNCATE_LEN = 500


def analyze_requirement_cmd(
    file: Annotated[
        str | None,
        typer.Argument(
            help="Path to a requirement text file. Omit to type interactively.",
        ),
    ] = None,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show detailed candidate and impact info"),
    ] = False,
    truncate: Annotated[
        int,
        typer.Option("--truncate", help="Max characters for requirement display"),
    ] = _DEFAULT_TRUNCATE_LEN,
) -> None:
    """Analyze a plain-English requirement against the local repository."""
    try:
        raw_text = _read_requirement(file)
        if not raw_text:
            console.print("No requirement text provided.")
            raise typer.Exit(code=1)

        container = get_container()
        warn_if_index_stale(container)

        started = time.perf_counter()
        with loading("Analyzing requirement..."):
            analysis = container.requirement_analysis_service.analyze(
                RequirementRequest(raw_text=raw_text)
            )
        elapsed = (time.perf_counter() - started) * 1000.0

        if output_json:
            console.print(analysis.model_dump_json(indent=2))
        else:
            _render(
                analysis,
                verbose=verbose,
                elapsed_ms=elapsed,
                raw_text=raw_text,
                truncate_len=truncate,
            )
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _read_requirement(file: str | None) -> str:
    """Read from file path, or prompt interactively."""
    if file:
        path = Path(file)
        if not path.is_file():
            console.print(f"File not found: {file}")
            raise typer.Exit(code=1)
        return path.read_text(encoding="utf-8", errors="replace").strip()

    if not sys.stdin.isatty():
        return sys.stdin.read().strip()

    console.print("Paste requirement (end with an empty line):\n")
    lines: list[str] = []
    try:
        while True:
            line = input()
            if not line and lines:
                break
            lines.append(line)
    except EOFError:
        pass
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_SEV_TAG = {
    "low": "LOW    ",
    "medium": "MEDIUM ",
    "high": "HIGH   ",
    "critical": "CRITICAL",
}


def _render(
    analysis: RequirementAnalysis,
    *,
    verbose: bool,
    elapsed_ms: float,
    raw_text: str = "",
    truncate_len: int = _DEFAULT_TRUNCATE_LEN,
) -> None:
    display_text = raw_text.strip() if raw_text else ""
    if display_text and len(display_text) > truncate_len:
        display_text = display_text[:truncate_len] + "..."

    lines: list[str] = [
        "",
        "Requirement Impact Analysis",
        "===========================",
        "",
        "Requirement",
        "-----------",
        display_text or analysis.summary or "(empty)",
        "",
        "Summary",
        "-------",
        analysis.summary or "(empty)",
        "",
    ]

    if analysis.features:
        lines.append("Detected Features")
        lines.append("-----------------")
        for feat in analysis.features:
            lines.append(f"  {feat}")
        lines.append("")

    if verbose and analysis.keywords:
        lines.append("Keywords")
        lines.append("--------")
        lines.append(f"  {', '.join(analysis.keywords[:20])}")
        lines.append("")

    if analysis.candidate_files:
        lines.append("Candidate Files")
        lines.append("---------------")
        for c in analysis.candidate_files[:15]:
            conf_str = f"  ({c.confidence:.2f})" if verbose else ""
            lines.append(f"  {c.path}{conf_str}")
            if verbose and c.reasons:
                lines.append(f"    reasons: {', '.join(c.reasons[:5])}")
        if len(analysis.candidate_files) > 15:
            lines.append(f"  ... and {len(analysis.candidate_files) - 15} more")
        lines.append("")

    if analysis.impacted_files:
        lines.append("Impact")
        lines.append("------")
        for impact in analysis.impacted_files[:15]:
            sev = _SEV_TAG.get(impact.severity, impact.severity.upper())
            lines.append(f"  [{sev}]  {impact.file}")
            if verbose and impact.why:
                lines.append(f"           {impact.why}")
        if len(analysis.impacted_files) > 15:
            lines.append(f"  ... and {len(analysis.impacted_files) - 15} more")
        lines.append("")

    if analysis.impacted_tests:
        lines.append("Tests")
        lines.append("-----")
        for t in analysis.impacted_tests[:10]:
            lines.append(f"  {t}")
        if len(analysis.impacted_tests) > 10:
            lines.append(f"  ... and {len(analysis.impacted_tests) - 10} more")
        lines.append("")

    if analysis.impacted_docs:
        lines.append("Documentation")
        lines.append("-------------")
        for d in analysis.impacted_docs:
            lines.append(f"  {d}")
        lines.append("")

    if verbose and analysis.configuration_files:
        lines.append("Configuration Files")
        lines.append("-------------------")
        for c in analysis.configuration_files:
            lines.append(f"  {c}")
        lines.append("")

    if verbose and analysis.database_files:
        lines.append("Database Files")
        lines.append("--------------")
        for d in analysis.database_files:
            lines.append(f"  {d}")
        lines.append("")

    lines.append("Assessment")
    lines.append("----------")
    lines.append(f"  Complexity  : {analysis.complexity.value.replace('_', ' ').title()}")
    lines.append(f"  Risk        : {analysis.risk.value.title()}")
    lines.append(f"  Confidence  : {analysis.confidence:.2f}")
    lines.append("")

    if analysis.implementation_plan:
        lines.append("Implementation Plan")
        lines.append("-------------------")
        for idx, step in enumerate(analysis.implementation_plan, 1):
            lines.append(f"  {idx}  {step}")
        lines.append("")

    if analysis.notes:
        lines.append("Notes")
        lines.append("-----")
        for note in analysis.notes:
            lines.append(f"  {note}")
        lines.append("")

    lines.append(f"Analysis completed in {format_ms(elapsed_ms)}")
    lines.append("")

    console.print("\n".join(lines))
