"""Nested settings groups preserve flat environment variable names."""

from __future__ import annotations

import pytest

from refactory.core.config import Settings, get_settings
from refactory.core.settings_groups import AISettings, EmbeddingSettings


def test_nested_access_paths():
    settings = Settings(
        AI_PROVIDER="mock",
        AI_MODEL="m1",
        CACHE_ENABLED=True,
        PROMPT_MAX_TOKENS=4096,
        REFACTORY_BACKEND_URL="http://example.test",
        EMBEDDING_MODEL="BAAI/bge-small-en-v1.5",
        LOG_LEVEL="DEBUG",
    )
    assert settings.ai.provider == "mock"
    assert settings.ai.model == "m1"
    assert settings.cache.enabled is True
    assert settings.prompt.max_tokens == 4096
    assert settings.backend.url == "http://example.test"
    assert settings.embedding.model == "BAAI/bge-small-en-v1.5"
    assert settings.logging.level == "DEBUG"


def test_model_copy_accepts_legacy_flat_keys():
    settings = Settings().model_copy(
        update={"ai_provider": "openai", "openai_api_key": "sk", "backend_url": None}
    )
    assert settings.ai.provider == "openai"
    assert settings.ai.openai_api_key == "sk"
    assert settings.backend.url is None


def test_env_var_names_unchanged(monkeypatch: pytest.MonkeyPatch):
    get_settings.cache_clear()
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_MODEL", "gpt-test")
    monkeypatch.setenv("CACHE_ENABLED", "false")
    monkeypatch.setenv("REFACTORY_BACKEND_URL", "http://env-backend")
    try:
        settings = Settings()
        assert settings.ai.provider == "openai"
        assert settings.ai.model == "gpt-test"
        assert settings.cache.enabled is False
        assert settings.backend.url == "http://env-backend"
    finally:
        get_settings.cache_clear()


def test_embedding_settings_section_standalone():
    cfg = EmbeddingSettings(model="custom-model", retrieval_top_k=5)
    assert cfg.model == "custom-model"
    assert cfg.retrieval_top_k == 5


def test_ai_settings_normalizes_provider():
    assert AISettings(provider=" OpenAI ").provider == "openai"
    assert AISettings(fallback_provider="none").fallback_provider is None
