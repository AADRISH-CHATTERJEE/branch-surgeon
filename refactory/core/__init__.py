"""Application core: config, DI, logging, and shared exceptions.

Import submodules directly (e.g. ``refactory.core.container``) to avoid
eager circular imports with optional clients.
"""

from refactory.core.config import Settings, get_settings
from refactory.core.exceptions import RefactoryError
from refactory.core.settings_groups import (
    AISettings,
    BackendSettings,
    CacheSettings,
    EmbeddingSettings,
    GitHubSettings,
    LoggingSettings,
    PromptSettings,
)

__all__ = [
    "AISettings",
    "BackendSettings",
    "CacheSettings",
    "EmbeddingSettings",
    "GitHubSettings",
    "LoggingSettings",
    "PromptSettings",
    "Settings",
    "get_settings",
    "RefactoryError",
]
