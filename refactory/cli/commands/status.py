"""`refactory status` — presentation adapter."""

from __future__ import annotations

from refactory.cli.commands._common import (
    get_container,
    get_remote_cli_config,
    handle_error,
)
from refactory.cli.ui.console import console
from refactory.cli.ui.tables import key_value_table


def status() -> None:
    """Show foundation status (settings + wired services)."""
    try:
        container = get_container()
        settings = container.settings
        client = container.get_backend_client()
        auth_state = "disabled"
        if client is not None:
            auth_state = "logged_in" if client.token_store.exists() else "logged_out"
        remote = get_remote_cli_config()
        rows = {
            "embedding_model": settings.embedding.model,
            "chroma_path": settings.embedding.chroma_path,
            "log_level": settings.logging.level,
            "ai_provider": settings.ai.provider,
            "ai_model": container.ai_gateway.model,
            "cache_enabled": settings.cache.enabled,
            "cache_ai_responses": settings.cache.ai_responses,
            "backend_url": settings.backend.url or "(disabled)",
            "backend_auth": auth_state,
            "remote_config": "applied" if remote is not None else "local",
            "github_token": "set" if settings.github.token else "missing",
            "gemini_api_key": "set" if settings.ai.gemini_api_key else "missing",
            "openai_api_key": "set" if settings.ai.openai_api_key else "missing",
            "ignore_dirs": ", ".join(settings.ignore_dirs),
            "review_engine": type(container.review_engine).__name__,
            "services_wired": "yes",
        }
        console.print(key_value_table("Refactory Status", rows))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
