"""Seed organization policy examples (applied once when the table is empty)."""

from __future__ import annotations

from typing import Any

DEFAULT_ORGANIZATION_RULES: list[dict[str, Any]] = [
    {
        "name": "Branch naming — feature / bugfix / hotfix",
        "description": "Branches must follow feature/*, bugfix/*, or hotfix/* naming.",
        "category": "branch_naming",
        "severity": "warning",
        "enabled": True,
        "rule_type": "branch_naming",
        "blocking": False,
        "condition_logic": "or",
        "conditions": [
            {
                "field": "branch_name",
                "operator": "matches",
                "pattern": r"^(feature|bugfix|hotfix)/.+",
            },
        ],
        "message": "Branch name must match feature/*, bugfix/*, or hotfix/*.",
        "documentation_url": "/documentation?doc=branching",
    },
    {
        "name": "Conventional Commits",
        "description": "Commit messages must use Conventional Commits prefixes.",
        "category": "commit_message",
        "severity": "warning",
        "enabled": True,
        "rule_type": "commit_message",
        "blocking": False,
        "conditions": [
            {
                "field": "commit_message",
                "operator": "matches",
                "pattern": r"^(feat|fix|refactor|docs|chore|test|ci|perf)(\(.+\))?: .+",
            },
        ],
        "message": "Use Conventional Commits (feat:, fix:, refactor:, docs:, …).",
        "documentation_url": "/documentation?doc=commits",
    },
    {
        "name": "Require tests for services/ changes",
        "description": "PRs touching services/ must include test file changes.",
        "category": "required_tests",
        "severity": "error",
        "enabled": True,
        "rule_type": "testing",
        "blocking": True,
        "conditions": [
            {
                "field": "changed_files",
                "operator": "matches",
                "pattern": r"(^|/)services/",
            },
            {
                "field": "changed_files",
                "operator": "matches",
                "pattern": r"(^|/)tests?/|(^|/)test_|_test\.py$",
            },
        ],
        "message": "Changes under services/ require accompanying test updates.",
        "documentation_url": "/documentation?doc=testing_guidelines",
    },
    {
        "name": "Controllers cannot call repositories",
        "description": "Architecture: controllers must call services only, not repositories.",
        "category": "architecture_layer",
        "severity": "error",
        "enabled": True,
        "rule_type": "architecture",
        "blocking": True,
        "conditions": [
            {
                "field": "imports",
                "operator": "matches",
                "pattern": r"controllers?.+repositories?|from\s+\S*controllers?\S*\s+import",
            },
        ],
        "message": "Controllers must not import repositories directly — use services.",
        "documentation_url": "/documentation?doc=architecture",
    },
    {
        "name": "No eval() in production code",
        "description": "Security: forbid eval() in application sources.",
        "category": "security_policy",
        "severity": "blocker",
        "enabled": True,
        "rule_type": "security",
        "blocking": True,
        "conditions": [
            {"field": "content", "operator": "matches", "pattern": r"\beval\s*\("},
        ],
        "message": "Do not use eval() — it allows arbitrary code execution.",
        "documentation_url": "/documentation?doc=security_guidelines",
    },
    {
        "name": "No hardcoded API keys",
        "description": "Security: forbid obvious API key assignments.",
        "category": "security_policy",
        "severity": "blocker",
        "enabled": True,
        "rule_type": "security",
        "blocking": True,
        "conditions": [
            {
                "field": "content",
                "operator": "matches",
                "pattern": r"(?i)(api[_-]?key|secret[_-]?key)\s*=\s*['\"][^'\"]+['\"]",
            },
        ],
        "message": "Do not hardcode API keys or secrets in source files.",
        "documentation_url": "/documentation?doc=security_guidelines",
    },
    {
        "name": "No print() in production modules",
        "description": "Prefer structured logging over print() in app code.",
        "category": "security_policy",
        "severity": "warning",
        "enabled": True,
        "rule_type": "security",
        "blocking": False,
        "conditions": [
            {"field": "content", "operator": "matches", "pattern": r"\bprint\s*\("},
        ],
        "message": "Avoid print() in production code — use the logging framework.",
        "documentation_url": "/documentation?doc=coding_guidelines",
    },
    {
        "name": "Public API changes require docs",
        "description": "Documentation: API surface changes should update docs.",
        "category": "required_tests",
        "severity": "warning",
        "enabled": True,
        "rule_type": "documentation",
        "blocking": False,
        "conditions": [
            {
                "field": "changed_files",
                "operator": "matches",
                "pattern": r"(^|/)(api|routes)/",
            },
            {
                "field": "changed_files",
                "operator": "matches",
                "pattern": r"(^|/)(docs?|documentation)/|\.md$",
            },
        ],
        "message": "Public API changes require a documentation update.",
        "documentation_url": "/documentation?doc=company_policies",
    },
]
