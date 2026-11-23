"""Configuration control-plane schemas (CLI download only — no source code)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CodingStandards(BaseModel):
    """Organization/repo coding standards the CLI applies locally."""

    style_guide: str = "pep8"
    max_complexity: int = 10
    require_type_hints: bool = True
    banned_imports: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class ReviewPolicy(BaseModel):
    """Review policy knobs downloaded by the CLI (executed locally)."""

    min_severity: str = "info"
    block_on_critical: bool = True
    include_security: bool = True
    include_maintainability: bool = True
    max_findings: int = 50
    require_file_paths: bool = True
    extra: dict[str, Any] = Field(default_factory=dict)


class FeatureFlags(BaseModel):
    """Feature flags for CLI behavior."""

    use_remote_prompts: bool = True
    use_remote_workflows: bool = True
    telemetry_enabled: bool = True
    hybrid_retrieval: bool = True
    graph_context: bool = True
    json_schema_validation: bool = True
    flags: dict[str, bool] = Field(default_factory=dict)


# Single source of truth for control-plane AI defaults (catalog + schema).
DEFAULT_PRIMARY_PROVIDER = "openai"
DEFAULT_FALLBACK_PROVIDER = "mock"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_PREFERRED_MODELS: dict[str, str] = {
    "openai": DEFAULT_MODEL,
    "gemini": "gemini-2.0-flash",
    "mock": "mock-review-1",
}


class AIProviderPreferences(BaseModel):
    """Preferred AI providers/models — credentials stay on the CLI."""

    primary_provider: str = DEFAULT_PRIMARY_PROVIDER
    fallback_provider: str | None = DEFAULT_FALLBACK_PROVIDER
    preferred_models: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_PREFERRED_MODELS)
    )
    timeout_seconds: float = 60.0
    max_retries: int = 3


class OrganizationSettings(BaseModel):
    coding_standards: CodingStandards = Field(default_factory=CodingStandards)
    review_policy: ReviewPolicy = Field(default_factory=ReviewPolicy)
    feature_flags: FeatureFlags = Field(default_factory=FeatureFlags)
    ai_preferences: AIProviderPreferences = Field(default_factory=AIProviderPreferences)
    extra: dict[str, Any] = Field(default_factory=dict)


class OrganizationResponse(BaseModel):
    id: str
    name: str
    slug: str
    settings: OrganizationSettings
    metadata: dict[str, Any] = Field(default_factory=dict)


class RepositorySettings(BaseModel):
    """Per-repository overrides. Never includes source code or file contents."""

    coding_standards: CodingStandards | None = None
    review_policy: ReviewPolicy | None = None
    feature_flags: FeatureFlags | None = None
    ai_preferences: AIProviderPreferences | None = None
    default_branch: str = "main"
    languages: list[str] = Field(default_factory=lambda: ["python"])
    extra: dict[str, Any] = Field(default_factory=dict)


class RepositoryResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    slug: str
    remote_url: str | None = None
    settings: RepositorySettings
    metadata: dict[str, Any] = Field(
        default_factory=lambda: {
            "note": "Control-plane metadata only; repository source is never uploaded.",
        }
    )


class PromptVersionSummary(BaseModel):
    name: str
    version: str
    description: str
    is_default: bool = False
    variables: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PromptListResponse(BaseModel):
    items: list[PromptVersionSummary]
    default_name: str = "review"
    default_version: str = "1.0.0"


class WorkflowVersionSummary(BaseModel):
    name: str
    version: str
    description: str
    is_default: bool = False
    step_count: int = 0
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowListResponse(BaseModel):
    items: list[WorkflowVersionSummary]
    default_name: str = "review"
    default_version: str = "1.0.0"


class CLIConfigResponse(BaseModel):
    """Compact control-plane configuration for CLI startup (no source code)."""

    prompt_version: str
    workflow_version: str
    ai_provider: str
    model: str
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    limits: dict[str, int | float] = Field(default_factory=dict)


class ControlPlaneConfigBundle(BaseModel):
    """Full aggregate configuration bundle (org/repo/settings)."""

    schema_version: str = "1.0.0"
    organization: OrganizationResponse
    repository: RepositoryResponse | None = None
    prompts: PromptListResponse
    workflows: WorkflowListResponse
    coding_standards: CodingStandards
    review_policy: ReviewPolicy
    feature_flags: FeatureFlags
    ai_preferences: AIProviderPreferences
    notes: list[str] = Field(
        default_factory=lambda: [
            "CLI downloads configuration only.",
            "Backend never receives repository source code.",
            "AI credentials remain local to the CLI.",
        ]
    )


# Back-compat alias used by older imports/tests
ControlPlaneConfig = ControlPlaneConfigBundle
