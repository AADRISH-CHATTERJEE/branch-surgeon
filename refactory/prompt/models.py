"""Typed models for deterministic review prompt assembly."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from refactory.backend.models import ReviewPrompt, ReviewWorkflow
from refactory.github.models import PullRequest
from refactory.graph.models import RepositoryGraph
from refactory.indexer.models import RepositoryIndex
from refactory.prompt.budget import ContextBudget
from refactory.retrieval.models import RankedContext, RetrievedFile, SearchResult
from refactory.review.models import Repository


class PromptSection(BaseModel):
    """One independently rendered prompt section."""

    key: str
    title: str
    body: str
    order: int = 0


class PromptMetadata(BaseModel):
    """Provenance and assembly details (never sent as model instructions alone)."""

    template_source: str  # "backend" | "local_default"
    template_name: str = "review"
    template_version: str = "0.0.0"
    repository_name: str = ""
    pr_number: int = 0
    section_keys: list[str] = Field(default_factory=list)
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    extras: dict[str, Any] = Field(default_factory=dict)


class PromptRequest(BaseModel):
    """Fully assembled prompts ready for a future AI provider (not invoked here)."""

    system_prompt: str
    user_prompt: str
    metadata: PromptMetadata
    sections: list[PromptSection] = Field(default_factory=list)


class PromptContext(BaseModel):
    """All inputs required to assemble a review prompt."""

    pull_request: PullRequest
    repository: Repository | None = None
    index: RepositoryIndex | None = None
    graph: RepositoryGraph | None = None
    retrieval: SearchResult | None = None
    ranked_context: RankedContext | None = None
    related_files: list[RetrievedFile] = Field(default_factory=list)
    impacted_files: list[str] = Field(default_factory=list)
    dependency_cycles: list[list[str]] = Field(default_factory=list)
    workflow: ReviewWorkflow | None = None
    prompt_template: ReviewPrompt | None = None
    coding_standards: str | None = None
    company_documentation: str | None = None
    budget: ContextBudget | None = None
