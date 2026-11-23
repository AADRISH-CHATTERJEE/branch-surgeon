"""Typer application entrypoint — wires command modules only."""

from __future__ import annotations

import typer

from refactory import __version__
from refactory.cli.commands.ai_test import ai_test
from refactory.cli.commands.analyze_requirement import analyze_requirement_cmd
from refactory.cli.commands.architecture import architecture_cmd
from refactory.cli.commands.docgen import docgen_cmd
from refactory.cli.commands.explain import explain_cmd
from refactory.cli.commands.api_docs import api_docs_cmd
from refactory.cli.commands.branches import branches_cmd
from refactory.cli.commands.callees import callees_cmd
from refactory.cli.commands.callers import callers_cmd
from refactory.cli.commands.commit import commit_cmd
from refactory.cli.commands.coverage_map import coverage_map_cmd
from refactory.cli.commands.definition import definition_cmd
from refactory.cli.commands.docs import docs_cmd
from refactory.cli.commands.duplicate_tests import duplicate_tests_cmd
from refactory.cli.commands.embed import embed_app
from refactory.cli.commands.file_history import file_history_cmd
from refactory.cli.commands.git_info import git_info
from refactory.cli.commands.graph import graph_app
from refactory.cli.commands.history import history_cmd
from refactory.cli.commands.hotspots import hotspots_cmd
from refactory.cli.commands.impact import impact_cmd
from refactory.cli.commands.index import index
from refactory.cli.commands.init import init_cmd
from refactory.cli.commands.login import login
from refactory.cli.commands.logout import logout
from refactory.cli.commands.missing_docs import missing_docs_cmd
from refactory.cli.commands.orphan_tests import orphan_tests_cmd
from refactory.cli.commands.parse import parse
from refactory.cli.commands.parse_review import parse_review
from refactory.cli.commands.prompt import prompt_cmd
from refactory.cli.commands.refactor import refactor_cmd
from refactory.cli.commands.references import references_cmd
from refactory.cli.commands.repo import repo_cmd
from refactory.cli.commands.repo_structure import repo_structure_cmd
from refactory.cli.commands.review import review
from refactory.cli.commands.patch import patch_cmd
from refactory.cli.commands.pr import (
    explain_change_cmd,
    merge_readiness_cmd,
    pr_risk_cmd,
    pr_summary_cmd,
    pr_tests_cmd,
    review_ai_cmd,
    reviewers_cmd,
)
from refactory.cli.commands.recommend import (
    debt_cmd,
    health_cmd,
    recommend_cmd,
    trends_cmd,
)
from refactory.cli.commands.rules import rules_app
from refactory.cli.commands.transform import (
    apply_cmd,
    preview_cmd,
    rollback_cmd,
    transform_cmd,
)
from refactory.cli.commands.search import related, search
from refactory.cli.commands.stale_docs import stale_docs_cmd
from refactory.cli.commands.stats import stats_cmd
from refactory.cli.commands.testgen import testgen_cmd
from refactory.cli.commands.watch import watch_cmd
from refactory.cli.commands.workspace import workspace_app
from refactory.cli.commands.status import status
from refactory.cli.commands.surgeon import surgeon_cmd
from refactory.cli.commands.tests_cmd import tests_cmd
from refactory.cli.commands.todos import todos_cmd
from refactory.cli.commands.uncovered import uncovered_cmd
from refactory.cli.commands.whoami import whoami
from refactory.cli.startup import bootstrap_cli_settings
from refactory.core.config import get_settings
from refactory.core.logger import setup_logging

app = typer.Typer(
    name="refactory",
    help="Local-first AI repository intelligence (architecture foundation).",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable DEBUG logging."),
) -> None:
    settings = get_settings()
    setup_logging("DEBUG" if verbose else settings.logging.level)
    # Optional GET /config when authenticated — falls back to local settings.
    bootstrap_cli_settings(settings)


app.command("login")(login)
app.command("logout")(logout)
app.command("whoami")(whoami)
app.command("status")(status)
app.command("init", help="Initialize a Refactory workspace with configuration files.")(init_cmd)
app.command("index")(index)
app.command("search")(search)
app.command(
    "related",
    help="[dev] Find related files (graph first, then embeddings).",
)(related)
app.command(
    "definition",
    help="Find local definition sites for a symbol.",
)(definition_cmd)
app.command(
    "references",
    help="Find local references to a symbol.",
)(references_cmd)
app.command(
    "callers",
    help="Find local callers of a symbol.",
)(callers_cmd)
app.command(
    "callees",
    help="Find local callees of a symbol or file.",
)(callees_cmd)
app.command(
    "todos",
    help="List TODO / FIXME markers from the local index.",
)(todos_cmd)
app.command("review")(review)
app.command(
    "commit",
    help="Inspect a local commit (metadata, files, statistics, diff summary).",
)(commit_cmd)
app.command(
    "history",
    help="List recent local commits (hash, author, date, message).",
)(history_cmd)
app.command(
    "repo",
    help="Repository intelligence overview (local Git only).",
)(repo_cmd)
app.command(
    "hotspots",
    help="Rank hotspot files and directories from local commit history.",
)(hotspots_cmd)
app.command(
    "branches",
    help="Show local branch information (ahead/behind, stale, merged).",
)(branches_cmd)
app.command(
    "file-history",
    help="Show local history for a single file path.",
)(file_history_cmd)
app.command(
    "impact",
    help="Estimate local impact for a file or symbol.",
)(impact_cmd)
app.command(
    "surgeon",
    help="Analyze a branch for structural problems before merge.",
)(surgeon_cmd)
app.command(
    "analyze-requirement",
    help="Analyze a plain-English requirement against the local repository.",
)(analyze_requirement_cmd)
app.command(
    "tests",
    help="Find related tests for a file or symbol.",
)(tests_cmd)
app.command(
    "uncovered",
    help="List production files/symbols lacking related tests.",
)(uncovered_cmd)
app.command(
    "orphan-tests",
    help="List tests with no production code links.",
)(orphan_tests_cmd)
app.command(
    "duplicate-tests",
    help="List likely duplicate tests.",
)(duplicate_tests_cmd)
app.command(
    "coverage-map",
    help="Show production ↔ test coverage map summary.",
)(coverage_map_cmd)
app.command(
    "docs",
    help="Analyze repository or file documentation (no LLM).",
)(docs_cmd)
app.command(
    "missing-docs",
    help="List missing docstrings and package READMEs.",
)(missing_docs_cmd)
app.command(
    "stale-docs",
    help="List documentation that appears stale vs source.",
)(stale_docs_cmd)
app.command(
    "api-docs",
    help="List undocumented public APIs.",
)(api_docs_cmd)
app.command(
    "repo-structure",
    help="Show deterministic package/module structure.",
)(repo_structure_cmd)
app.command(
    "refactor",
    help="Analyze repository for deterministic refactoring opportunities.",
)(refactor_cmd)
app.command(
    "stats",
    help="Show repository statistics (languages, LOC, classes, functions, etc.).",
)(stats_cmd)
app.command(
    "patch",
    help="Generate unified git patches via AI (never modifies files).",
)(patch_cmd)
app.command(
    "testgen",
    help="Generate pytest test skeletons for a source file.",
)(testgen_cmd)
app.command(
    "docgen",
    help="Generate documentation for a source file.",
)(docgen_cmd)
app.command(
    "architecture",
    help="Generate architectural summary, violations, and advice.",
)(architecture_cmd)
app.command(
    "explain",
    help="Explain a file's purpose, dependencies, and business role.",
)(explain_cmd)
app.command(
    "pr-summary",
    help="Generate a PR summary: files, modules, impact, breaking changes.",
)(pr_summary_cmd)
app.command(
    "pr-risk",
    help="Analyze merge risk: LOW, MEDIUM, HIGH, CRITICAL.",
)(pr_risk_cmd)
app.command(
    "reviewers",
    help="Recommend reviewers based on ownership and expertise.",
)(reviewers_cmd)
app.command(
    "pr-tests",
    help="Recommend tests: existing, missing, integration, regression.",
)(pr_tests_cmd)
app.command(
    "pr-review",
    help="Generate AI review comments (bug risk, performance, security).",
)(review_ai_cmd)
app.command(
    "merge-readiness",
    help="Compute merge readiness score.",
)(merge_readiness_cmd)
app.command(
    "explain-change",
    help="Explain why a change matters and its downstream effects.",
)(explain_change_cmd)
app.command(
    "recommend",
    help="Generate ranked engineering recommendations.",
)(recommend_cmd)
app.command(
    "health",
    help="Show repository health dashboard.",
)(health_cmd)
app.command(
    "debt",
    help="Analyze technical debt.",
)(debt_cmd)
app.command(
    "trends",
    help="Show historical engineering trends.",
)(trends_cmd)
app.command(
    "preview",
    help="Preview a transformation without applying it.",
)(preview_cmd)
app.command(
    "apply",
    help="Apply a code transformation.",
)(apply_cmd)
app.command(
    "rollback",
    help="Rollback the last applied transformation.",
)(rollback_cmd)
app.command(
    "transform",
    help="Generate and preview a transformation.",
)(transform_cmd)
app.command(
    "prompt",
    help="[dev] Build and inspect the review prompt (no AI gateway call).",
)(prompt_cmd)
app.command(
    "ai-test",
    help="[dev] Smoke-test the AI gateway with a small synthetic prompt.",
)(ai_test)
app.add_typer(graph_app, name="graph")
app.add_typer(embed_app, name="embed")
app.add_typer(workspace_app, name="workspace")
app.add_typer(rules_app, name="rules")
app.command(
    "watch",
    help="Watch repository for changes and auto-update analysis.",
)(watch_cmd)
app.command(
    "git-info",
    help="[dev] Print local Git repository info discovered from the current directory.",
)(git_info)
app.command(
    "parse",
    help="[dev] Parse a source file with Tree-sitter and print structured info.",
)(parse)
app.command(
    "parse-review",
    help="[dev] Parse an on-disk AI review response into structured models.",
)(parse_review)


@app.command("version")
def version_cmd() -> None:
    """Show Refactory version."""
    typer.echo(f"refactory {__version__}")


if __name__ == "__main__":
    app()
