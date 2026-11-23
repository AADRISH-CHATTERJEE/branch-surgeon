"""`refactory graph` — presentation adapter for RepositoryGraphService."""

from __future__ import annotations

from pathlib import Path

import typer

from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console
from refactory.graph.models import NodeKind, RepositoryGraph
from refactory.graph.service import RepositoryGraphService
from refactory.indexer.models import RepositoryIndex
from refactory.indexer.service import IndexerService

graph_app = typer.Typer(
    name="graph",
    help="[dev] Build and query the deterministic repository knowledge graph.",
    invoke_without_command=True,
    no_args_is_help=False,
)


def _ensure_index(indexer: IndexerService, root: Path, repository_name: str) -> RepositoryIndex:
    existing = indexer.load_index(root)
    if existing is not None:
        return existing
    return indexer.build_index(root, repository_name=repository_name)


def _build_graph_service(*, force: bool = False) -> tuple[RepositoryGraphService, RepositoryGraph]:
    container = get_container()
    repository = container.git_service.get_repository_metadata()
    root = Path(repository.root_path)
    index = _ensure_index(container.indexer_service, root, repository.name)
    service: RepositoryGraphService = container.graph_service
    built = service.build_graph(index, force=force)
    return service, built


@graph_app.callback()
def graph_root(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", "-f", help="Rebuild graph even if cached."),
) -> None:
    """Show repository graph summary (or run a subcommand)."""
    if ctx.invoked_subcommand is not None:
        return
    try:
        service, built = _build_graph_service(force=force)
        _render_summary(service, built)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


@graph_app.command("symbol")
def graph_symbol(name: str = typer.Argument(..., help="Symbol name to look up.")) -> None:
    """Show where a symbol is defined and who imports / references it."""
    try:
        service, _built = _build_graph_service()
        _render_symbol(service, name)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


@graph_app.command("file")
def graph_file(path: str = typer.Argument(..., help="Relative file path to inspect.")) -> None:
    """Show definitions, imports, and importers for a file."""
    try:
        service, _built = _build_graph_service()
        _render_file(service, path)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _render_summary(service: RepositoryGraphService, graph: RepositoryGraph) -> None:
    stats = graph.statistics
    top_modules = service.top_imported_modules(5)
    top_symbols = service.top_referenced_symbols(5)
    connected = service.most_connected_files(5)

    lines = [
        "====================================",
        "",
        "Repository Graph",
        "",
        "====================================",
        "",
        f"Nodes: {stats.total_nodes}",
        "",
        f"Edges: {stats.total_edges}",
        "",
        f"Modules: {stats.modules}",
        "",
        f"Files: {stats.files}",
        "",
        f"Functions: {stats.functions}",
        "",
        f"Classes: {stats.classes}",
        "",
        f"Import relationships: {stats.import_edges}",
        "",
        "Top imported modules:",
        "",
    ]
    if top_modules:
        for name, count in top_modules:
            lines.extend([f"  {name} ({count})", ""])
    else:
        lines.extend(["  (none)", ""])

    lines.extend(["Top referenced symbols:", ""])
    if top_symbols:
        for name, count in top_symbols:
            lines.extend([f"  {name} ({count})", ""])
    else:
        lines.extend(["  (none)", ""])

    lines.extend(["Most connected files:", ""])
    if connected:
        for path, count in connected:
            lines.extend([f"  {path} ({count})", ""])
    else:
        lines.extend(["  (none)", ""])

    lines.append("====================================")
    console.print("\n".join(lines))


def _render_symbol(service: RepositoryGraphService, name: str) -> None:
    matches = service.find_symbol(name)
    if not matches:
        console.print(f"Symbol not found: {name}")
        raise typer.Exit(code=1)

    defined_in = service.where_defined(name)
    # Prefer module-stem importers for modules that share the symbol's module name
    module_names = sorted({m.module_name for m in matches if m.module_name})
    imported_by: set[str] = set()
    for module_name in module_names:
        imported_by.update(service.who_imports(module_name))
    for path in defined_in:
        imported_by.update(service.who_imports_file(path))
    referenced_by = service.files_referencing_symbol(name)

    # Display kind for the first match
    primary = matches[0]
    kind_label = {
        NodeKind.FUNCTION: f"{name}()",
        NodeKind.METHOD: f"{name}()",
        NodeKind.NESTED_FUNCTION: f"{name}()",
        NodeKind.CLASS: name,
        NodeKind.MODULE: name,
        NodeKind.FILE: name,
    }.get(primary.kind, name)

    lines = [
        "====================================",
        "",
        "Symbol",
        "",
        kind_label,
        "",
        "Defined in:",
        "",
    ]
    if defined_in:
        for path in defined_in:
            lines.extend([path, ""])
    else:
        lines.extend(["(unknown)", ""])

    lines.extend(["Imported by:", ""])
    if imported_by:
        for path in sorted(imported_by):
            lines.extend([path, ""])
    else:
        lines.extend(["(none)", ""])

    lines.extend(["Referenced by:", ""])
    if referenced_by:
        for path in referenced_by:
            lines.extend([path, ""])
    else:
        lines.extend(["(none)", ""])

    lines.append("====================================")
    console.print("\n".join(lines))


def _render_file(service: RepositoryGraphService, path: str) -> None:
    file_node = service.find_file(path)
    if file_node is None:
        console.print(f"File not found in graph: {path}")
        raise typer.Exit(code=1)

    display_path = file_node.file_path or path
    defines = service.defined_symbols_in_file(display_path)
    imports = service.dependencies_of(display_path)
    imported_by = service.who_imports_file(display_path)

    lines = [
        "====================================",
        "",
        "File",
        "",
        display_path,
        "",
        "Defines:",
        "",
    ]
    callable_kinds = {NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.NESTED_FUNCTION}
    if defines:
        for match in defines:
            label = f"{match.name}()" if match.kind in callable_kinds else match.name
            lines.extend([label, ""])
    else:
        lines.extend(["(none)", ""])

    lines.extend(["Imports:", ""])
    if imports:
        for dep in imports:
            lines.extend([dep, ""])
    else:
        lines.extend(["(none)", ""])

    lines.extend(["Imported by:", ""])
    if imported_by:
        for importer in imported_by:
            lines.extend([importer, ""])
    else:
        lines.extend(["(none)", ""])

    lines.append("====================================")
    console.print("\n".join(lines))
