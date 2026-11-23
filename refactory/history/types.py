"""Canonical analysis_type values for History."""

from __future__ import annotations

# Stable identifiers stored in analysis_history.analysis_type
ANALYSIS_TYPES = (
    "review",
    "recommendation",
    "repository_health",
    "repository_graph",
    "branch_surgeon",
    "rules_evaluation",
    "patch_generation",
    "patch_apply",
    "transform",
    "index",
    "organization_admin",
    "organization_rule",
)

# Map Activity command / result_type → History analysis_type
COMMAND_TO_ANALYSIS_TYPE: dict[str, str] = {
    "review": "review",
    "review-suggestion": "review",
    "recommend": "recommendation",
    "health": "repository_health",
    "repository-health": "repository_health",
    "graph": "repository_graph",
    "surgeon": "branch_surgeon",
    "branch-surgeon": "branch_surgeon",
    "rules-check": "rules_evaluation",
    "rules": "rules_evaluation",
    "patch": "patch_generation",
    "recommendation-patch": "patch_generation",
    "patch-apply": "patch_apply",
    "patch-rollback": "patch_apply",
    "transform": "transform",
    "apply": "transform",
    "rollback": "transform",
    "transformation-preview": "transform",
    "transformation-applied": "transform",
    "transformation-rollback": "transform",
    "index": "index",
    "embed": "index",
    # Organization administration
    "organization-created": "organization_admin",
    "organization-updated": "organization_admin",
    "organization-deleted": "organization_admin",
    "team-created": "organization_admin",
    "team-updated": "organization_admin",
    "team-deleted": "organization_admin",
    "member-invited": "organization_admin",
    "member-updated": "organization_admin",
    "member-removed": "organization_admin",
    "team-member-added": "organization_admin",
    "team-member-removed": "organization_admin",
    "organization-repository-linked": "organization_admin",
    "organization-repository-unlinked": "organization_admin",
    "team-repository-assigned": "organization_admin",
    "team-repository-unassigned": "organization_admin",
    # Organization rules
    "organization-rule-created": "organization_rule",
    "organization-rule-updated": "organization_rule",
    "organization-rule-deleted": "organization_rule",
    "organization-rule-enabled": "organization_rule",
    "organization-rule-disabled": "organization_rule",
    "organization-rule-duplicated": "organization_rule",
}

RESULT_TYPE_TO_ANALYSIS_TYPE: dict[str, str] = {
    "recommendations": "recommendation",
    "recommendation_lifecycle": "recommendation",
    "company_rules": "rules_evaluation",
    "transformation_plan": "transform",
    "transformation_applied": "transform",
    "transformation_rollback": "transform",
    "review": "review",
    "review_suggestion": "review",
    "patch": "patch_generation",
    "patch_apply": "patch_apply",
    "graph": "repository_graph",
    "index": "index",
    "health": "repository_health",
    "surgeon": "branch_surgeon",
    "organization_admin": "organization_admin",
    "organization_rule": "organization_rule",
}


def resolve_analysis_type(
    *,
    command: str | None = None,
    result_type: str | None = None,
    explicit: str | None = None,
) -> str:
    if explicit and explicit in ANALYSIS_TYPES:
        return explicit
    if result_type and result_type in RESULT_TYPE_TO_ANALYSIS_TYPE:
        return RESULT_TYPE_TO_ANALYSIS_TYPE[result_type]
    if command:
        key = command.lower().strip()
        if key in COMMAND_TO_ANALYSIS_TYPE:
            return COMMAND_TO_ANALYSIS_TYPE[key]
        for prefix, mapped in COMMAND_TO_ANALYSIS_TYPE.items():
            if prefix in key:
                return mapped
    return "index"
