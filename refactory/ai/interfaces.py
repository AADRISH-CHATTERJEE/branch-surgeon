"""AI provider contract."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from refactory.ai.capabilities import ProviderCapabilities
from refactory.ai.health import ProviderHealth
from refactory.ai.models import AIRequest, AIResponse


@runtime_checkable
class AIProvider(Protocol):
    """Interface for LLM backends (Gemini, OpenAI, Mock, …)."""

    @property
    def name(self) -> str:
        """Short provider identifier (e.g. ``gemini``, ``openai``, ``mock``)."""
        ...

    @property
    def model(self) -> str:
        """Configured model id."""
        ...

    def generate(self, request: AIRequest) -> AIResponse:
        """Generate a completion for ``request``."""
        ...

    def capabilities(self) -> ProviderCapabilities:
        """Declare what this provider/model supports."""
        ...

    def health_check(self) -> ProviderHealth:
        """Lightweight readiness probe (no full generation required)."""
        ...

    def stream(self, request: AIRequest) -> Iterator[str]:
        """Future-ready streaming API (may fall back to a single chunk)."""
        ...
