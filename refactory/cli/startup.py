"""CLI startup hooks — optional remote configuration, local fallback."""

from __future__ import annotations

from refactory.backend.auth import TokenStore
from refactory.backend.client import BackendClient
from refactory.backend.remote_config import resolve_startup_settings
from refactory.cli.commands._common import set_startup_settings
from refactory.core.config import Settings, get_settings
from refactory.core.logger import get_service_logger


def bootstrap_cli_settings(settings: Settings | None = None) -> Settings:
    """Resolve settings for this CLI invocation.

    When authenticated against the control plane, downloads ``GET /config`` and
    overlays preferences. On any failure (no backend, not logged in, network),
    falls back entirely to local configuration. Never raises for remote issues.
    """
    local = settings or get_settings()
    url = local.backend.url
    if not url:
        set_startup_settings(local, remote_config=None)
        return local

    logger = get_service_logger("cli.startup", local.logging.level)
    try:
        client = BackendClient(
            base_url=url,
            token_store=TokenStore(),
            logger=logger,
        )
    except Exception:  # noqa: BLE001
        set_startup_settings(local, remote_config=None)
        return local

    resolved, remote = resolve_startup_settings(local, client=client, logger=logger)
    set_startup_settings(resolved, remote_config=remote)
    if remote is not None:
        logger.debug(
            "Applied remote control-plane config — prompt={}, workflow={}, provider={}",
            remote.prompt_version,
            remote.workflow_version,
            remote.ai_provider,
        )
    return resolved
