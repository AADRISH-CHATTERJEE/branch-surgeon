"""Versioned control-plane catalog (prompts, workflows, org/repo settings).

Static seed data — no repository source code is ever stored here.
"""

from __future__ import annotations

from copy import deepcopy

from refactory_backend.prompts.review import REVIEW_PROMPT
from refactory_backend.schemas.config import (
    AIProviderPreferences,
    CodingStandards,
    DEFAULT_FALLBACK_PROVIDER,
    DEFAULT_PREFERRED_MODELS,
    DEFAULT_PRIMARY_PROVIDER,
    FeatureFlags,
    OrganizationResponse,
    OrganizationSettings,
    PromptListResponse,
    PromptVersionSummary,
    RepositoryResponse,
    RepositorySettings,
    ReviewPolicy,
    WorkflowListResponse,
    WorkflowVersionSummary,
)
from refactory_backend.schemas.prompts import PromptTemplateResponse
from refactory_backend.schemas.workflows import WorkflowDefinitionResponse, WorkflowStep
from refactory_backend.workflows.review import REVIEW_WORKFLOW

DEFAULT_ORG_ID = "org_default"
DEFAULT_REPO_ID = "repo_default"

_PROMPT_V2 = PromptTemplateResponse(
    name="review",
    version="2.0.0",
    description="Compact sectioned review prompt (PromptBuilder v2 compatible).",
    template=(
        "You are a senior code reviewer for {{repository_name}}.\n"
        "PR #{{pr_number}}\n\n"
        "==================== CONTEXT ====================\n"
        "{{related_context}}\n\n"
        "==================== DIFF ====================\n"
        "{{diff_summary}}\n\n"
        "Return JSON: summary, overall_risk, confidence, findings[]."
    ),
    variables=[
        "repository_name",
        "pr_number",
        "related_context",
        "diff_summary",
    ],
    metadata={
        "channel": "cli",
        "template_family": "review",
        "feature_flags": {
            "structured_findings": True,
            "security_focus": True,
            "compact_sections": True,
        },
    },
)

_WORKFLOW_V2 = WorkflowDefinitionResponse(
    name="review",
    version="2.0.0",
    description="Review workflow with hybrid retrieval and graph context.",
    steps=[
        *REVIEW_WORKFLOW.steps,
        WorkflowStep(
            id="hybrid_rank",
            name="Hybrid rank context",
            description="Combine semantic and graph signals for context selection.",
            optional=True,
        ),
    ],
    feature_flags={
        **REVIEW_WORKFLOW.feature_flags,
        "hybrid_retrieval": True,
        "graph_context": True,
    },
    metadata={
        **REVIEW_WORKFLOW.metadata,
        "template_family": "review",
    },
)


def default_organization() -> OrganizationResponse:
    settings = OrganizationSettings(
        coding_standards=CodingStandards(
            style_guide="pep8",
            max_complexity=10,
            require_type_hints=True,
            banned_imports=["pickle", "subprocess"],
        ),
        review_policy=ReviewPolicy(
            min_severity="info",
            block_on_critical=True,
            include_security=True,
            max_findings=50,
        ),
        feature_flags=FeatureFlags(
            use_remote_prompts=True,
            use_remote_workflows=True,
            telemetry_enabled=True,
            hybrid_retrieval=True,
            graph_context=True,
            json_schema_validation=True,
            flags={"experimental_streaming": False},
        ),
        ai_preferences=AIProviderPreferences(
            primary_provider=DEFAULT_PRIMARY_PROVIDER,
            fallback_provider=DEFAULT_FALLBACK_PROVIDER,
            preferred_models=dict(DEFAULT_PREFERRED_MODELS),
        ),
    )
    return OrganizationResponse(
        id=DEFAULT_ORG_ID,
        name="Default Organization",
        slug="default",
        settings=settings,
        metadata={"seed": True},
    )


def default_repository() -> RepositoryResponse:
    return RepositoryResponse(
        id=DEFAULT_REPO_ID,
        organization_id=DEFAULT_ORG_ID,
        name="default-repository",
        slug="default",
        remote_url=None,
        settings=RepositorySettings(
            default_branch="main",
            languages=["python"],
            review_policy=ReviewPolicy(min_severity="low", max_findings=40),
        ),
        metadata={
            "seed": True,
            "note": "Control-plane metadata only; repository source is never uploaded.",
        },
    )


def all_prompts() -> list[PromptTemplateResponse]:
    v1 = REVIEW_PROMPT.model_copy(
        update={
            "metadata": {
                **REVIEW_PROMPT.metadata,
                "is_default": False,
                "template_family": "review",
            }
        }
    )
    v2 = _PROMPT_V2.model_copy(
        update={
            "metadata": {
                **_PROMPT_V2.metadata,
                "is_default": True,
            }
        }
    )
    return [v1, v2]


def all_workflows() -> list[WorkflowDefinitionResponse]:
    v1 = REVIEW_WORKFLOW.model_copy(
        update={
            "metadata": {
                **REVIEW_WORKFLOW.metadata,
                "is_default": False,
                "template_family": "review",
            }
        }
    )
    v2 = _WORKFLOW_V2.model_copy(
        update={
            "metadata": {
                **_WORKFLOW_V2.metadata,
                "is_default": True,
            }
        }
    )
    return [v1, v2]


def prompt_list() -> PromptListResponse:
    items = [
        PromptVersionSummary(
            name=p.name,
            version=p.version,
            description=p.description,
            is_default=bool(p.metadata.get("is_default")),
            variables=list(p.variables),
            metadata={k: v for k, v in p.metadata.items() if k != "is_default"},
        )
        for p in all_prompts()
    ]
    default = next((i for i in items if i.is_default), items[-1])
    return PromptListResponse(
        items=items,
        default_name=default.name,
        default_version=default.version,
    )


def workflow_list() -> WorkflowListResponse:
    items = [
        WorkflowVersionSummary(
            name=w.name,
            version=w.version,
            description=w.description,
            is_default=bool(w.metadata.get("is_default")),
            step_count=len(w.steps),
            feature_flags=dict(w.feature_flags),
            metadata={k: v for k, v in w.metadata.items() if k != "is_default"},
        )
        for w in all_workflows()
    ]
    default = next((i for i in items if i.is_default), items[-1])
    return WorkflowListResponse(
        items=items,
        default_name=default.name,
        default_version=default.version,
    )


def get_prompt(name: str, version: str | None = None) -> PromptTemplateResponse | None:
    prompts = [p for p in all_prompts() if p.name == name]
    if not prompts:
        return None
    if version is None:
        return next(
            (p for p in prompts if p.metadata.get("is_default")),
            prompts[-1],
        )
    for prompt in prompts:
        if prompt.version == version:
            return prompt
    return None


def get_workflow(
    name: str, version: str | None = None
) -> WorkflowDefinitionResponse | None:
    workflows = [w for w in all_workflows() if w.name == name]
    if not workflows:
        return None
    if version is None:
        return next(
            (w for w in workflows if w.metadata.get("is_default")),
            workflows[-1],
        )
    for workflow in workflows:
        if workflow.version == version:
            return workflow
    return None


def get_organization(org_id: str) -> OrganizationResponse | None:
    org = default_organization()
    if org_id in {org.id, org.slug}:
        return deepcopy(org)
    return None


def get_repository(repo_id: str) -> RepositoryResponse | None:
    repo = default_repository()
    if repo_id in {repo.id, repo.slug}:
        return deepcopy(repo)
    return None
