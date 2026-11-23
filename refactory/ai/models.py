"""Provider-agnostic AI request/response models."""

from __future__ import annotations

from pydantic import BaseModel, Field

from refactory.prompt.models import PromptMetadata, PromptRequest


class AIRequest(BaseModel):
    """Normalized generation request for any AIProvider."""

    system_prompt: str
    user_prompt: str
    metadata: PromptMetadata = Field(
        default_factory=lambda: PromptMetadata(template_source="local_default")
    )

    @classmethod
    def from_prompt_request(cls, prompt: PromptRequest) -> "AIRequest":
        """Adapt a PromptRequest without coupling the gateway to PromptBuilder."""
        return cls(
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
            metadata=prompt.metadata,
        )


class AIResponse(BaseModel):
    """Normalized generation response from any AIProvider."""

    text: str
    provider: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None
    latency_ms: float = 0.0
    estimated_cost_usd: float | None = None
