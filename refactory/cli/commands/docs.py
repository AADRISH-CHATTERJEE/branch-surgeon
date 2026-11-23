"""`refactory docs [path]` — repository / file documentation overview."""

from __future__ import annotations

import time

import typer

from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading
from refactory.cli.ui.style import format_ms
from refactory.documentation.models import FileDocsReport, RepositoryDocsReport


def docs_cmd(
    path: str | None = typer.Argument(
        None,
        help="Optional file path. Omit for full repository documentation overview.",
    ),
) -> None:
    """Analyze documentation for the repository or a single file."""
    try:
        container = get_container()
        service = container.documentation_service
        started = time.perf_counter()
        if path:
            with loading(f"Analyzing docs for {path}…"):
                report = service.analyze_file_docs(path)
            _render_file(report, elapsed_ms=(time.perf_counter() - started) * 1000.0)
        else:
            with loading("Analyzing repository documentation…"):
                report = service.analyze_repository_docs()
            _render_repo(report, elapsed_ms=(time.perf_counter() - started) * 1000.0)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _render_repo(report: RepositoryDocsReport, *, elapsed_ms: float) -> None:
    cov = report.coverage
    lines = [
        "====================================",
        "",
        "Documentation Overview",
        "",
        "====================================",
        "",
        "Root:",
        report.root,
        "",
        f"Modules: {report.module_count}",
        f"Overall coverage: {cov.overall_coverage:.2%}",
        f"Module coverage:  {cov.module_coverage:.2%}",
        f"Class coverage:   {cov.class_coverage:.2%}",
        f"Function coverage:{cov.function_coverage:.2%}",
        f"Public API:       {cov.public_api_coverage:.2%}",
        f"Missing READMEs:  {cov.packages_missing_readme}",
        f"Elapsed: {format_ms(elapsed_ms)}",
        "",
        "====================================",
        "",
        "Top missing docstrings",
        "",
    ]
    if report.missing_docstrings:
        for gap in report.missing_docstrings[:20]:
            sym = f"::{gap.symbol}" if gap.symbol else ""
            lines.append(f"  {gap.path}{sym}  [{gap.kind.value}]  {gap.reason}")
    else:
        lines.append("  (none)")

    lines.extend(["", "===================================="])
    console.print("\n".join(lines))


def _render_file(report: FileDocsReport, *, elapsed_ms: float) -> None:
    lines = [
        "====================================",
        "",
        "File Documentation",
        "",
        "====================================",
        "",
        "Path:",
        report.path,
        "",
        f"Coverage: {report.coverage:.2%}",
        f"Elapsed: {format_ms(elapsed_ms)}",
        "",
    ]
    if report.module:
        lines.extend(
            [
                "Module:",
                report.module.module_name,
                "",
                "Docstring:",
                (report.module.docstring or "(none)")[:200],
                "",
                "Public API:",
                ", ".join(report.module.public_api) if report.module.public_api else "(none)",
                "",
            ]
        )
    lines.extend(["Gaps", ""])
    if report.gaps:
        for gap in report.gaps:
            sym = f"::{gap.symbol}" if gap.symbol else ""
            lines.append(f"  {gap.path}{sym}  {gap.reason}")
    else:
        lines.append("  (none)")
    lines.extend(["", "===================================="])
    console.print("\n".join(lines))
