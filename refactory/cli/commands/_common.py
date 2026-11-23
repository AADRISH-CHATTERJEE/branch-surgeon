"""Shared CLI helpers (error mapping only — no domain logic)."""

from __future__ import annotations

from pathlib import Path

import typer

from refactory.cli.ui.console import console
from refactory.core.config import Settings, get_settings
from refactory.core.container import ServiceContainer, build_container
from refactory.core.exceptions import RefactoryError

# Session-scoped settings after optional remote control-plane overlay.
_startup_settings: Settings | None = None
_remote_cli_config = None


def set_startup_settings(
    settings: Settings,
    *,
    remote_config: object | None = None,
) -> None:
    """Record settings resolved during CLI startup (local or remote overlay)."""
    global _startup_settings, _remote_cli_config
    _startup_settings = settings
    _remote_cli_config = remote_config


def get_startup_settings() -> Settings:
    return _startup_settings or get_settings()


def get_remote_cli_config() -> object | None:
    return _remote_cli_config


def reset_startup_settings_for_tests() -> None:
    global _startup_settings, _remote_cli_config
    _startup_settings = None
    _remote_cli_config = None


def get_container() -> ServiceContainer:
    return build_container(settings=get_startup_settings())


def warm_backend_client(container: ServiceContainer) -> None:
    """Lazily construct BackendClient when configured (no network / login required)."""
    container.get_backend_client()


def warn_if_index_stale(container: ServiceContainer) -> None:
    """Warn when on-disk sources diverge from the persisted repository index."""
    try:
        root = Path(container.git_service.get_root_path())
        info = container.indexer_service.assess_staleness(root)
    except Exception:  # noqa: BLE001 — never block the command on a warning
        return
    if not info.get("is_stale"):
        return
    indexed = info.get("indexed_files", 0)
    current = info.get("current_files", 0)
    console.print(
        "[yellow]Repository contents have changed since the last index.[/yellow]"
    )
    console.print(f"Indexed:\n{indexed} files")
    console.print(f"\nCurrent:\n{current} files")
    console.print("\nRun:\n\nrefactory index\n")


def handle_error(exc: Exception) -> None:
    if isinstance(exc, NotImplementedError):
        console.print(f"[yellow]Not implemented yet:[/yellow] {exc}")
        raise typer.Exit(code=2) from exc
    if isinstance(exc, RefactoryError):
        console.print(f"[bold red]Error:[/bold red] {exc.message}")
        raise typer.Exit(code=1) from exc
    console.print(f"[bold red]Unexpected error:[/bold red] {exc}")
    raise typer.Exit(code=1) from exc
