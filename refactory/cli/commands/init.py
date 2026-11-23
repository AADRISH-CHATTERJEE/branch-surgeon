"""refactory init — bootstrap a new Refactory workspace."""

from __future__ import annotations

from pathlib import Path

import typer

from refactory.company.defaults import (
    DEFAULT_ARCHITECTURE_MD as _DEFAULT_ARCHITECTURE_MD,
    DEFAULT_CODING_GUIDELINES_MD as _DEFAULT_CODING_GUIDELINES_MD,
    DEFAULT_SECURITY_GUIDELINES_MD as _DEFAULT_SECURITY_GUIDELINES_MD,
    DEFAULT_TESTING_GUIDELINES_MD as _DEFAULT_TESTING_GUIDELINES_MD,
)
from refactory.core.container import build_container

_DEFAULT_RULES = """\
# Refactory rules — customize checks for your repository.
# See https://refactory.dev/docs/rules for full reference.
#
# Each rule needs:
#   name:       unique identifier
#   category:   one of max_function_size, max_file_size, forbidden_import,
#               forbidden_path, branch_naming, commit_message, naming_convention,
#               architecture_layer, security_policy, custom
#   severity:   error | warning | info
#   blocking:   true/false — block merges on violation
#   conditions: list of {field, operator, value, pattern}
#   message:    human-readable violation message

rules:
  - name: max-function-length
    category: max_function_size
    severity: warning
    blocking: false
    conditions:
      - field: function_size
        operator: greater_than
        value: 50
    message: "Function exceeds 50 lines."

  - name: max-file-length
    category: max_file_size
    severity: warning
    blocking: false
    conditions:
      - field: file_size
        operator: greater_than
        value: 500
    message: "File exceeds 500 lines."

  - name: no-wildcard-imports
    category: forbidden_import
    severity: warning
    blocking: false
    conditions:
      - field: import
        operator: matches
        pattern: "from .* import \\\\*"
    message: "Avoid wildcard imports."

  - name: no-eval
    category: security_policy
    severity: error
    blocking: false
    conditions:
      - field: content
        operator: matches
        pattern: "\\\\beval\\\\s*\\\\("
    message: "Do not use eval() — it allows arbitrary code execution."
"""

_DEFAULT_ARCHITECTURE = """\
# Refactory architecture policies.
# Define layer boundaries and dependency rules for your codebase.

layers:
  - name: presentation
    patterns:
      - "*/views/*"
      - "*/routes/*"
      - "*/cli/*"

  - name: business
    patterns:
      - "*/services/*"
      - "*/domain/*"

  - name: data
    patterns:
      - "*/models/*"
      - "*/repositories/*"
      - "*/storage/*"

policies:
  - from: presentation
    to: data
    action: deny
    message: "Presentation layer must not access data layer directly."
"""

_DEFAULT_COMPANY = """\
# Refactory company/team configuration.
# These rules are checked BEFORE the AI review runs.
# Blocking violations stop the review immediately.

organization:
  name: "My Team"
  language: python
  test_framework: pytest

# Branch naming (optional). Set block: true to stop AI review on mismatch.
# branch:
#   pattern: "^feature/[A-Z]+-[0-9]+-.*$"
#   block: true
#   message: "Branch must look like feature/JIRA-123-description"

# Commit / PR title convention (optional).
# commit:
#   pattern: "^(feat|fix|refactor|docs|test):"
#   block: true

# Architecture forbidden dependencies (optional).
# architecture:
#   block: true
#   forbidden_dependencies:
#     - from: presentation
#       to: data

# Require tests when production code changes (optional).
testing:
  require_tests: false
  block: false

standards:
  max_function_lines: 50
  max_file_lines: 500
  require_docstrings: true
  require_type_hints: true
"""

_DEFAULT_PROMPTS = """\
# Refactory prompt templates.
# Override default AI prompts for review, docgen, and recommendations.

templates:
  review:
    system: |
      You are a senior code reviewer. Focus on correctness, security,
      and maintainability. Be concise and actionable.

  docgen:
    system: |
      You are a documentation expert. Generate clear, concise docstrings
      following Google style. Include parameters, returns, and raises.

  recommend:
    system: |
      You are an engineering advisor. Provide specific, actionable
      recommendations with estimated effort and risk.
"""


def init_cmd(
    root: Path = typer.Argument(
        ".", help="Repository root directory.", exists=True, resolve_path=True,
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing files."),
) -> None:
    """Initialize a Refactory workspace with default configuration files."""
    refactory_dir = root / ".refactory"
    storage_dir = refactory_dir / "storage"

    files = {
        refactory_dir / "rules.yaml": _DEFAULT_RULES,
        refactory_dir / "architecture.yaml": _DEFAULT_ARCHITECTURE,
        refactory_dir / "company.yaml": _DEFAULT_COMPANY,
        refactory_dir / "architecture.md": _DEFAULT_ARCHITECTURE_MD,
        refactory_dir / "coding_guidelines.md": _DEFAULT_CODING_GUIDELINES_MD,
        refactory_dir / "security_guidelines.md": _DEFAULT_SECURITY_GUIDELINES_MD,
        refactory_dir / "testing_guidelines.md": _DEFAULT_TESTING_GUIDELINES_MD,
        refactory_dir / "prompts.yaml": _DEFAULT_PROMPTS,
    }

    created: list[str] = []
    skipped: list[str] = []

    refactory_dir.mkdir(parents=True, exist_ok=True)
    storage_dir.mkdir(parents=True, exist_ok=True)

    for path, content in files.items():
        if path.exists() and not force:
            skipped.append(str(path.relative_to(root)))
            continue
        path.write_text(content, encoding="utf-8")
        created.append(str(path.relative_to(root)))

    db_path = storage_dir / "refactory.db"
    if not db_path.exists() or force:
        from refactory.storage.database import DatabaseEngine
        engine = DatabaseEngine(repo_root=root)
        engine.create_tables()
        created.append(str(db_path.relative_to(root)))
    else:
        skipped.append(str(db_path.relative_to(root)))

    typer.echo(f"Initialized Refactory workspace at {root}")
    if created:
        typer.echo(f"  Created: {', '.join(created)}")
    if skipped:
        typer.echo(f"  Skipped (exists): {', '.join(skipped)}")
    typer.echo("\nRun 'refactory index' to start analyzing your repository.")
