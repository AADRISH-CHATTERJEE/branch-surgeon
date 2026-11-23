"""Google Gemini provider (HTTP via AI Studio Generative Language REST API)."""

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

# Default for current Google AI Studio keys. ``gemini-2.5-flash`` remains a valid
# model id when the account still has access; new Studio keys typically require
# Gemini 3.x flash (``gemini-3.5-flash`` / ``gemini-flash-latest``).
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_API_KEY_HEADER = "x-goog-api-key"


class GeminiProvider:
    def __init__(
        self,
        api_key: str | None,
        model: str | None,
        logger: "Logger",
        *,
        timeout_seconds: float = 60.0,
        api_root: str = GEMINI_API_ROOT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip() or None
        self._model = _normalize_model_id(model or DEFAULT_GEMINI_MODEL)
        self._logger = logger
        self._timeout = timeout_seconds
        self._api_root = api_root.rstrip("/")
        self._transport = transport

    @property
    def name(self) -> str:
        return "gemini"

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
                message="GEMINI_API_KEY is not configured",
            )
        # Lightweight authenticated probe against the models list endpoint.
        url = f"{self._api_root}/models"
        try:
            with httpx.Client(timeout=min(self._timeout, 10.0), transport=self._transport) as client:
                response = client.get(url, headers=self._auth_headers())
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
            raise ConfigurationError("GEMINI_API_KEY is not configured")

        started = time.perf_counter()
        payload = self._build_payload(request)
        url = f"{self._api_root}/models/{self._model}:generateContent"
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.post(
                    url,
                    headers={**self._auth_headers(), "Content-Type": "application/json"},
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise TransientAIProviderError(
                f"Gemini request timed out after {self._timeout}s"
            ) from exc
        except httpx.RequestError as exc:
            raise TransientAIProviderError(f"Gemini request failed: {exc}") from exc

        latency_ms = (time.perf_counter() - started) * 1000.0
        if response.status_code == 429:
            raise RateLimitAIProviderError(
                f"Gemini rate limited (429): {response.text[:300]}",
            )
        if response.status_code == 408 or response.status_code >= 500:
            raise TransientAIProviderError(
                f"Gemini transient error ({response.status_code}): {response.text[:300]}",
            )
        if response.status_code >= 400:
            raise AIProviderError(
                f"Gemini error ({response.status_code}): {response.text[:300]}",
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise AIProviderError("Gemini returned non-JSON response") from exc

        return self._parse_response(data, latency_ms=latency_ms)

    def _auth_headers(self) -> dict[str, str]:
        assert self._api_key is not None
        # Current AI Studio docs require the API key header (query ?key= is legacy).
        return {GEMINI_API_KEY_HEADER: self._api_key}

    def _build_payload(self, request: AIRequest) -> dict[str, Any]:
        """Build a generateContent body for the Generative Language REST API."""
        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": request.user_prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
            },
        }
        system_prompt = (request.system_prompt or "").strip()
        if system_prompt:
            # camelCase field name used by generativelanguage.googleapis.com REST.
            payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}],
            }
        return payload

    def _parse_response(self, data: dict[str, Any], *, latency_ms: float) -> AIResponse:
        prompt_feedback = data.get("promptFeedback") or {}
        block_reason = prompt_feedback.get("blockReason")
        if block_reason:
            raise AIProviderError(f"Gemini blocked the prompt ({block_reason})")

        candidates = data.get("candidates") or []
        if not candidates:
            raise AIProviderError("Gemini response contained no candidates")

        candidate = candidates[0] if isinstance(candidates[0], dict) else {}
        finish = candidate.get("finishReason")
        if finish in {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}:
            raise AIProviderError(f"Gemini blocked the response ({finish})")

        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        # Gemini 2.5/3.x may return thought parts; keep only answer text.
        texts = [
            str(part.get("text", ""))
            for part in parts
            if isinstance(part, dict)
            and part.get("text")
            and not part.get("thought")
        ]
        text = "".join(texts).strip()
        if not text:
            raise AIProviderError("Gemini response missing text parts")

        usage = data.get("usageMetadata") or {}
        completion_tokens = _optional_int(usage.get("candidatesTokenCount"))
        if completion_tokens is None:
            completion_tokens = _optional_int(usage.get("totalTokenCount"))

        self._logger.debug("GeminiProvider.generate ok (model={})", self._model)
        return AIResponse(
            text=text,
            provider=self.name,
            model=self._model,
            prompt_tokens=_optional_int(usage.get("promptTokenCount")),
            completion_tokens=completion_tokens,
            finish_reason=str(finish) if finish is not None else None,
            latency_ms=round(latency_ms, 3),
        )

    # Legacy stub used by older call sites (kept for compatibility).
    def generate_json(self, prompt: str) -> dict[str, Any]:
        self._logger.debug("GeminiProvider.generate_json called (model={})", self._model)
        raise NotImplementedError(
            "Use AIGateway / GeminiProvider.generate(AIRequest) instead of generate_json"
        )


def _normalize_model_id(model: str) -> str:
    """Accept ``gemini-…`` or ``models/gemini-…`` ids from AI Studio."""
    text = (model or "").strip()
    if text.startswith("models/"):
        text = text[len("models/") :]
    return text or DEFAULT_GEMINI_MODEL


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
