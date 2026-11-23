"""Static review prompt template (control-plane content for CLI)."""

from __future__ import annotations

from refactory_backend.schemas.prompts import PromptTemplateResponse

REVIEW_PROMPT = PromptTemplateResponse(
    name="review",
    version="1.0.0",
    description="Default pull-request review prompt skeleton for the Refactory CLI.",
    template=(
        "You are a senior code reviewer for repository {{repository_name}}.\n"
        "Review pull request #{{pr_number}} with focus on correctness, security, "
        "and maintainability.\n\n"
        "Context:\n{{related_context}}\n\n"
        "Diff summary:\n{{diff_summary}}\n\n"
        "Respond with a structured review: summary, risk_level, findings[]."
    ),
    variables=[
        "repository_name",
        "pr_number",
        "related_context",
        "diff_summary",
    ],
    metadata={
        "channel": "cli",
        "feature_flags": {
            "structured_findings": True,
            "security_focus": True,
        },
    },
)


def get_review_prompt() -> PromptTemplateResponse:
    return REVIEW_PROMPT
