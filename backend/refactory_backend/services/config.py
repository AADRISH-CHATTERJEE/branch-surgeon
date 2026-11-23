"""Configuration service — versioned prompts/workflows and org/repo settings.

Delivers downloadable control-plane configuration to the CLI.
Never accepts or stores repository source code.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from refactory_backend.config import catalog
from refactory_backend.schemas.config import (
    AIProviderPreferences,
    CLIConfigResponse,
    ControlPlaneConfigBundle,
    DEFAULT_MODEL,
    FeatureFlags,
    OrganizationResponse,
    PromptListResponse,
    RepositoryResponse,
    ReviewPolicy,
)
from refactory_backend.schemas.prompts import PromptTemplateResponse
from refactory_backend.schemas.workflows import WorkflowDefinitionResponse


def _feature_flags_dict(flags: FeatureFlags) -> dict[str, bool]:
    data = flags.model_dump()
    extra = data.pop("flags", {}) or {}
    merged: dict[str, bool] = {
        key: bool(value) for key, value in data.items() if isinstance(value, bool)
    }
    for key, value in extra.items():
        if isinstance(value, bool):
            merged[str(key)] = value
    return merged


class ConfigService:
    """Resolve configuration for authenticated CLI clients."""

    def __init__(self, db: Session | None = None) -> None:
        # DB reserved for future persistence; catalog is the source of truth today.
        self._db = db

    def get_cli_config(
        self,
        *,
        organization_id: str | None = None,
        repository_id: str | None = None,
    ) -> CLIConfigResponse:
        """Compact configuration document for CLI startup."""
        org = catalog.get_organization(organization_id or catalog.DEFAULT_ORG_ID)
        if org is None:
            org = catalog.default_organization()

        flags = org.settings.feature_flags
        ai_prefs = org.settings.ai_preferences
        policy = org.settings.review_policy

        if repository_id:
            repo = catalog.get_repository(repository_id)
            if repo is not None:
                if repo.settings.feature_flags is not None:
                    flags = repo.settings.feature_flags
                if repo.settings.ai_preferences is not None:
                    ai_prefs = repo.settings.ai_preferences
                if repo.settings.review_policy is not None:
                    policy = repo.settings.review_policy

        prompts = self.list_prompts()
        workflows = self.list_workflows()
        model = self._resolve_model(ai_prefs)

        return CLIConfigResponse(
            prompt_version=prompts.default_version,
            workflow_version=workflows.default_version,
            ai_provider=ai_prefs.primary_provider,
            model=model,
            feature_flags=_feature_flags_dict(flags),
            limits=self._limits(ai_prefs, policy),
        )

    def get_aggregate_config(
        self,
        *,
        organization_id: str | None = None,
        repository_id: str | None = None,
    ) -> ControlPlaneConfigBundle:
        org = catalog.get_organization(organization_id or catalog.DEFAULT_ORG_ID)
        if org is None:
            org = catalog.default_organization()

        repo: RepositoryResponse | None = None
        if repository_id:
            repo = catalog.get_repository(repository_id)
        else:
            repo = catalog.default_repository()

        coding = org.settings.coding_standards
        policy = org.settings.review_policy
        flags = org.settings.feature_flags
        ai_prefs = org.settings.ai_preferences

        if repo is not None:
            if repo.settings.coding_standards is not None:
                coding = repo.settings.coding_standards
            if repo.settings.review_policy is not None:
                policy = repo.settings.review_policy
            if repo.settings.feature_flags is not None:
                flags = repo.settings.feature_flags
            if repo.settings.ai_preferences is not None:
                ai_prefs = repo.settings.ai_preferences

        return ControlPlaneConfigBundle(
            organization=org,
            repository=repo,
            prompts=self.list_prompts(),
            workflows=self.list_workflows(),
            coding_standards=coding,
            review_policy=policy,
            feature_flags=flags,
            ai_preferences=ai_prefs,
        )

    @staticmethod
    def _resolve_model(ai_prefs: AIProviderPreferences) -> str:
        """Resolve model from org/repo preferred_models for the primary provider."""
        preferred = ai_prefs.preferred_models.get(ai_prefs.primary_provider)
        if preferred:
            return preferred
        return DEFAULT_MODEL

    @staticmethod
    def _limits(
        ai_prefs: AIProviderPreferences, policy: ReviewPolicy
    ) -> dict[str, int | float]:
        return {
            "max_tokens": 6000,
            "max_retrieved_files": 8,
            "max_symbols": 16,
            "max_related_files": 8,
            "max_graph_depth": 3,
            "max_findings": policy.max_findings,
            "timeout_seconds": ai_prefs.timeout_seconds,
            "max_retries": ai_prefs.max_retries,
        }

    def list_prompts(self) -> PromptListResponse:
        return catalog.prompt_list()

    def list_workflows(self) -> WorkflowListResponse:
        return catalog.workflow_list()

    def get_prompt(
        self, name: str, version: str | None = None
    ) -> PromptTemplateResponse | None:
        return catalog.get_prompt(name, version)

    def get_workflow(
        self, name: str, version: str | None = None
    ) -> WorkflowDefinitionResponse | None:
        return catalog.get_workflow(name, version)

    def get_organization(self, org_id: str) -> OrganizationResponse | None:
        return catalog.get_organization(org_id)

    def get_repository(self, repo_id: str) -> RepositoryResponse | None:
        return catalog.get_repository(repo_id)
