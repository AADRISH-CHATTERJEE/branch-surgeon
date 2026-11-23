"""Live smoke test for GeminiProvider against Google AI Studio.

Requires ``GEMINI_API_KEY`` in the project ``.env`` (or process environment).
Skipped automatically when the key is missing.
"""

from __future__ import annotations

import pytest

from refactory.ai.models import AIRequest
from refactory.ai.providers.gemini import DEFAULT_GEMINI_MODEL, GeminiProvider
from refactory.core.config import get_settings
from refactory.core.exceptions import AIProviderError
from refactory.core.logger import get_service_logger
from refactory.prompt.models import PromptMetadata


@pytest.fixture
def gemini_api_key() -> str:
    get_settings.cache_clear()
    key = (get_settings().ai.gemini_api_key or "").strip()
    if not key:
        pytest.skip("GEMINI_API_KEY not configured")
    return key


def test_gemini_generate_smoke(gemini_api_key: str) -> None:
    """Call generate() against the current AI Studio REST API."""
    provider = GeminiProvider(
        api_key=gemini_api_key,
        model=DEFAULT_GEMINI_MODEL,
        logger=get_service_logger("test.gemini.smoke"),
        timeout_seconds=60.0,
    )
    request = AIRequest(
        system_prompt="You are a concise assistant. Reply with exactly: OK",
        user_prompt="Respond now.",
        metadata=PromptMetadata(template_source="local_default"),
    )
    response = provider.generate(request)
    assert response.provider == "gemini"
    assert response.model == DEFAULT_GEMINI_MODEL
    assert response.text.strip()
    assert response.latency_ms >= 0


def test_gemini_25_flash_still_accepted_when_available(gemini_api_key: str) -> None:
    """``gemini-2.5-flash`` remains a supported model id when the account allows it."""
    provider = GeminiProvider(
        api_key=gemini_api_key,
        model="gemini-2.5-flash",
        logger=get_service_logger("test.gemini.smoke.25"),
        timeout_seconds=60.0,
    )
    request = AIRequest(
        system_prompt="Reply with exactly: OK",
        user_prompt="ping",
        metadata=PromptMetadata(template_source="local_default"),
    )
    try:
        response = provider.generate(request)
    except AIProviderError as exc:
        # New AI Studio keys often get 404 for retired 2.5 flash aliases.
        if "404" in exc.message or "no longer available" in exc.message.lower():
            pytest.skip(f"gemini-2.5-flash unavailable for this API key: {exc.message[:160]}")
        raise
    assert response.provider == "gemini"
    assert response.model == "gemini-2.5-flash"
    assert response.text.strip()
