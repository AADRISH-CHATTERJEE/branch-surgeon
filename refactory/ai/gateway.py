"""AIGateway — retries, backoff, fallback, health, usage (provider-agnostic).

Knows only ``AIRequest`` / ``AIResponse`` / ``AIProvider``. Does not import
PromptBuilder, Git, Indexer, Graph, or Retrieval.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import TYPE_CHECKING

from refactory.ai.capabilities import ProviderCapabilities
from refactory.ai.health import ProviderHealth
from refactory.ai.interfaces import AIProvider
from refactory.ai.models import AIRequest, AIResponse
from refactory.ai.usage import CostEstimate, UsageSnapshot, UsageTracker, estimate_cost
from refactory.cache.keys import ai_response_cache_key
from refactory.cache.store import CacheStore, NullCache
from refactory.core.exceptions import (
    AIProviderError,
    RateLimitAIProviderError,
    TransientAIProviderError,
)
from refactory.core.logger import bind_context

if TYPE_CHECKING:
    from loguru import Logger


class AIGateway:
    """Facade over injected AIProvider(s) with production resilience policies."""

    def __init__(
        self,
        provider: AIProvider,
        logger: "Logger",
        *,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.25,
        fallback_provider: AIProvider | None = None,
        timeout_seconds: float | None = None,
        cache: CacheStore | None = None,
        cache_responses: bool = False,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self._provider = provider
        # Drop only when the same object is passed twice; distinct instances may
        # share a provider name (e.g. broken mock → healthy mock in tests).
        self._fallback = (
            None if fallback_provider is provider else fallback_provider
        )
        self._logger = logger
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._timeout_seconds = timeout_seconds
        self._usage = UsageTracker()
        self._cache: CacheStore = cache or NullCache()
        self._cache_responses = cache_responses
        self._last_cache_hit: bool | None = None

    @property
    def last_cache_hit(self) -> bool | None:
        """Whether the most recent ``generate`` served a cached AI response."""
        return self._last_cache_hit

    @property
    def provider(self) -> AIProvider:
        return self._provider

    @property
    def fallback_provider(self) -> AIProvider | None:
        return self._fallback

    @property
    def provider_name(self) -> str:
        return self._provider.name

    @property
    def model(self) -> str:
        return self._provider.model

    def usage_stats(self) -> UsageSnapshot:
        """Return accumulated usage / cost statistics."""
        return self._usage.snapshot()

    def capabilities(self) -> list[ProviderCapabilities]:
        """Capability detection for primary (and fallback when configured)."""
        caps = [self._safe_capabilities(self._provider)]
        if self._fallback is not None:
            caps.append(self._safe_capabilities(self._fallback))
        return caps

    def health_check(self) -> list[ProviderHealth]:
        """Run provider health probes for primary and fallback."""
        results = [self._safe_health(self._provider)]
        if self._fallback is not None:
            results.append(self._safe_health(self._fallback))
        return results

    def stream(self, request: AIRequest) -> Iterator[str]:
        """Future-ready streaming. Uses provider.stream when available."""
        stream_fn = getattr(self._provider, "stream", None)
        if callable(stream_fn):
            yield from stream_fn(request)
            return
        yield self.generate(request).text

    def generate(self, request: AIRequest) -> AIResponse:
        """Send ``request`` with retries, exponential backoff, and optional fallback."""
        self._usage.record_request()
        self._last_cache_hit = False
        if self._cache_responses:
            cache_key = ai_response_cache_key(
                provider=self._provider.name,
                model_version=self._provider.model,
                system_prompt=request.system_prompt,
                user_prompt=request.user_prompt,
            )
            cached = self._cache.get(cache_key)
            if isinstance(cached, dict):
                response = AIResponse.model_validate(cached)
                self._last_cache_hit = True
                bind_context(
                    self._logger,
                    provider=response.provider,
                    model=response.model,
                    cache="hit",
                ).info("AIGateway cache hit — provider={}, model={}", response.provider, response.model)
                return response

        providers = [self._provider]
        if self._fallback is not None:
            providers.append(self._fallback)

        last_error: Exception | None = None
        for provider_index, provider in enumerate(providers):
            if provider_index > 0:
                self._usage.record_fallback()
                bind_context(
                    self._logger, provider=provider.name, model=provider.model, cache="miss"
                ).warning(
                    "AIGateway fallback — switching to provider={}, model={}",
                    provider.name,
                    provider.model,
                )
            try:
                response = self._generate_with_retries(provider, request)
                self._last_cache_hit = False
                if self._cache_responses:
                    self._cache.set(
                        ai_response_cache_key(
                            provider=self._provider.name,
                            model_version=self._provider.model,
                            system_prompt=request.system_prompt,
                            user_prompt=request.user_prompt,
                        ),
                        response.model_dump(mode="json"),
                    )
                return response
            except AIProviderError as exc:
                last_error = exc
                bind_context(
                    self._logger, provider=provider.name, model=provider.model
                ).error(
                    "AIGateway provider exhausted — provider={}, model={}: {}",
                    provider.name,
                    provider.model,
                    exc.message,
                )
                continue

        self._usage.record_failure()
        assert last_error is not None
        raise AIProviderError(
            f"AI provider(s) failed after retries/fallback: {last_error.message}"
        ) from last_error

    def _generate_with_retries(self, provider: AIProvider, request: AIRequest) -> AIResponse:
        attempts = self._max_retries + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                log = bind_context(
                    self._logger,
                    provider=provider.name,
                    model=provider.model,
                    cache="miss",
                )
                log.info(
                    "AIGateway generate — provider={}, model={}, attempt={}/{}",
                    provider.name,
                    provider.model,
                    attempt,
                    attempts,
                )
                response = provider.generate(request)
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                if response.latency_ms <= 0:
                    response = response.model_copy(update={"latency_ms": round(elapsed_ms, 3)})

                cost = estimate_cost(
                    provider=response.provider,
                    model=response.model,
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                )
                response = response.model_copy(
                    update={"estimated_cost_usd": cost.estimated_cost_usd}
                )
                self._usage.record_success(
                    provider=response.provider,
                    latency_ms=response.latency_ms,
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    cost_usd=cost.estimated_cost_usd,
                )
                bind_context(
                    self._logger,
                    provider=response.provider,
                    model=response.model,
                    elapsed_ms=round(response.latency_ms, 3),
                    cache="miss",
                ).info(
                    "AIGateway success — provider={}, model={}, latency_ms={:.1f}, "
                    "cost_usd={:.6f}, prompt_tokens={}, completion_tokens={}",
                    response.provider,
                    response.model,
                    response.latency_ms,
                    cost.estimated_cost_usd,
                    response.prompt_tokens,
                    response.completion_tokens,
                )
                return response
            except RateLimitAIProviderError as exc:
                last_error = exc
                self._usage.record_rate_limit()
                bind_context(
                    self._logger, provider=provider.name, model=provider.model
                ).warning(
                    "AIGateway rate-limit — provider={}, attempt={}/{}: {}",
                    provider.name,
                    attempt,
                    attempts,
                    exc.message,
                )
                if attempt >= attempts:
                    break
                self._usage.record_retry()
                self._sleep_backoff(attempt, rate_limited=True)
            except TransientAIProviderError as exc:
                last_error = exc
                bind_context(
                    self._logger, provider=provider.name, model=provider.model
                ).warning(
                    "AIGateway transient failure — provider={}, attempt={}/{}: {}",
                    provider.name,
                    attempt,
                    attempts,
                    exc.message,
                )
                if attempt >= attempts:
                    break
                self._usage.record_retry()
                self._sleep_backoff(attempt, rate_limited=False)
            except AIProviderError as exc:
                bind_context(
                    self._logger, provider=provider.name, model=provider.model
                ).error(
                    "AIGateway permanent failure — provider={}: {}",
                    provider.name,
                    exc.message,
                )
                raise
            except Exception as exc:  # noqa: BLE001
                bind_context(
                    self._logger, provider=provider.name, model=provider.model
                ).error(
                    "AIGateway unexpected failure — provider={}: {}",
                    provider.name,
                    exc,
                )
                raise AIProviderError(f"Unexpected AI provider failure: {exc}") from exc

        assert last_error is not None
        raise AIProviderError(
            f"AI provider failed after {attempts} attempt(s): {last_error.message}"
        ) from last_error

    def _sleep_backoff(self, attempt: int, *, rate_limited: bool) -> None:
        # Exponential backoff: base * 2^(attempt-1); rate-limits get a longer base.
        base = self._retry_backoff_seconds * (2.0 if rate_limited else 1.0)
        delay = base * (2 ** (attempt - 1))
        self._logger.info(
            "AIGateway backoff — sleeping={:.3f}s (attempt={}, rate_limited={})",
            delay,
            attempt,
            rate_limited,
        )
        if delay > 0:
            time.sleep(delay)

    @staticmethod
    def _safe_capabilities(provider: AIProvider) -> ProviderCapabilities:
        fn = getattr(provider, "capabilities", None)
        if callable(fn):
            return fn()
        from refactory.ai.capabilities import capabilities_for

        return capabilities_for(provider.name, provider.model)

    @staticmethod
    def _safe_health(provider: AIProvider) -> ProviderHealth:
        fn = getattr(provider, "health_check", None)
        if callable(fn):
            return fn()
        from refactory.ai.health import HealthStatus

        return ProviderHealth(
            provider=provider.name,
            model=provider.model,
            status=HealthStatus.UNKNOWN,
            message="health_check not implemented",
        )

    def estimate_cost_for(
        self,
        *,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        provider: str | None = None,
        model: str | None = None,
    ) -> CostEstimate:
        """Public helper for cost estimation without making a request."""
        return estimate_cost(
            provider=provider or self.provider_name,
            model=model or self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
