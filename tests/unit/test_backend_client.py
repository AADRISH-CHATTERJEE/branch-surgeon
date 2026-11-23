"""Unit tests for BackendClient, TokenStore, and CLI auth commands."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from typer.testing import CliRunner

from refactory.backend.auth import TokenStore
from refactory.backend.client import BackendClient
from refactory.backend.exceptions import (
    BackendAuthError,
    BackendNotConfiguredError,
    BackendUnavailableError,
)
from refactory.backend.models import StoredAuth, TelemetryPayload, TokenPair
from refactory.cli.app import app
from refactory.core.config import Settings
from refactory.core.container import build_container

runner = CliRunner()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tokens(*, access: str = "access-1", refresh: str = "refresh-1", expires_in: int = 3600) -> dict:
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": expires_in,
    }


def _user_payload() -> dict:
    return {
        "id": 1,
        "email": "cli@refactory.dev",
        "full_name": "CLI Developer",
        "is_active": True,
        "is_superuser": True,
        "created_at": _now().isoformat(),
    }


def _client(tmp_path: Path, handler) -> BackendClient:
    transport = httpx.MockTransport(handler)
    return BackendClient(
        base_url="http://backend.test",
        token_store=TokenStore(tmp_path / "auth.json"),
        transport=transport,
        timeout=5.0,
    )


def test_login_success_persists_tokens(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/auth/login"
        body = json.loads(request.content.decode())
        assert body["email"] == "cli@refactory.dev"
        assert "password" in body
        return httpx.Response(200, json=_tokens())

    client = _client(tmp_path, handler)
    tokens = client.login("cli@refactory.dev", "secret")
    assert tokens.access_token == "access-1"

    stored = client.token_store.load()
    assert stored is not None
    assert stored.access_token == "access-1"
    assert stored.refresh_token == "refresh-1"
    assert stored.backend_url == "http://backend.test"
    raw = json.loads((tmp_path / "auth.json").read_text(encoding="utf-8"))
    assert "password" not in raw


def test_login_invalid_credentials(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Incorrect email or password"})

    client = _client(tmp_path, handler)
    with pytest.raises(BackendAuthError):
        client.login("cli@refactory.dev", "wrong")
    assert client.token_store.load() is None


def test_missing_auth_file_raises_on_me(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not call network without tokens")

    client = _client(tmp_path, handler)
    with pytest.raises(BackendAuthError, match="Not logged in"):
        client.get_current_user()


def test_refresh_flow_on_expired_access_token(tmp_path: Path):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/auth/refresh":
            body = json.loads(request.content.decode())
            assert body["refresh_token"] == "refresh-old"
            return httpx.Response(200, json=_tokens(access="access-new", refresh="refresh-new"))
        if request.url.path == "/auth/me":
            auth = request.headers.get("Authorization", "")
            assert auth == "Bearer access-new"
            return httpx.Response(200, json=_user_payload())
        return httpx.Response(404)

    store = TokenStore(tmp_path / "auth.json")
    store.save(
        StoredAuth(
            access_token="access-old",
            refresh_token="refresh-old",
            expires_at=_now() - timedelta(seconds=5),
            backend_url="http://backend.test",
        )
    )
    client = BackendClient(
        base_url="http://backend.test",
        token_store=store,
        transport=httpx.MockTransport(handler),
    )
    user = client.get_current_user()
    assert user.email == "cli@refactory.dev"
    assert "POST /auth/refresh" in calls
    assert "GET /auth/me" in calls
    assert store.load() is not None
    assert store.load().access_token == "access-new"


def test_refresh_retry_after_401(tmp_path: Path):
    state = {"me_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/refresh":
            return httpx.Response(200, json=_tokens(access="access-2", refresh="refresh-2"))
        if request.url.path == "/auth/me":
            state["me_calls"] += 1
            auth = request.headers.get("Authorization", "")
            if auth.endswith("access-stale"):
                return httpx.Response(401, json={"detail": "expired"})
            assert auth.endswith("access-2")
            return httpx.Response(200, json=_user_payload())
        return httpx.Response(404)

    store = TokenStore(tmp_path / "auth.json")
    store.save(
        StoredAuth(
            access_token="access-stale",
            refresh_token="refresh-1",
            expires_at=_now() + timedelta(hours=1),
            backend_url="http://backend.test",
        )
    )
    client = BackendClient(
        base_url="http://backend.test",
        token_store=store,
        transport=httpx.MockTransport(handler),
    )
    user = client.get_current_user()
    assert user.id == 1
    assert state["me_calls"] == 2


def test_logout_removes_auth_file(tmp_path: Path):
    store = TokenStore(tmp_path / "auth.json")
    store.save_tokens(TokenPair.model_validate(_tokens()), backend_url="http://backend.test")
    assert store.exists()

    client = BackendClient(
        base_url="http://backend.test",
        token_store=store,
        transport=httpx.MockTransport(lambda r: httpx.Response(500)),
    )
    assert client.logout() is True
    assert store.exists() is False
    assert client.logout() is False


def test_backend_unavailable(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _client(tmp_path, handler)
    with pytest.raises(BackendUnavailableError):
        client.login("cli@refactory.dev", "secret")


def test_token_persistence_roundtrip(tmp_path: Path):
    store = TokenStore(tmp_path / "auth.json")
    saved = store.save_tokens(
        TokenPair.model_validate(_tokens(expires_in=120)),
        backend_url="http://127.0.0.1:8000",
    )
    loaded = TokenStore(tmp_path / "auth.json").load()
    assert loaded is not None
    assert loaded.access_token == saved.access_token
    assert loaded.backend_url == "http://127.0.0.1:8000"
    assert store.is_access_expired(loaded) is False


def test_get_prompt_and_workflow(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/prompts/review":
            return httpx.Response(
                200,
                json={
                    "name": "review",
                    "version": "1.0.0",
                    "description": "d",
                    "template": "t",
                    "variables": [],
                    "metadata": {},
                },
            )
        if request.url.path == "/workflows/review":
            return httpx.Response(
                200,
                json={
                    "name": "review",
                    "version": "1.0.0",
                    "description": "d",
                    "steps": [],
                    "feature_flags": {"telemetry_enabled": True},
                    "metadata": {},
                },
            )
        return httpx.Response(404)

    store = TokenStore(tmp_path / "auth.json")
    store.save_tokens(TokenPair.model_validate(_tokens()), backend_url="http://backend.test")
    client = BackendClient(
        base_url="http://backend.test",
        token_store=store,
        transport=httpx.MockTransport(handler),
    )
    assert client.get_review_prompt().name == "review"
    assert client.get_review_prompt(version="1.0.0").version == "1.0.0"
    assert client.get_review_workflow().feature_flags["telemetry_enabled"] is True


def test_get_config_and_org_repo(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/config":
            return httpx.Response(
                200,
                json={
                    "prompt_version": "2.0.0",
                    "workflow_version": "2.0.0",
                    "ai_provider": "mock",
                    "model": "mock-review-1",
                    "feature_flags": {"telemetry_enabled": True, "hybrid_retrieval": True},
                    "limits": {"max_tokens": 6000, "max_findings": 50, "max_retries": 3},
                },
            )
        if request.url.path == "/prompts":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "name": "review",
                            "version": "2.0.0",
                            "description": "d",
                            "is_default": True,
                        }
                    ],
                    "default_name": "review",
                    "default_version": "2.0.0",
                },
            )
        if request.url.path == "/workflows":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "name": "review",
                            "version": "2.0.0",
                            "description": "d",
                            "is_default": True,
                            "step_count": 7,
                        }
                    ],
                    "default_name": "review",
                    "default_version": "2.0.0",
                },
            )
        if request.url.path == "/organizations/org_default":
            return httpx.Response(
                200,
                json={
                    "id": "org_default",
                    "name": "Default Organization",
                    "slug": "default",
                    "settings": {
                        "coding_standards": {"style_guide": "pep8"},
                        "review_policy": {},
                        "feature_flags": {},
                        "ai_preferences": {"primary_provider": "mock"},
                    },
                    "metadata": {},
                },
            )
        if request.url.path == "/repositories/repo_default":
            return httpx.Response(
                200,
                json={
                    "id": "repo_default",
                    "organization_id": "org_default",
                    "name": "default-repository",
                    "slug": "default",
                    "settings": {"default_branch": "main"},
                    "metadata": {},
                },
            )
        return httpx.Response(404)

    store = TokenStore(tmp_path / "auth.json")
    store.save_tokens(TokenPair.model_validate(_tokens()), backend_url="http://backend.test")
    client = BackendClient(
        base_url="http://backend.test",
        token_store=store,
        transport=httpx.MockTransport(handler),
    )
    cfg = client.get_config()
    assert cfg.prompt_version == "2.0.0"
    assert cfg.workflow_version == "2.0.0"
    assert cfg.ai_provider == "mock"
    assert cfg.model == "mock-review-1"
    assert cfg.feature_flags["telemetry_enabled"] is True
    assert cfg.limits["max_tokens"] == 6000
    assert client.list_prompts().default_version == "2.0.0"
    assert client.list_workflows().items[0].step_count == 7
    assert client.get_organization("org_default").slug == "default"
    assert client.get_repository("repo_default").organization_id == "org_default"


def test_send_telemetry(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/telemetry"
        return httpx.Response(
            201,
            json={
                "id": 9,
                "event_type": "cli.command",
                "accepted": True,
                "received_at": _now().isoformat(),
            },
        )

    store = TokenStore(tmp_path / "auth.json")
    store.save_tokens(TokenPair.model_validate(_tokens()), backend_url="http://backend.test")
    client = BackendClient(
        base_url="http://backend.test",
        token_store=store,
        transport=httpx.MockTransport(handler),
    )
    ack = client.send_telemetry(TelemetryPayload(event_type="cli.command", payload={"cmd": "search"}))
    assert ack.id == 9


def test_empty_base_url_raises():
    with pytest.raises(BackendNotConfiguredError):
        BackendClient(base_url="")


def test_container_lazy_backend_client():
    settings = Settings().model_copy(update={"backend_url": "http://127.0.0.1:8000"})
    container = build_container(settings=settings)
    assert container._backend_client is None
    first = container.get_backend_client()
    second = container.get_backend_client()
    assert first is not None
    assert first is second
    assert first.base_url == "http://127.0.0.1:8000"


def test_container_backend_disabled():
    settings = Settings().model_copy(update={"backend_url": None})
    container = build_container(settings=settings)
    assert container.get_backend_client() is None


def test_login_cli_command(mocker, tmp_path: Path):
    client = MagicMock()
    client.token_store.path = tmp_path / "auth.json"
    client.get_current_user.return_value = MagicMock(email="cli@refactory.dev")
    container = MagicMock()
    container.require_backend_client.return_value = client
    mocker.patch("refactory.cli.commands.login.get_container", return_value=container)

    result = runner.invoke(
        app,
        ["login", "--email", "cli@refactory.dev", "--password", "secret"],
    )
    assert result.exit_code == 0, result.stdout
    client.login.assert_called_once_with("cli@refactory.dev", "secret")
    assert "cli@refactory.dev" in result.stdout


def test_whoami_cli_command(mocker):
    client = MagicMock()
    client.base_url = "http://127.0.0.1:8000"
    client.get_current_user.return_value = MagicMock(
        email="cli@refactory.dev",
        full_name="CLI Developer",
        id=1,
        is_active=True,
        is_superuser=False,
    )
    container = MagicMock()
    container.require_backend_client.return_value = client
    mocker.patch("refactory.cli.commands.whoami.get_container", return_value=container)

    result = runner.invoke(app, ["whoami"])
    assert result.exit_code == 0, result.stdout
    assert "cli@refactory.dev" in result.stdout


def test_logout_cli_command(mocker, tmp_path: Path):
    store = TokenStore(tmp_path / "auth.json")
    store.save_tokens(TokenPair.model_validate(_tokens()), backend_url="http://backend.test")
    client = MagicMock()
    client.token_store = store
    container = MagicMock()
    container.get_backend_client.return_value = client
    mocker.patch("refactory.cli.commands.logout.get_container", return_value=container)

    result = runner.invoke(app, ["logout"])
    assert result.exit_code == 0, result.stdout
    assert store.exists() is False
    assert "Logged out" in result.stdout


def test_review_does_not_require_login(mocker):
    from refactory.review.models import ReviewResult

    engine = MagicMock()
    engine.review.return_value = ReviewResult(
        pull_request_number=1,
        summary="ok",
        risk_level="low",
        confidence=0.5,
    )
    container = MagicMock()
    container.review_engine = engine
    container.get_backend_client.return_value = None
    mocker.patch("refactory.cli.commands.review.get_container", return_value=container)

    result = runner.invoke(app, ["review", "1"])
    assert result.exit_code == 0, result.output
    engine.review.assert_called_once_with(1)
    container.get_backend_client.assert_called()
