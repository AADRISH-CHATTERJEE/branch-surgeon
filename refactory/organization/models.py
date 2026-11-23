"""Pydantic models for organization (company) rules."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

# Any retained for audit change payloads

RULE_TYPES = (
    "branch_naming",
    "commit_message",
    "pull_request",
    "file_path",
    "file_pattern",
    "code_pattern",
    "documentation",
    "testing",
    "security",
    "architecture",
    "custom",
)

SEVERITIES = ("blocker", "critical", "error", "warning", "info")


class OrganizationRuleCondition(BaseModel):
    """Single condition; rule-level condition_logic combines them (AND/OR)."""

    field: str = ""
    operator: str = "matches"
    value: str | int | float | list[str] | None = None
    pattern: str = ""


class OrganizationRulePayload(BaseModel):
    """Create/update payload and API representation for an organization rule."""

    id: str = ""
    name: str
    description: str = ""
    category: str = "custom"
    severity: str = "warning"
    enabled: bool = True
    rule_type: str = "custom"
    conditions: list[OrganizationRuleCondition] = Field(default_factory=list)
    condition_logic: Literal["and", "or"] = "and"
    message: str = ""
    documentation_url: str = ""
    blocking: bool = False
    organization_id: str | None = None
    team_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OrganizationRuleOut(BaseModel):
    """Canonical list/get/create/update response shape for organization rules.

    ``blocking`` is required so list endpoints never omit the field.
    """

    id: str
    name: str
    description: str = ""
    category: str = "custom"
    severity: str = "warning"
    enabled: bool = True
    rule_type: str = "custom"
    conditions: list[Any] = Field(default_factory=list)
    condition_logic: str = "and"
    message: str = ""
    documentation_url: str = ""
    blocking: bool
    organization_id: str | None = None
    team_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    source: str = "organization"


class OrganizationRuleAuditEntry(BaseModel):
    id: str
    rule_id: str
    action: str
    actor: str = "local"
    changes: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
