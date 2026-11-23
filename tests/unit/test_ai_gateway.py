"""Unit tests for AI gateway, providers, configuration, and resilience."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest
from typer.testing import CliRunner

from refactory.ai.gateway import AIGateway
from refactory.ai.health import HealthStatus
from refactory.ai.models import AIRequest, AIResponse
from refactory.ai.providers import build_ai_provider, build_ai_provider_pair
from refactory.ai.providers.gemini import GeminiProvider
from refactory.ai.providers.mock import MockProvider
from refactory.ai.providers.openai import OpenAIProvider
from refactory.ai.usage import estimate_cost
from refactory.cli.app import app
from refactory.core.config import Settings
from refactory.core.container import build_container
from refactory.core.exceptions import (
    AIProviderError,
    ConfigurationError,
    RateLimitAIProviderError,
    TransientAIProviderError,
)
from refactory.core.logger import get_service_logger
from refactory.prompt.models import PromptMetadata, PromptRequest

runner = CliRunner()


def _logger():
    return get_service_logger("test.ai")


def _request(**kwargs: object) -> AIRequest:
    meta = PromptMetadata(
        template_source="local_default",
        repository_name="demo",
        pr_number=7,
    )
    base = dict(
        system_prompt="You are a reviewer.",
        user_prompt="## Pull Request Metadata\n\n- Number: #7\n",
        metadata=meta,
    )
    base.update(kwargs)
    return AIRequest(**base)  # type: ignore[arg-type]


def test_mock_provider_deterministic():
    provider = MockProvider(logger=_logger())
    a = provider.generate(_request())
    b = provider.generate(_request())
    assert a.text == b.text
    assert a.provider == "mock"
    assert a.finish_reason == "stop"
    assert "MOCK_REVIEW" in a.text


def test_provider_selection_from_config():
    settings = Settings().model_copy(update={"ai_provider": "mock", "ai_model": "mock-x"})
    provider = build_ai_provider(settings.ai, _logger())
    assert isinstance(provider, MockProvider)
    assert provider.model == "mock-x"

    settings = Settings().model_copy(
        update={"ai_provider": "gemini", "gemini_api_key": "k", "ai_model": None}
    )
    provider = build_ai_provider(settings.ai, _logger())
    assert isinstance(provider, GeminiProvider)

    settings = Settings().model_copy(
        update={"ai_provider": "openai", "openai_api_key": "k", "ai_model": "gpt-test"}
    )
    provider = build_ai_provider(settings.ai, _logger())
    assert isinstance(provider, OpenAIProvider)
    assert provider.model == "gpt-test"


def test_unknown_provider_raises():
    settings = Settings().model_copy(update={"ai_provider": "anthropic"})
    with pytest.raises(ConfigurationError):
        build_ai_provider(settings.ai, _logger())


def test_settings_expose_timeout_retries_provider_model_fallback():
    settings = Settings(
        AI_PROVIDER="openai",
        AI_MODEL="gpt-4o-mini",
        AI_TIMEOUT=45,
        AI_MAX_RETRIES=4,
        AI_FALLBACK_PROVIDER="mock",
    )
    assert settings.ai.provider == "openai"
    assert settings.ai.model == "gpt-4o-mini"
    assert settings.ai.timeout_seconds == 45.0
    assert settings.ai.max_retries == 4
    assert settings.ai.fallback_provider == "mock"


def test_settings_ai_timeout_seconds_alias_still_works():
    settings = Settings(AI_TIMEOUT_SECONDS=12.5)
    assert settings.ai.timeout_seconds == 12.5


def test_gateway_success():
    gateway = AIGateway(provider=MockProvider(fixed_text="ok", logger=_logger()), logger=_logger())
    response = gateway.generate(_request())
    assert response.text == "ok"
    assert response.provider == "mock"
    assert response.estimated_cost_usd is not None
    stats = gateway.usage_stats()
    assert stats.successes == 1
    assert stats.requests == 1


def test_gateway_retries_transient_failures(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("refactory.ai.gateway.time.sleep", lambda s: sleeps.append(s))

    class FlakyProvider(MockProvider):
        def __init__(self) -> None:
            super().__init__(fixed_text="recovered", logger=_logger())
            self.calls = 0

        def generate(self, request: AIRequest) -> AIResponse:
            self.calls += 1
            if self.calls < 3:
                raise TransientAIProviderError("temporary outage")
            return super().generate(request)

    provider = FlakyProvider()
    gateway = AIGateway(
        provider=provider,
        logger=_logger(),
        max_retries=2,
        retry_backoff_seconds=0.1,
    )
    response = gateway.generate(_request())
    assert response.text == "recovered"
    assert provider.calls == 3
    # Exponential: 0.1 * 2^0, 0.1 * 2^1
    assert sleeps == pytest.approx([0.1, 0.2])
    assert gateway.usage_stats().retries == 2


def test_gateway_exhausted_retries(monkeypatch):
    monkeypatch.setattr("refactory.ai.gateway.time.sleep", lambda _s: None)

    class AlwaysTransient(MockProvider):
        def generate(self, request: AIRequest) -> AIResponse:
            raise TransientAIProviderError("still down")

    gateway = AIGateway(
        provider=AlwaysTransient(logger=_logger()),
        logger=_logger(),
        max_retries=1,
        retry_backoff_seconds=0.0,
    )
    with pytest.raises(AIProviderError, match="failed after"):
        gateway.generate(_request())
    assert gateway.usage_stats().failures == 1


def test_gateway_does_not_retry_permanent_errors():
    class Permanent(MockProvider):
        def __init__(self) -> None:
            super().__init__(logger=_logger())
            self.calls = 0

        def generate(self, request: AIRequest) -> AIResponse:
            self.calls += 1
            raise AIProviderError("bad request")

    provider = Permanent()
    gateway = AIGateway(provider=provider, logger=_logger(), max_retries=3, retry_backoff_seconds=0.0)
    with pytest.raises(AIProviderError, match="bad request"):
        gateway.generate(_request())
    assert provider.calls == 1


def test_gateway_rate_limit_detection(monkeypatch):
    monkeypatch.setattr("refactory.ai.gateway.time.sleep", lambda _s: None)

    class Limited(MockProvider):
        def __init__(self) -> None:
            super().__init__(fixed_text="ok", logger=_logger())
            self.calls = 0

        def generate(self, request: AIRequest) -> AIResponse:
            self.calls += 1
            if self.calls == 1:
                raise RateLimitAIProviderError("429 too many requests")
            return super().generate(request)

    gateway = AIGateway(
        provider=Limited(),
        logger=_logger(),
        max_retries=2,
        retry_backoff_seconds=0.05,
    )
    response = gateway.generate(_request())
    assert response.text == "ok"
    assert gateway.usage_stats().rate_limits == 1
    assert gateway.usage_stats().retries == 1


def test_gateway_provider_fallback(monkeypatch):
    monkeypatch.setattr("refactory.ai.gateway.time.sleep", lambda _s: None)

    class Broken(MockProvider):
        def generate(self, request: AIRequest) -> AIResponse:
            raise TransientAIProviderError("primary down")

    primary = Broken(logger=_logger())
    fallback = MockProvider(fixed_text="from-fallback", logger=_logger())
    gateway = AIGateway(
        provider=primary,
        logger=_logger(),
        max_retries=0,
        retry_backoff_seconds=0.0,
        fallback_provider=fallback,
    )
    response = gateway.generate(_request())
    assert response.text == "from-fallback"
    assert response.provider == "mock"
    assert gateway.usage_stats().fallbacks == 1


def test_build_ai_provider_pair_with_fallback():
    settings = Settings().model_copy(
        update={"ai_provider": "openai", "openai_api_key": "k", "ai_fallback_provider": "mock"}
    )
    primary, fallback = build_ai_provider_pair(settings.ai, _logger())
    assert isinstance(primary, OpenAIProvider)
    assert isinstance(fallback, MockProvider)


def test_provider_capabilities_and_health():
    mock = MockProvider(logger=_logger())
    caps = mock.capabilities()
    assert caps.provider == "mock"
    assert caps.supports_chat is True
    health = mock.health_check()
    assert health.status == HealthStatus.HEALTHY

    gateway = AIGateway(provider=mock, logger=_logger())
    assert gateway.capabilities()[0].provider == "mock"
    assert gateway.health_check()[0].status == HealthStatus.HEALTHY


def test_gateway_stream_future_ready():
    gateway = AIGateway(
        provider=MockProvider(fixed_text="chunk-a", logger=_logger()),
        logger=_logger(),
    )
    chunks = list(gateway.stream(_request()))
    assert chunks == ["chunk-a"]


def test_cost_estimation():
    cost = estimate_cost(
        provider="openai",
        model="gpt-4o-mini",
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
    )
    assert cost.pricing_known is True
    assert cost.estimated_cost_usd == pytest.approx(0.75)


def test_openai_timeout_raises_transient():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout", request=request)

    provider = OpenAIProvider(
        api_key="sk-test",
        model="gpt-4o-mini",
        logger=_logger(),
        timeout_seconds=0.01,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(TransientAIProviderError, match="timed out"):
        provider.generate(_request())


def test_openai_rate_limit_raises_rate_limit_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    provider = OpenAIProvider(
        api_key="sk-test",
        model="gpt-4o-mini",
        logger=_logger(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(RateLimitAIProviderError, match="429"):
        provider.generate(_request())


def test_openai_response_parsing():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        assert body["messages"][0]["role"] == "system"
        return httpx.Response(
            200,
            json={
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "review ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3},
            },
        )

    provider = OpenAIProvider(
        api_key="sk-test",
        model="gpt-4o-mini",
        logger=_logger(),
        transport=httpx.MockTransport(handler),
    )
    response = provider.generate(_request())
    assert response.text == "review ok"
    assert response.prompt_tokens == 11
    assert response.completion_tokens == 3
    assert response.finish_reason == "stop"


def test_gemini_response_parsing():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "generateContent" in str(request.url)
        assert "key=" not in str(request.url)
        assert request.headers.get("x-goog-api-key") == "gem-test"
        body = json.loads(request.content.decode("utf-8"))
        assert body["systemInstruction"]["parts"][0]["text"]
        assert body["contents"][0]["role"] == "user"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "thinking…", "thought": True},
                                {"text": "gemini review"},
                            ]
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2},
            },
        )

    provider = GeminiProvider(
        api_key="gem-test",
        model="gemini-2.5-flash",
        logger=_logger(),
        transport=httpx.MockTransport(handler),
    )
    response = provider.generate(_request())
    assert response.text == "gemini review"
    assert response.prompt_tokens == 5
    assert response.completion_tokens == 2
    assert provider.model == "gemini-2.5-flash"


def test_gemini_normalizes_models_prefix():
    provider = GeminiProvider(
        api_key="k",
        model="models/gemini-2.5-flash",
        logger=_logger(),
    )
    assert provider.model == "gemini-2.5-flash"


def test_gemini_missing_key():
    provider = GeminiProvider(api_key=None, model="gemini-2.5-flash", logger=_logger())
    with pytest.raises(ConfigurationError):
        provider.generate(_request())


def test_gemini_health_check_missing_key():
    provider = GeminiProvider(api_key=None, model="gemini-2.5-flash", logger=_logger())
    health = provider.health_check()
    assert health.status == HealthStatus.UNHEALTHY


def test_ai_request_from_prompt_request():
    prompt = PromptRequest(
        system_prompt="sys",
        user_prompt="user",
        metadata=PromptMetadata(template_source="local_default", pr_number=3),
    )
    req = AIRequest.from_prompt_request(prompt)
    assert req.system_prompt == "sys"
    assert req.metadata.pr_number == 3


def test_container_wires_mock_gateway_by_default():
    container = build_container(Settings().model_copy(update={"ai_provider": "mock"}))
    assert isinstance(container.ai_gateway.provider, MockProvider)
    assert container.ai_service.gateway is container.ai_gateway
    assert container.review_engine._gateway is container.ai_gateway


def test_container_wires_fallback_provider():
    container = build_container(
        Settings().model_copy(
            update={
                "ai_provider": "openai",
                "openai_api_key": "sk-test",
                "ai_fallback_provider": "mock",
            }
        )
    )
    assert isinstance(container.ai_gateway.provider, OpenAIProvider)
    assert isinstance(container.ai_gateway.fallback_provider, MockProvider)


def test_ai_test_cli(mocker):
    gateway = MagicMock()
    gateway.generate.return_value = AIResponse(
        text="hello from mock",
        provider="mock",
        model="mock-review-1",
        latency_ms=12.5,
        finish_reason="stop",
        prompt_tokens=10,
        completion_tokens=4,
    )
    builder = MagicMock()
    builder.build.return_value = PromptRequest(
        system_prompt="s",
        user_prompt="u",
        metadata=PromptMetadata(template_source="local_default"),
    )
    container = MagicMock()
    container.ai_gateway = gateway
    container.prompt_builder = builder
    mocker.patch("refactory.cli.commands.ai_test.get_container", return_value=container)

    result = runner.invoke(app, ["ai-test"])
    assert result.exit_code == 0, result.stdout
    assert "mock" in result.stdout
    assert "hello from mock" in result.stdout
    assert "12.5" in result.stdout
    gateway.generate.assert_called_once()
