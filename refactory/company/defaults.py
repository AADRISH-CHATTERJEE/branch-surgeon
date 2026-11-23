"""Default company documentation Markdown for .refactory/ scaffolding."""

from __future__ import annotations

# Filenames under <repo>/.refactory/ — shared by init, seed, and the Documentation API.
DOC_FILES: dict[str, str] = {
    "architecture.md": "architecture",
    "coding_guidelines.md": "coding_guidelines",
    "security_guidelines.md": "security_guidelines",
    "testing_guidelines.md": "testing_guidelines",
}

DEFAULT_ARCHITECTURE_MD = """\
# Architecture

This repository follows a layered architecture.

Presentation
↓
Services
↓
Repositories
↓
Persistence

## Rules

- Controllers never access repositories directly.
- Business logic belongs in services.
- Database access belongs in repositories.
"""

DEFAULT_CODING_GUIDELINES_MD = """\
# Coding Guidelines

- Use type hints.
- Follow PEP8.
- Keep functions under 40 lines.
- Avoid duplicated logic.
- Use descriptive names.
"""

DEFAULT_SECURITY_GUIDELINES_MD = """\
# Security Guidelines

- Never hardcode credentials.
- Never commit API keys.
- Validate all inputs.
- Escape user-controlled data.
- Do not use eval().
"""

DEFAULT_TESTING_GUIDELINES_MD = """\
# Testing Guidelines

- Every service change requires tests.
- Maintain at least 80% coverage.
- Add regression tests for bugs.
- Unit tests should not depend on external services.
"""

DEFAULT_DOCUMENTATION_MD: dict[str, str] = {
    "architecture.md": DEFAULT_ARCHITECTURE_MD,
    "coding_guidelines.md": DEFAULT_CODING_GUIDELINES_MD,
    "security_guidelines.md": DEFAULT_SECURITY_GUIDELINES_MD,
    "testing_guidelines.md": DEFAULT_TESTING_GUIDELINES_MD,
}
