"""`refactory review` — presentation adapter over ReviewEngine."""

from __future__ import annotations

import typer

from refactory.cli.commands._common import get_container, handle_error, warm_backend_client
from refactory.cli.ui.progress import loading
from refactory.cli.ui.report import render_review_report


def review(
    pr: int = typer.Argument(..., help="Pull request number (or local review target id)"),
) -> None:
    """Delegate review orchestration to ReviewEngine (no business logic here)."""
    try:
        container = get_container()
        warm_backend_client(container)
        with loading(f"Reviewing PR #{pr}…"):
            result = container.review_engine.review(pr)
        render_review_report(result)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
