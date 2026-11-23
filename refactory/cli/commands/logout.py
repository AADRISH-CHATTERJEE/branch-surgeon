"""`refactory logout` — clear locally stored backend JWTs."""

from __future__ import annotations

from refactory.backend.auth import TokenStore
from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console


def logout() -> None:
    """Remove ~/.refactory/auth.json (does not call the backend)."""
    try:
        container = get_container()
        client = container.get_backend_client()
        store = client.token_store if client is not None else TokenStore()
        path = store.path
        if store.clear():
            console.print(f"[green]Logged out.[/green] Removed {path}")
        else:
            console.print(f"[yellow]Already logged out.[/yellow] No auth file at {path}")
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
