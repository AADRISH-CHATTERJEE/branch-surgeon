"""CLI commands for the Transformation Engine."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading
from refactory.transformation.models import TransformationRequest, TransformationType


def _parse_type(t: str) -> TransformationType:
    """Parse transformation type from CLI string."""
    try:
        return TransformationType(t)
    except ValueError:
        for tt in TransformationType:
            if t.lower().replace("-", "_") == tt.value:
                return tt
        return TransformationType.RENAME_SYMBOL


def preview_cmd(
    file: str = typer.Argument(..., help="Target file"),
    transform_type: str = typer.Option("rename_symbol", "--type", "-t", help="Transformation type"),
    symbol: str = typer.Option("", "--symbol", "-s", help="Target symbol"),
    old_name: str = typer.Option("", "--old", help="Old name (for renames)"),
    new_name: str = typer.Option("", "--new", help="New name (for renames)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Preview a transformation without applying it."""
    try:
        container = get_container()
        root = Path(container.git_service.get_root_path()).resolve()
        params: dict = {}
        if old_name:
            params["old_name"] = old_name
        if new_name:
            params["new_name"] = new_name

        request = TransformationRequest(
            transformation_type=_parse_type(transform_type),
            target_file=file,
            target_symbol=symbol,
            parameters=params,
        )
        with loading("Generating preview..."):
            preview = container.transformation_service.preview(request, root)
        if json_output:
            console.print(json.dumps(preview.model_dump(mode="json"), indent=2, default=str))
        else:
            from refactory.transformation.preview import PreviewEngine
            from loguru import logger
            engine = PreviewEngine(logger)
            console.print(engine.format_preview(preview))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def apply_cmd(
    file: str = typer.Argument(..., help="Target file"),
    transform_type: str = typer.Option("rename_symbol", "--type", "-t", help="Transformation type"),
    symbol: str = typer.Option("", "--symbol", "-s", help="Target symbol"),
    old_name: str = typer.Option("", "--old", help="Old name (for renames)"),
    new_name: str = typer.Option("", "--new", help="New name (for renames)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Apply a transformation."""
    try:
        container = get_container()
        root = Path(container.git_service.get_root_path()).resolve()
        params: dict = {}
        if old_name:
            params["old_name"] = old_name
        if new_name:
            params["new_name"] = new_name

        request = TransformationRequest(
            transformation_type=_parse_type(transform_type),
            target_file=file,
            target_symbol=symbol,
            parameters=params,
        )
        with loading("Applying transformation..."):
            result = container.transformation_service.apply(request, root)
        if json_output:
            console.print(json.dumps(result.model_dump(mode="json"), indent=2, default=str))
        else:
            lines = [
                "", "Transformation Result", "====================", "",
                f"Status: {result.status.value.upper()}",
                f"Files Modified: {len(result.files_modified)}",
                f"Duration: {result.duration_ms:.0f}ms",
                f"Rollback Available: {'Yes' if result.rollback_available else 'No'}",
            ]
            if result.files_modified:
                lines.append("")
                lines.append("Modified:")
                for f in result.files_modified:
                    lines.append(f"  {f}")
            lines.append("")
            console.print("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def rollback_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Rollback the last applied transformation."""
    try:
        container = get_container()
        root = Path(container.git_service.get_root_path()).resolve()
        with loading("Rolling back..."):
            result = container.transformation_service.rollback(root)
        if json_output:
            console.print(json.dumps(result.model_dump(mode="json"), indent=2, default=str))
        else:
            lines = [
                "", "Rollback Result", "===============", "",
                f"Status: {result.status.value.upper()}",
            ]
            if result.files_modified:
                lines.append(f"Files Restored: {len(result.files_modified)}")
                for f in result.files_modified:
                    lines.append(f"  {f}")
            else:
                lines.append("No transformation to rollback.")
            lines.append("")
            console.print("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def transform_cmd(
    file: str = typer.Argument(..., help="Target file"),
    transform_type: str = typer.Option("rename_symbol", "--type", "-t", help="Transformation type"),
    symbol: str = typer.Option("", "--symbol", "-s", help="Target symbol"),
    old_name: str = typer.Option("", "--old", help="Old name (for renames)"),
    new_name: str = typer.Option("", "--new", help="New name (for renames)"),
    ai: bool = typer.Option(False, "--ai", help="Enable AI assistance"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Generate and preview a transformation (alias for preview)."""
    try:
        container = get_container()
        root = Path(container.git_service.get_root_path()).resolve()
        params: dict = {}
        if old_name:
            params["old_name"] = old_name
        if new_name:
            params["new_name"] = new_name

        request = TransformationRequest(
            transformation_type=_parse_type(transform_type),
            target_file=file,
            target_symbol=symbol,
            parameters=params,
            ai_assisted=ai,
        )
        with loading("Planning transformation..."):
            preview = container.transformation_service.transform(request, root)
        if json_output:
            console.print(json.dumps(preview.model_dump(mode="json"), indent=2, default=str))
        else:
            from refactory.transformation.preview import PreviewEngine
            from loguru import logger
            engine = PreviewEngine(logger)
            console.print(engine.format_preview(preview))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
