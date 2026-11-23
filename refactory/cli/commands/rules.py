"""`refactory rules` — check company rules without running AI review."""

from __future__ import annotations

import time
from pathlib import Path

import typer

from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console
from refactory.company.context import resolve_gate_context
from refactory.company.models import GateOutcome, GateResult

rules_app = typer.Typer(
    name="rules",
    help="Check company rules and standards (no AI).",
    no_args_is_help=True,
)


@rules_app.command("check")
def rules_check(
    root: Path = typer.Option(
        None,
        "--root",
        help="Repository root (defaults to current git repository).",
        exists=True,
        file_okay=False,
        resolve_path=True,
    ),
    branch: str | None = typer.Option(
        None,
        "--branch",
        "-b",
        help="Branch name to validate (defaults to current git branch).",
    ),
    commit: str | None = typer.Option(
        None,
        "--commit",
        "-c",
        help="Commit / PR subject to validate (defaults to branch commits since base).",
    ),
    base: str | None = typer.Option(
        None,
        "--base",
        help="Base branch for changed-files / commit range (defaults to repo default).",
    ),
) -> None:
    """Run company rules check. Exit code 1 if any blocking rule fails."""
    try:
        container = get_container()
        git = container.git_service

        if root is None:
            repo = git.get_repository_metadata()
            root = Path(repo.root_path)
        else:
            root = Path(root)

        ctx = resolve_gate_context(
            git,
            branch_name=branch,
            commit_message=commit,
            base_branch=base,
        )

        started = time.perf_counter()
        result = container.company_rules_checker.check(
            root,
            branch_name=ctx.branch_name,
            commit_message=ctx.commit_message,
            commit_messages=ctx.commit_messages,
            changed_files=ctx.changed_files,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)

        _render_gate_result(
            result,
            branch_name=ctx.branch_name,
            commit_message=ctx.commit_message,
            base_branch=ctx.base_branch,
            changed_file_count=len(ctx.changed_files),
            commit_count=len(ctx.commit_messages),
        )
        _persist_gate_result(
            container,
            result,
            branch_name=ctx.branch_name,
            elapsed_ms=elapsed_ms,
            head_sha=ctx.head_sha,
            base_branch=ctx.base_branch,
        )

        if result.outcome == GateOutcome.BLOCK:
            raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _persist_gate_result(
    container,
    result: GateResult,
    *,
    branch_name: str,
    elapsed_ms: float,
    head_sha: str | None = None,
    base_branch: str = "",
) -> None:
    """Persist the gate result as an analysis run. Never raises."""
    try:
        persistence = container.persistence_service
        git = container.git_service

        repo_meta = git.get_repository_metadata()
        repo_data = persistence.get_or_create_repository(
            name=repo_meta.name,
            root_path=repo_meta.root_path,
            default_branch=getattr(repo_meta, "default_branch", "main") or "main",
            remote_url=getattr(repo_meta, "remote_url", None),
        )

        git_commit = head_sha
        if not git_commit:
            try:
                commit_info = git.get_current_commit()
                git_commit = getattr(commit_info, "sha", None) or getattr(
                    commit_info, "hash", None
                )
            except Exception:  # noqa: BLE001
                pass

        persistence.persist_analysis_run(
            repository_id=repo_data["id"],
            command="rules-check",
            result_type="company_rules",
            status=result.outcome.value,
            git_commit=git_commit,
            branch=branch_name or None,
            duration_ms=elapsed_ms,
            result_data={
                "outcome": result.outcome.value,
                "violations": [v.model_dump() for v in result.violations],
                "blocker_count": len(result.blockers),
                "warning_count": len(result.warnings),
                "summary": result.summary_text(),
                "base_branch": base_branch or None,
            },
        )
    except Exception:  # noqa: BLE001
        pass


def _render_gate_result(
    result: GateResult,
    *,
    branch_name: str,
    commit_message: str,
    base_branch: str = "",
    changed_file_count: int = 0,
    commit_count: int = 0,
) -> None:
    outcome = result.outcome
    if outcome == GateOutcome.PASS:
        console.print("[bold green]✓ PASS[/bold green] — all company rules passed")
    elif outcome == GateOutcome.WARN:
        console.print("[bold yellow]⚠ WARN[/bold yellow] — company rules have warnings")
    else:
        console.print("[bold red]❌ BLOCK[/bold red] — mandatory company rules failed")

    if branch_name:
        console.print(f"  Branch:  {branch_name}")
    if base_branch:
        console.print(f"  Base:    {base_branch}")
    subject = commit_message.splitlines()[0].strip() if commit_message else ""
    if subject:
        if commit_count > 1:
            console.print(
                f"  Subject: {subject}  [dim]({commit_count} commits)[/dim]"
            )
        else:
            console.print(f"  Subject: {subject}")
    if changed_file_count:
        console.print(f"  Files:   {changed_file_count} changed")

    if result.blockers:
        console.print()
        console.print("[bold red]Blockers[/bold red]")
        for v in result.blockers:
            # Escape brackets — Rich treats [name] as markup
            console.print(f"  • \\[{v.rule}\\] {v.message}")
            if v.detail:
                console.print(f"    {v.detail}")

    if result.warnings:
        console.print()
        console.print("[bold yellow]Warnings[/bold yellow]")
        for v in result.warnings:
            console.print(f"  • \\[{v.rule}\\] {v.message}")
            if v.detail:
                console.print(f"    {v.detail}")

    if outcome == GateOutcome.PASS and not result.violations:
        console.print()
        console.print("[dim]No violations found.[/dim]")
