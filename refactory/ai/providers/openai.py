"""OpenAI Chat Completions provider (HTTP via httpx)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import httpx

from refactory.ai.capabilities import ProviderCapabilities, capabilities_for
from refactory.ai.health import HealthStatus, ProviderHealth
from refactory.ai.models import AIRequest, AIResponse
from refactory.core.exceptions import (
    AIProviderError,
    ConfigurationError,
    RateLimitAIProviderError,
    TransientAIProviderError,
)

if TYPE_CHECKING:
    from loguru import Logger

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider:
    def __init__(
        self,
        api_key: str | None,
        model: str | None,
        logger: "Logger",
        *,
        timeout_seconds: float = 60.0,
        base_url: str = OPENAI_CHAT_URL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip() or None
        self._model = (model or DEFAULT_OPENAI_MODEL).strip()
        self._logger = logger
        self._timeout = timeout_seconds
        self._base_url = base_url
        self._transport = transport

    @property
    def name(self) -> str:
        return "openai"

    @property
    def model(self) -> str:
        return self._model

    def capabilities(self) -> ProviderCapabilities:
        return capabilities_for(self.name, self._model)

    def health_check(self) -> ProviderHealth:
        started = time.perf_counter()
        if not self._api_key:
            return ProviderHealth(
                provider=self.name,
                model=self._model,
                status=HealthStatus.UNHEALTHY,
                message="OPENAI_API_KEY is not configured",
            )
        # Models list is a cheap authenticated readiness probe.
        models_url = self._base_url.replace("/chat/completions", "/models")
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            with httpx.Client(timeout=min(self._timeout, 10.0), transport=self._transport) as client:
                response = client.get(models_url, headers=headers)
            latency = (time.perf_counter() - started) * 1000.0
            if response.status_code == 429:
                return ProviderHealth(
                    provider=self.name,
                    model=self._model,
                    status=HealthStatus.DEGRADED,
                    latency_ms=round(latency, 3),
                    message="rate limited",
                )
            if response.status_code >= 400:
                return ProviderHealth(
                    provider=self.name,
                    model=self._model,
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=round(latency, 3),
                    message=f"HTTP {response.status_code}",
                )
            return ProviderHealth(
                provider=self.name,
                model=self._model,
                status=HealthStatus.HEALTHY,
                latency_ms=round(latency, 3),
                message="ok",
            )
        except httpx.TimeoutException:
            return ProviderHealth(
                provider=self.name,
                model=self._model,
                status=HealthStatus.DEGRADED,
                message="timeout",
            )
        except httpx.RequestError as exc:
            return ProviderHealth(
                provider=self.name,
                model=self._model,
                status=HealthStatus.UNHEALTHY,
                message=str(exc),
            )

    def stream(self, request: AIRequest) -> Iterator[str]:
        """Future-ready streaming stub — currently yields one full completion chunk."""
        yield self.generate(request).text

    def generate(self, request: AIRequest) -> AIResponse:
        if not self._api_key:
            raise ConfigurationError("OPENAI_API_KEY is not configured")

        started = time.perf_counter()
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": 0.2,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.post(self._base_url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise TransientAIProviderError(
                f"OpenAI request timed out after {self._timeout}s"
            ) from exc
        except httpx.RequestError as exc:
            raise TransientAIProviderError(f"OpenAI request failed: {exc}") from exc

        latency_ms = (time.perf_counter() - started) * 1000.0
        if response.status_code == 429:
            raise RateLimitAIProviderError(
                f"OpenAI rate limited (429): {response.text[:300]}",
            )
        if response.status_code == 408 or response.status_code >= 500:
            raise TransientAIProviderError(
                f"OpenAI transient error ({response.status_code}): {response.text[:300]}",
            )
        if response.status_code >= 400:
            raise AIProviderError(
                f"OpenAI error ({response.status_code}): {response.text[:300]}",
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise AIProviderError("OpenAI returned non-JSON response") from exc

        return self._parse_response(data, latency_ms=latency_ms)

    def _parse_response(self, data: dict[str, Any], *, latency_ms: float) -> AIResponse:
        choices = data.get("choices") or []
        if not choices:
            raise AIProviderError("OpenAI response contained no choices")
        message = choices[0].get("message") or {}
        text = message.get("content")
        if not isinstance(text, str) or not text.strip():
            raise AIProviderError("OpenAI response missing message content")
        usage = data.get("usage") or {}
        self._logger.debug("OpenAIProvider.generate ok (model={})", self._model)
        return AIResponse(
            text=text,
            provider=self.name,
            model=str(data.get("model") or self._model),
            prompt_tokens=_optional_int(usage.get("prompt_tokens")),
            completion_tokens=_optional_int(usage.get("completion_tokens")),
            finish_reason=choices[0].get("finish_reason"),
            latency_ms=round(latency_ms, 3),
        )


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
