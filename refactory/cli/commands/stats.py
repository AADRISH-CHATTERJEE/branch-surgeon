"""`refactory stats` — repository statistics overview."""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path

import typer

from refactory.cli.commands._common import get_container, handle_error, warn_if_index_stale
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading
from refactory.cli.ui.style import format_ms


def stats_cmd(
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show repository statistics: languages, LOC, classes, functions, etc."""
    try:
        container = get_container()
        warn_if_index_stale(container)

        started = time.perf_counter()
        with loading("Collecting repository statistics..."):
            index = container.indexer_service.get_last_index()
            if index is None:
                root = Path(container.git_service.get_root_path()).resolve()
                index = container.indexer_service.build_index(root)

            stats = _collect_stats(index)

            try:
                container.graph_service.build_graph(index)
                graph_stats = container.graph_service.repository_statistics()
                stats["graph"] = {
                    "total_nodes": graph_stats.total_nodes,
                    "total_edges": graph_stats.total_edges,
                    "cyclic_dependencies": graph_stats.cyclic_dependency_count,
                    "orphan_modules": graph_stats.orphan_module_count,
                    "unused_symbols": graph_stats.unused_symbol_count,
                }
            except Exception:  # noqa: BLE001
                stats["graph"] = {"error": "graph build failed"}

            cache_stats = container.repository_cache.stats()
            stats["cache"] = cache_stats

        elapsed_ms = (time.perf_counter() - started) * 1000.0

        if output_json:
            import json
            console.print(json.dumps(stats, indent=2, default=str))
        else:
            _render(stats, elapsed_ms)

    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _collect_stats(index) -> dict[str, object]:
    """Gather statistics from the repository index."""
    languages: Counter[str] = Counter()
    total_classes = 0
    total_functions = 0
    total_imports = 0
    total_tests = 0
    total_files = len(index.files)

    for f in index.files:
        lang = f.language or "unknown"
        languages[lang] += 1
        total_classes += len(f.classes)
        total_functions += len(f.functions) + len(f.nested_functions)
        total_imports += len(f.import_references)

        path_lower = f.relative_path.lower()
        parts = path_lower.replace("\\", "/").split("/")
        stem = Path(f.relative_path).stem.lower()
        if (
            "test" in parts
            or "tests" in parts
            or stem.startswith("test_")
            or stem.endswith("_test")
        ):
            total_tests += 1

    return {
        "total_files": total_files,
        "languages": dict(languages.most_common()),
        "total_classes": total_classes,
        "total_functions": total_functions,
        "total_imports": total_imports,
        "test_files": total_tests,
        "production_files": total_files - total_tests,
    }


def _render(stats: dict[str, object], elapsed_ms: float) -> None:
    lines: list[str] = [
        "",
        "Repository Statistics",
        "=====================",
        "",
        f"Total Files:     {stats['total_files']}",
        f"Classes:         {stats['total_classes']}",
        f"Functions:       {stats['total_functions']}",
        f"Imports:         {stats['total_imports']}",
        f"Test Files:      {stats['test_files']}",
        f"Production:      {stats['production_files']}",
        "",
    ]

    languages = stats.get("languages")
    if isinstance(languages, dict) and languages:
        lines.append("Languages")
        lines.append("---------")
        for lang, count in languages.items():
            lines.append(f"  {lang}: {count} files")
        lines.append("")

    graph = stats.get("graph")
    if isinstance(graph, dict):
        if "error" not in graph:
            lines.append("Repository Graph")
            lines.append("----------------")
            lines.append(f"  Nodes:               {graph['total_nodes']}")
            lines.append(f"  Edges:               {graph['total_edges']}")
            lines.append(f"  Cyclic Dependencies: {graph['cyclic_dependencies']}")
            lines.append(f"  Orphan Modules:      {graph['orphan_modules']}")
            lines.append(f"  Unused Symbols:      {graph['unused_symbols']}")
            lines.append("")

    cache = stats.get("cache")
    if isinstance(cache, dict):
        lines.append("Cache")
        lines.append("-----")
        lines.append(f"  Entries:    {cache.get('entries', 0)}")
        lines.append(f"  Hits:       {cache.get('hits', 0)}")
        lines.append(f"  Misses:     {cache.get('misses', 0)}")
        hit_ratio = cache.get("hit_ratio", 0)
        lines.append(f"  Hit Ratio:  {hit_ratio:.0%}" if isinstance(hit_ratio, float) else f"  Hit Ratio:  {hit_ratio}")
        lines.append("")

    lines.append(f"Collected in {format_ms(elapsed_ms)}")
    lines.append("")
    console.print("\n".join(lines))
