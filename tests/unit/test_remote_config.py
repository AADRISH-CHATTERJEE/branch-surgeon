"""Remote control-plane config overlay for CLI startup (soft dependency)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from refactory.backend.auth import TokenStore
from refactory.backend.client import BackendClient
from refactory.backend.models import CLIConfig, TokenPair
from refactory.backend.remote_config import (
    apply_cli_config,
    fetch_cli_config,
    resolve_startup_settings,
)
from refactory.cli.commands._common import (
    get_startup_settings,
    reset_startup_settings_for_tests,
)
from refactory.cli.startup import bootstrap_cli_settings
from refactory.core.config import Settings


def _tokens() -> dict:
    from datetime import datetime, timedelta, timezone

    return {
        "access_token": "access",
        "refresh_token": "refresh",
        "token_type": "bearer",
        "expires_in": 3600,
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }


@pytest.fixture(autouse=True)
def _reset_startup():
    reset_startup_settings_for_tests()
    yield
    reset_startup_settings_for_tests()


def test_apply_cli_config_overlays_ai_and_prompt_limits():
    local = Settings().model_copy(update={"ai_provider": "gemini", "ai_model": None})
    remote = CLIConfig(
        prompt_version="9.9.9",
        workflow_version="8.8.8",
        ai_provider="openai",
        model="gpt-test",
        feature_flags={"telemetry_enabled": False},
        limits={"max_tokens": 1234, "max_retries": 7, "timeout_seconds": 12.5},
    )
    updated = apply_cli_config(local, remote)
    # Local AI_PROVIDER wins — remote must not force openai/gpt-*.
    assert updated.ai.provider == "gemini"
    assert updated.ai.model is None
    assert updated.ai.max_retries == 7
    assert updated.ai.timeout_seconds == 12.5
    assert updated.prompt.template_version == "9.9.9"
    assert updated.prompt.max_tokens == 1234


def test_apply_cli_config_fills_blank_model_when_provider_matches():
    local = Settings().model_copy(update={"ai_provider": "openai", "ai_model": None})
    remote = CLIConfig(
        prompt_version="2.0.0",
        workflow_version="2.0.0",
        ai_provider="openai",
        model="gpt-4o-mini",
        feature_flags={},
        limits={},
    )
    updated = apply_cli_config(local, remote)
    assert updated.ai.provider == "openai"
    assert updated.ai.model == "gpt-4o-mini"


def test_fetch_cli_config_returns_none_when_logged_out(tmp_path: Path):
    client = BackendClient(
        base_url="http://backend.test",
        token_store=TokenStore(tmp_path / "auth.json"),
        transport=httpx.MockTransport(lambda r: httpx.Response(500)),
    )
    assert fetch_cli_config(client) is None


def test_fetch_cli_config_success(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/config"
        return httpx.Response(
            200,
            json={
                "prompt_version": "2.0.0",
                "workflow_version": "2.0.0",
                "ai_provider": "mock",
                "model": "mock-review-1",
                "feature_flags": {"hybrid_retrieval": True},
                "limits": {"max_tokens": 6000},
            },
        )

    store = TokenStore(tmp_path / "auth.json")
    store.save_tokens(
        TokenPair.model_validate(_tokens()),
        backend_url="http://backend.test",
    )
    client = BackendClient(
        base_url="http://backend.test",
        token_store=store,
        transport=httpx.MockTransport(handler),
    )
    cfg = fetch_cli_config(client)
    assert cfg is not None
    assert cfg.prompt_version == "2.0.0"


def test_resolve_startup_settings_falls_back_on_error():
    local = Settings()
    client = MagicMock()
    client.token_store.exists.return_value = True
    client.get_config.side_effect = RuntimeError("down")
    resolved, remote = resolve_startup_settings(local, client=client)
    assert remote is None
    assert resolved.ai.provider == local.ai.provider


def test_bootstrap_cli_settings_without_backend_url():
    local = Settings().model_copy(update={"backend_url": None})
    result = bootstrap_cli_settings(local)
    assert result.backend.url is None
    assert get_startup_settings().backend.url is None
