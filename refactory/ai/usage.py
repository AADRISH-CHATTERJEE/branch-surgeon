"""Usage statistics and rough USD cost estimation for AI calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

from pydantic import BaseModel, Field


# Approximate USD per 1M tokens (input, output). Kept intentionally coarse.
_MODEL_PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    # Gemini
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
    # Mock
    "mock-review-1": (0.0, 0.0),
}


class CostEstimate(BaseModel):
    """Estimated cost for a single completion."""

    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    pricing_known: bool = False


class UsageSnapshot(BaseModel):
    """Immutable view of accumulated gateway usage."""

    requests: int = 0
    successes: int = 0
    failures: int = 0
    retries: int = 0
    fallbacks: int = 0
    rate_limits: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_latency_ms: float = 0.0
    estimated_cost_usd: float = 0.0
    by_provider: dict[str, int] = Field(default_factory=dict)

    @property
    def average_latency_ms(self) -> float:
        if self.successes <= 0:
            return 0.0
        return round(self.total_latency_ms / self.successes, 3)


def estimate_cost(
    *,
    provider: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> CostEstimate:
    """Estimate USD cost from token counts and a small static price table."""
    prompt = max(0, int(prompt_tokens or 0))
    completion = max(0, int(completion_tokens or 0))
    key = (model or "").strip().lower()
    pricing = _MODEL_PRICING_PER_MTOK.get(key)
    if pricing is None:
        # Prefix match (e.g. gpt-4o-mini-2024-...)
        for known, prices in _MODEL_PRICING_PER_MTOK.items():
            if key.startswith(known):
                pricing = prices
                break
    if pricing is None:
        return CostEstimate(
            provider=provider,
            model=model,
            prompt_tokens=prompt,
            completion_tokens=completion,
            estimated_cost_usd=0.0,
            pricing_known=False,
        )
    in_price, out_price = pricing
    cost = (prompt / 1_000_000.0) * in_price + (completion / 1_000_000.0) * out_price
    return CostEstimate(
        provider=provider,
        model=model,
        prompt_tokens=prompt,
        completion_tokens=completion,
        estimated_cost_usd=round(cost, 8),
        pricing_known=True,
    )


@dataclass
class UsageTracker:
    """Thread-safe accumulator used by AIGateway."""

    _lock: Lock = field(default_factory=Lock)
    requests: int = 0
    successes: int = 0
    failures: int = 0
    retries: int = 0
    fallbacks: int = 0
    rate_limits: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_latency_ms: float = 0.0
    estimated_cost_usd: float = 0.0
    by_provider: dict[str, int] = field(default_factory=dict)

    def record_request(self) -> None:
        with self._lock:
            self.requests += 1

    def record_retry(self) -> None:
        with self._lock:
            self.retries += 1

    def record_fallback(self) -> None:
        with self._lock:
            self.fallbacks += 1

    def record_rate_limit(self) -> None:
        with self._lock:
            self.rate_limits += 1

    def record_failure(self) -> None:
        with self._lock:
            self.failures += 1

    def record_success(
        self,
        *,
        provider: str,
        latency_ms: float,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        cost_usd: float,
    ) -> None:
        with self._lock:
            self.successes += 1
            self.total_latency_ms += max(0.0, latency_ms)
            self.prompt_tokens += max(0, int(prompt_tokens or 0))
            self.completion_tokens += max(0, int(completion_tokens or 0))
            self.estimated_cost_usd = round(self.estimated_cost_usd + max(0.0, cost_usd), 8)
            self.by_provider[provider] = self.by_provider.get(provider, 0) + 1

    def snapshot(self) -> UsageSnapshot:
        with self._lock:
            return UsageSnapshot(
                requests=self.requests,
                successes=self.successes,
                failures=self.failures,
                retries=self.retries,
                fallbacks=self.fallbacks,
                rate_limits=self.rate_limits,
                prompt_tokens=self.prompt_tokens,
                completion_tokens=self.completion_tokens,
                total_latency_ms=round(self.total_latency_ms, 3),
                estimated_cost_usd=round(self.estimated_cost_usd, 8),
                by_provider=dict(self.by_provider),
            )
