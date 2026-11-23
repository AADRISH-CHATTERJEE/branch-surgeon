"""Deterministic mock provider for local/dev/tests (no network)."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING

from refactory.ai.capabilities import ProviderCapabilities, capabilities_for
from refactory.ai.health import HealthStatus, ProviderHealth
from refactory.ai.models import AIRequest, AIResponse

if TYPE_CHECKING:
    from loguru import Logger


class MockProvider:
    """Returns a stable, content-derived response — never calls an external API."""

    def __init__(
        self,
        model: str = "mock-review-1",
        logger: "Logger | None" = None,
        *,
        fixed_text: str | None = None,
        latency_ms: float = 1.0,
    ) -> None:
        self._model = model
        self._logger = logger
        self._fixed_text = fixed_text
        self._latency_ms = latency_ms

    @property
    def name(self) -> str:
        return "mock"

    @property
    def model(self) -> str:
        return self._model

    def capabilities(self) -> ProviderCapabilities:
        return capabilities_for(self.name, self._model)

    def health_check(self) -> ProviderHealth:
        started = time.perf_counter()
        # Instant local probe
        latency = (time.perf_counter() - started) * 1000.0
        return ProviderHealth(
            provider=self.name,
            model=self._model,
            status=HealthStatus.HEALTHY,
            latency_ms=round(latency, 3),
            message="mock provider ready",
        )

    def stream(self, request: AIRequest) -> Iterator[str]:
        """Future-ready: yields the full mock completion as a single chunk."""
        yield self.generate(request).text

    def generate(self, request: AIRequest) -> AIResponse:
        started = time.perf_counter()
        if self._fixed_text is not None:
            text = self._fixed_text
        else:
            digest = hashlib.sha256(
                (request.system_prompt + "\n" + request.user_prompt).encode("utf-8")
            ).hexdigest()[:12]
            text = (
                "MOCK_REVIEW\n"
                f"digest={digest}\n"
                f"pr={request.metadata.pr_number}\n"
                f"repo={request.metadata.repository_name}\n"
                "summary: Deterministic mock review response.\n"
                "risk_level: low\n"
                "findings: []\n"
                "confidence: 0.5\n"
            )
        elapsed = (time.perf_counter() - started) * 1000.0
        if self._logger is not None:
            self._logger.debug("MockProvider.generate (model={})", self._model)
        latency = max(elapsed, self._latency_ms)
        return AIResponse(
            text=text,
            provider=self.name,
            model=self._model,
            prompt_tokens=len(request.system_prompt.split()) + len(request.user_prompt.split()),
            completion_tokens=len(text.split()),
            finish_reason="stop",
            latency_ms=round(latency, 3),
        )
