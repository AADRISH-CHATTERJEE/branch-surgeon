"""AI provider implementations and factory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from refactory.ai.interfaces import AIProvider
from refactory.ai.providers.gemini import DEFAULT_GEMINI_MODEL, GeminiProvider
from refactory.ai.providers.mock import MockProvider
from refactory.ai.providers.openai import DEFAULT_OPENAI_MODEL, OpenAIProvider
from refactory.core.exceptions import ConfigurationError

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.core.settings_groups import AISettings


def build_ai_provider(
    settings: "AISettings",
    logger: "Logger",
    *,
    provider_name: str | None = None,
) -> AIProvider:
    """Construct an AIProvider (mock | gemini | openai).

    ``provider_name`` overrides ``settings.provider`` (used for fallbacks).
    """
    name = (provider_name or settings.provider or "mock").strip().lower()
    timeout = settings.timeout_seconds
    model = settings.model

    if name == "mock":
        return MockProvider(model=model or "mock-review-1", logger=logger)
    if name == "gemini":
        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=model or DEFAULT_GEMINI_MODEL,
            logger=logger,
            timeout_seconds=timeout,
        )
    if name == "openai":
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=model or DEFAULT_OPENAI_MODEL,
            logger=logger,
            timeout_seconds=timeout,
        )
    raise ConfigurationError(
        f"Unknown AI_PROVIDER={name!r}. Expected one of: mock, gemini, openai"
    )


def build_ai_provider_pair(
    settings: "AISettings", logger: "Logger"
) -> tuple[AIProvider, AIProvider | None]:
    """Build primary provider and optional fallback provider."""
    primary = build_ai_provider(settings, logger)
    fallback_name = settings.fallback_provider
    if not fallback_name:
        return primary, None
    if fallback_name == primary.name:
        return primary, None
    fallback = build_ai_provider(settings, logger, provider_name=fallback_name)
    return primary, fallback


__all__ = [
    "DEFAULT_GEMINI_MODEL",
    "DEFAULT_OPENAI_MODEL",
    "GeminiProvider",
    "MockProvider",
    "OpenAIProvider",
    "build_ai_provider",
    "build_ai_provider_pair",
]
