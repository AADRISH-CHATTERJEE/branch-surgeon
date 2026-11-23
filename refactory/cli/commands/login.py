"""`refactory login` — authenticate against the control-plane backend."""

from __future__ import annotations

import typer

from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console


def login(
    email: str | None = typer.Option(
        None,
        "--email",
        "-e",
        help="Account email (prompted if omitted).",
    ),
    password: str | None = typer.Option(
        None,
        "--password",
        "-p",
        help="Account password (prompted if omitted; never stored).",
        hide_input=True,
    ),
) -> None:
    """Log in to the Refactory backend and persist JWTs under ~/.refactory/auth.json."""
    try:
        container = get_container()
        # Touch lazy client so local commands share the same wiring path.
        client = container.require_backend_client()

        resolved_email = email or typer.prompt("Email")
        resolved_password = password or typer.prompt("Password", hide_input=True)
        client.login(resolved_email.strip(), resolved_password)
        user = client.get_current_user()
        console.print(f"[green]Authenticated as[/green] {user.email}")
        console.print(f"[dim]Tokens saved to {client.token_store.path}[/dim]")
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
