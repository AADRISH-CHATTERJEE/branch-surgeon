"""`refactory prompt` — [dev] inspect PromptBuilder output (no AI calls)."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from refactory.cli.commands._common import get_container, handle_error, warm_backend_client
from refactory.cli.ui.console import console
from refactory.prompt.models import PromptRequest

DEFAULT_SAVE_RELATIVE = Path(".refactory") / "prompts" / "latest_prompt.md"


def prompt_cmd(
    review_target: int = typer.Argument(
        ...,
        help="Review target id (GitHub PR number, or local synthetic target).",
    ),
    save: bool = typer.Option(
        False,
        "--save",
        help=f"Write prompt to {{repo}}/{DEFAULT_SAVE_RELATIVE.as_posix()}.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Write prompt to this path (relative paths resolve from the repo root).",
        writable=True,
    ),
) -> None:
    """Build and print the review prompt without invoking the AI gateway."""
    try:
        container = get_container()
        warm_backend_client(container)
        prompt = container.review_engine.build_prompt(review_target)
        _print_prompt(prompt)

        write_path: Path | None = None
        if output is not None:
            write_path = output
        elif save:
            write_path = DEFAULT_SAVE_RELATIVE

        if write_path is not None:
            repo_root = Path(container.git_service.require_repository().root_path)
            destination = (
                write_path if write_path.is_absolute() else (repo_root / write_path)
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(format_prompt_document(prompt), encoding="utf-8")
            console.print("")
            console.print(f"[green]Saved prompt[/green] → {destination}")
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def format_prompt_document(prompt: PromptRequest) -> str:
    """Canonical on-disk layout for saved prompts."""
    metadata = json.dumps(
        prompt.metadata.model_dump(mode="json"),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )
    return (
        "====================================\n"
        "SYSTEM PROMPT\n"
        "====================================\n"
        "\n"
        f"{prompt.system_prompt.rstrip()}\n"
        "\n"
        "====================================\n"
        "USER PROMPT\n"
        "====================================\n"
        "\n"
        f"{prompt.user_prompt.rstrip()}\n"
        "\n"
        "====================================\n"
        "METADATA\n"
        "====================================\n"
        "\n"
        f"{metadata}\n"
    )


def _print_prompt(prompt: PromptRequest) -> None:
    console.print("[bold]System Prompt[/bold]")
    console.print(prompt.system_prompt)
    console.print("")
    console.print("[bold]User Prompt[/bold]")
    console.print(prompt.user_prompt)
    console.print("")
    console.print("[bold]Prompt metadata[/bold]")
    console.print_json(data=prompt.metadata.model_dump(mode="json"))
