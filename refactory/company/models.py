"""Company Rules & Standards — models for pre-review gate and config."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class GateOutcome(str, Enum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"


class CompanyRuleViolation(BaseModel):
    """A single company-rule finding."""

    rule: str
    message: str
    severity: str = "error"  # error | warning | info | blocker
    blocking: bool = False
    file_path: str = ""
    detail: str = ""
    source: str = "builtin"  # builtin | organization
    documentation_url: str = ""


class BranchRuleConfig(BaseModel):
    pattern: str = ""
    block: bool = True
    message: str = ""


class CommitRuleConfig(BaseModel):
    pattern: str = ""
    block: bool = True
    message: str = ""


class ForbiddenDependency(BaseModel):
    from_layer: str = Field(alias="from", default="")
    to_layer: str = Field(alias="to", default="")
    message: str = ""

    model_config = {"populate_by_name": True}


class ArchitectureRuleConfig(BaseModel):
    forbidden_dependencies: list[ForbiddenDependency] = Field(default_factory=list)
    block: bool = True


class TestingRuleConfig(BaseModel):
    require_tests: bool = False
    block: bool = False
    test_path_pattern: str = r"(^|/)tests?/|(^|/)test_[^/]+\.py$|_test\.py$"
    message: str = ""


class CompanyStandards(BaseModel):
    """Parsed company standards from .refactory/company.yaml."""

    organization_name: str = "default"
    branch: BranchRuleConfig | None = None
    commit: CommitRuleConfig | None = None
    architecture: ArchitectureRuleConfig | None = None
    testing: TestingRuleConfig | None = None
    # Raw extras preserved for forward compatibility
    extras: dict = Field(default_factory=dict)


class CompanyGuidelines(BaseModel):
    """Markdown guideline documents loaded from .refactory/."""

    architecture_md: str = ""
    coding_guidelines_md: str = ""
    security_guidelines_md: str = ""
    testing_guidelines_md: str = ""

    def combined_for_prompt(self) -> str:
        """Merge non-empty guideline docs into a single standards string."""
        parts: list[str] = []
        if self.architecture_md.strip():
            parts.append("## Company Architecture Guidelines\n\n" + self.architecture_md.strip())
        if self.coding_guidelines_md.strip():
            parts.append("## Company Coding Guidelines\n\n" + self.coding_guidelines_md.strip())
        if self.security_guidelines_md.strip():
            parts.append("## Company Security Guidelines\n\n" + self.security_guidelines_md.strip())
        if self.testing_guidelines_md.strip():
            parts.append("## Company Testing Guidelines\n\n" + self.testing_guidelines_md.strip())
        return "\n\n".join(parts)

    def to_documentation(self) -> "CompanyDocumentation":
        return CompanyDocumentation(
            architecture=self.architecture_md,
            coding_guidelines=self.coding_guidelines_md,
            security_guidelines=self.security_guidelines_md,
            testing_guidelines=self.testing_guidelines_md,
        )


class CompanyDocumentation(BaseModel):
    """Plain markdown company documents for AI prompt context (not a rule engine)."""

    architecture: str = ""
    coding_guidelines: str = ""
    security_guidelines: str = ""
    testing_guidelines: str = ""

    def combined_for_prompt(self) -> str:
        """Merge non-empty docs into a single prompt section body."""
        parts: list[str] = []
        if self.architecture.strip():
            parts.append("## Company Architecture Guidelines\n\n" + self.architecture.strip())
        if self.coding_guidelines.strip():
            parts.append("## Company Coding Guidelines\n\n" + self.coding_guidelines.strip())
        if self.security_guidelines.strip():
            parts.append("## Company Security Guidelines\n\n" + self.security_guidelines.strip())
        if self.testing_guidelines.strip():
            parts.append("## Company Testing Guidelines\n\n" + self.testing_guidelines.strip())
        return "\n\n".join(parts)

    def to_guidelines(self) -> CompanyGuidelines:
        return CompanyGuidelines(
            architecture_md=self.architecture,
            coding_guidelines_md=self.coding_guidelines,
            security_guidelines_md=self.security_guidelines,
            testing_guidelines_md=self.testing_guidelines,
        )


class GateResult(BaseModel):
    """Outcome of the pre-review company rules check."""

    outcome: GateOutcome = GateOutcome.PASS
    violations: list[CompanyRuleViolation] = Field(default_factory=list)
    guidelines: CompanyGuidelines = Field(default_factory=CompanyGuidelines)
    standards: CompanyStandards = Field(default_factory=CompanyStandards)

    @property
    def blockers(self) -> list[CompanyRuleViolation]:
        return [v for v in self.violations if v.blocking]

    @property
    def warnings(self) -> list[CompanyRuleViolation]:
        return [v for v in self.violations if not v.blocking]

    def summary_text(self) -> str:
        if self.outcome == GateOutcome.PASS and not self.violations:
            return "All company rules passed."
        lines: list[str] = []
        if self.blockers:
            lines.append(f"BLOCKED by {len(self.blockers)} mandatory company rule(s):")
            for v in self.blockers:
                lines.append(f"  - [{v.rule}] {v.message}")
                if v.detail:
                    lines.append(f"    {v.detail}")
        if self.warnings:
            lines.append(f"{len(self.warnings)} warning(s):")
            for v in self.warnings:
                lines.append(f"  - [{v.rule}] {v.message}")
        return "\n".join(lines)


class GateContext(BaseModel):
    """Resolved git + PR context used by the company-rules gate."""

    branch_name: str = ""
    base_branch: str = ""
    commit_message: str = ""
    commit_messages: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    head_sha: str | None = None
    source: str = "unknown"  # git | pr | override | mixed

