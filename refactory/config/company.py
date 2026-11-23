"""CompanyConfiguration — configurable policies inherited by repositories.

Stores coding standards, architecture docs, review policies, security policies,
branch strategy, merge strategy, and more.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class CodingStandards(BaseModel):
    """Coding standards configuration."""

    max_function_lines: int = 50
    max_file_lines: int = 500
    max_class_methods: int = 20
    naming_convention: str = "snake_case"
    required_docstrings: bool = True
    forbidden_patterns: list[str] = Field(default_factory=list)


class ReviewPolicy(BaseModel):
    """Code review policies."""

    min_reviewers: int = 1
    require_owner_review: bool = False
    auto_assign_reviewers: bool = True
    required_checks: list[str] = Field(default_factory=list)
    max_pr_size_lines: int = 1000


class SecurityPolicy(BaseModel):
    """Security policies."""

    block_on_critical: bool = True
    block_on_high: bool = False
    required_scans: list[str] = Field(default_factory=list)
    forbidden_apis: list[str] = Field(default_factory=list)
    allowed_licenses: list[str] = Field(default_factory=list)


class BranchStrategy(BaseModel):
    """Branch strategy configuration."""

    default_branch: str = "main"
    branch_pattern: str = r"^(feature|fix|hotfix|release)/[a-z0-9-]+$"
    require_pr: bool = True
    require_linear_history: bool = False


class CommitConvention(BaseModel):
    """Commit message conventions."""

    pattern: str = r"^(feat|fix|docs|style|refactor|test|chore)(\(.+\))?: .+"
    max_subject_length: int = 72
    require_body: bool = False


class ProjectTestRequirements(BaseModel):
    """Test requirements."""

    min_coverage_percent: float = 80.0
    require_unit_tests: bool = True
    require_integration_tests: bool = False
    test_file_pattern: str = "test_*.py"


class DocumentationRequirements(BaseModel):
    """Documentation requirements."""

    require_readme: bool = True
    require_changelog: bool = False
    require_api_docs: bool = False
    min_public_docstring_ratio: float = 0.8


class CompanyConfiguration(BaseModel):
    """Complete company-level configuration."""

    name: str = "default"
    version: str = "1.0"
    coding_standards: CodingStandards = Field(default_factory=CodingStandards)
    review_policy: ReviewPolicy = Field(default_factory=ReviewPolicy)
    security_policy: SecurityPolicy = Field(default_factory=SecurityPolicy)
    branch_strategy: BranchStrategy = Field(default_factory=BranchStrategy)
    commit_convention: CommitConvention = Field(default_factory=CommitConvention)
    test_requirements: ProjectTestRequirements = Field(default_factory=ProjectTestRequirements)
    documentation_requirements: DocumentationRequirements = Field(default_factory=DocumentationRequirements)
    allowed_frameworks: list[str] = Field(default_factory=list)
    restricted_frameworks: list[str] = Field(default_factory=list)
    architecture_layers: list[dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def load_from_file(cls, path: Path) -> "CompanyConfiguration":
        """Load configuration from a JSON file."""
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
        return cls(**data)

    @classmethod
    def load_from_repo(cls, repo_root: Path) -> "CompanyConfiguration":
        """Load from .refactory/company.json in a repository."""
        config_path = repo_root / ".refactory" / "company.json"
        if config_path.is_file():
            return cls.load_from_file(config_path)
        return cls()

    def merge_with(self, override: "CompanyConfiguration") -> "CompanyConfiguration":
        """Merge with repository-level overrides."""
        base = self.model_dump()
        overrides = override.model_dump(exclude_defaults=True)
        merged = _deep_merge(base, overrides)
        return CompanyConfiguration(**merged)

    def save_to_file(self, path: Path) -> None:
        """Save configuration to file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            self.model_dump_json(indent=2),
            encoding="utf-8",
        )


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dicts, with override taking precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
