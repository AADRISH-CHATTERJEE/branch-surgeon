"""Typed models for BackendClient responses and local token storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class StoredAuth(BaseModel):
    """Persisted JWT session under ``~/.refactory/auth.json`` (never passwords)."""

    access_token: str
    refresh_token: str
    expires_at: datetime
    backend_url: str
    token_type: str = "bearer"


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class BackendUser(BaseModel):
    id: int
    email: str
    full_name: str
    is_active: bool
    is_superuser: bool
    created_at: datetime


class ReviewPrompt(BaseModel):
    name: str
    version: str
    description: str
    template: str
    variables: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowStep(BaseModel):
    id: str
    name: str
    description: str
    optional: bool = False


class ReviewWorkflow(BaseModel):
    name: str
    version: str
    description: str
    steps: list[WorkflowStep] = Field(default_factory=list)
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TelemetryPayload(BaseModel):
    event_type: str
    cli_version: str | None = None
    os_name: str | None = None
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class TelemetryAck(BaseModel):
    id: int
    event_type: str
    accepted: bool = True
    received_at: datetime


class CodingStandards(BaseModel):
    style_guide: str = "pep8"
    max_complexity: int = 10
    require_type_hints: bool = True
    banned_imports: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class ReviewPolicy(BaseModel):
    min_severity: str = "info"
    block_on_critical: bool = True
    include_security: bool = True
    include_maintainability: bool = True
    max_findings: int = 50
    require_file_paths: bool = True
    extra: dict[str, Any] = Field(default_factory=dict)


class FeatureFlags(BaseModel):
    use_remote_prompts: bool = True
    use_remote_workflows: bool = True
    telemetry_enabled: bool = True
    hybrid_retrieval: bool = True
    graph_context: bool = True
    json_schema_validation: bool = True
    flags: dict[str, bool] = Field(default_factory=dict)


class AIProviderPreferences(BaseModel):
    primary_provider: str = "mock"
    fallback_provider: str | None = None
    preferred_models: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = 60.0
    max_retries: int = 3


class OrganizationSettings(BaseModel):
    coding_standards: CodingStandards = Field(default_factory=CodingStandards)
    review_policy: ReviewPolicy = Field(default_factory=ReviewPolicy)
    feature_flags: FeatureFlags = Field(default_factory=FeatureFlags)
    ai_preferences: AIProviderPreferences = Field(default_factory=AIProviderPreferences)
    extra: dict[str, Any] = Field(default_factory=dict)


class OrganizationConfig(BaseModel):
    id: str
    name: str
    slug: str
    settings: OrganizationSettings
    metadata: dict[str, Any] = Field(default_factory=dict)


class RepositorySettings(BaseModel):
    coding_standards: CodingStandards | None = None
    review_policy: ReviewPolicy | None = None
    feature_flags: FeatureFlags | None = None
    ai_preferences: AIProviderPreferences | None = None
    default_branch: str = "main"
    languages: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class RepositoryConfig(BaseModel):
    id: str
    organization_id: str
    name: str
    slug: str
    remote_url: str | None = None
    settings: RepositorySettings
    metadata: dict[str, Any] = Field(default_factory=dict)


class PromptVersionSummary(BaseModel):
    name: str
    version: str
    description: str
    is_default: bool = False
    variables: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PromptList(BaseModel):
    items: list[PromptVersionSummary] = Field(default_factory=list)
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


class WorkflowList(BaseModel):
    items: list[WorkflowVersionSummary] = Field(default_factory=list)
    default_name: str = "review"
    default_version: str = "1.0.0"


class CLIConfig(BaseModel):
    """Compact control-plane configuration from GET /config (CLI startup)."""

    prompt_version: str
    workflow_version: str
    ai_provider: str
    model: str
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    limits: dict[str, int | float] = Field(default_factory=dict)


class ControlPlaneConfigBundle(BaseModel):
    """Full aggregate configuration downloaded by the CLI (never includes source)."""

    schema_version: str = "1.0.0"
    organization: OrganizationConfig
    repository: RepositoryConfig | None = None
    prompts: PromptList
    workflows: WorkflowList
    coding_standards: CodingStandards
    review_policy: ReviewPolicy
    feature_flags: FeatureFlags
    ai_preferences: AIProviderPreferences
    notes: list[str] = Field(default_factory=list)


# Back-compat alias
ControlPlaneConfig = CLIConfig
