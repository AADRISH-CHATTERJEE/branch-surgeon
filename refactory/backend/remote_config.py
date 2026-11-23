"""Optional remote control-plane config fetch for CLI startup.

Never required: any failure falls back to local ``Settings``.
Does not call AI, parse code, embed, or touch Git.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from refactory.backend.models import CLIConfig
from refactory.core.config import Settings

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.backend.client import BackendClient


def fetch_cli_config(
    client: "BackendClient",
    *,
    logger: "Logger | None" = None,
) -> CLIConfig | None:
    """GET /config when authenticated. Returns None on any failure."""
    try:
        if not client.token_store.exists():
            return None
        return client.get_config()
    except Exception as exc:  # noqa: BLE001 — soft dependency
        if logger is not None:
            logger.debug("Remote control-plane config unavailable: {}", exc)
        return None


def apply_cli_config(local: Settings, remote: CLIConfig) -> Settings:
    """Overlay remote preferences onto local settings (local wins on blanks).

    AI provider/model are owned by the CLI (``.env`` / OS env + credentials).
    Remote may only fill a blank local model; it never overwrites a configured
    local provider, and never applies a remote model when the remote provider
    differs from the local provider.
    """
    limits = remote.limits or {}
    ai_update: dict[str, object] = {}
    # Never overwrite local AI_PROVIDER — that caused gemini → openai on GET /config.
    if (
        remote.model
        and local.ai.model is None
        and (
            not remote.ai_provider
            or remote.ai_provider.strip().lower() == local.ai.provider.strip().lower()
        )
    ):
        ai_update["model"] = remote.model
    if "timeout_seconds" in limits:
        ai_update["timeout_seconds"] = float(limits["timeout_seconds"])
    if "max_retries" in limits:
        ai_update["max_retries"] = int(limits["max_retries"])

    prompt_update: dict[str, object] = {}
    if remote.prompt_version:
        prompt_update["template_version"] = remote.prompt_version
    for key, attr in (
        ("max_tokens", "max_tokens"),
        ("max_retrieved_files", "max_retrieved_files"),
        ("max_symbols", "max_symbols"),
        ("max_related_files", "max_related_files"),
        ("max_graph_depth", "max_graph_depth"),
    ):
        if key in limits:
            prompt_update[attr] = int(limits[key])

    update: dict[str, object] = {}
    if ai_update:
        update["ai"] = ai_update
    if prompt_update:
        update["prompt"] = prompt_update
    if not update:
        return local
    return local.model_copy(update=update)


def resolve_startup_settings(
    local: Settings,
    *,
    client: "BackendClient | None" = None,
    logger: "Logger | None" = None,
) -> tuple[Settings, CLIConfig | None]:
    """Fetch remote config when possible; otherwise return local unchanged."""
    if client is None:
        return local, None
    remote = fetch_cli_config(client, logger=logger)
    if remote is None:
        return local, None
    return apply_cli_config(local, remote), remote
