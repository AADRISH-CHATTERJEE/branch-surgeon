"""`refactory workspace` — manage repository workspaces."""

from __future__ import annotations

import typer

from refactory.cli.ui.console import console
from refactory.workspace.manager import WorkspaceManager

workspace_app = typer.Typer(
    name="workspace",
    help="Manage repository workspaces.",
    no_args_is_help=True,
)


def _get_manager() -> WorkspaceManager:
    from loguru import logger
    return WorkspaceManager(logger=logger)


@workspace_app.command("add")
def workspace_add(
    name: str = typer.Argument(..., help="Workspace name"),
    path: str = typer.Argument(".", help="Repository path"),
) -> None:
    """Add a new workspace."""
    try:
        manager = _get_manager()
        ws = manager.add(name, path)
        console.print(f"[green]Workspace added:[/green] {ws.name} → {ws.path}")
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc


@workspace_app.command("remove")
def workspace_remove(
    name: str = typer.Argument(..., help="Workspace name to remove"),
) -> None:
    """Remove a workspace."""
    try:
        manager = _get_manager()
        manager.remove(name)
        console.print(f"[green]Workspace removed:[/green] {name}")
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc


@workspace_app.command("list")
def workspace_list() -> None:
    """List all workspaces."""
    manager = _get_manager()
    workspaces = manager.list_workspaces()
    if not workspaces:
        console.print("[dim]No workspaces configured.[/dim]")
        return
    for ws in workspaces:
        marker = " [green]*[/green]" if ws.active else ""
        console.print(f"  {ws.name}{marker}  →  {ws.path}")


@workspace_app.command("use")
def workspace_use(
    name: str = typer.Argument(..., help="Workspace name to activate"),
) -> None:
    """Set the active workspace."""
    try:
        manager = _get_manager()
        ws = manager.use(name)
        console.print(f"[green]Active workspace:[/green] {ws.name} → {ws.path}")
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
