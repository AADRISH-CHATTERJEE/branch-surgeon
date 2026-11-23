"""Strongly typed application settings (pydantic-settings).

Settings are organized into logical groups (``settings.ai.provider``, etc.)
while environment variables remain the historical flat names
(``AI_PROVIDER``, ``CACHE_ENABLED``, ``REFACTORY_BACKEND_URL``, …).
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from refactory.core.settings_groups import (
    AISettings,
    BackendSettings,
    CacheSettings,
    EmbeddingSettings,
    GitHubSettings,
    LoggingSettings,
    PromptSettings,
)

_LOG = logging.getLogger("refactory.core.config")
_PROJECT_ROOT_MARKERS = ("pyproject.toml", ".git", ".env")
_dotenv_debug_logged = False

DEFAULT_IGNORE_DIRS: tuple[str, ...] = (
    ".git",
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".cache",
    "venv",
    ".venv",
    "__pycache__",
    ".refactory",
    ".pytest_cache",
    ".mypy_cache",
    ".next",
    ".turbo",
    ".tox",
    ".eggs",
    "egg-info",
    "vendor",
    "generated",
)

# Flat env / init key → (group, field)
_FLAT_KEY_MAP: dict[str, tuple[str, str]] = {
    # AI
    "AI_PROVIDER": ("ai", "provider"),
    "ai_provider": ("ai", "provider"),
    "AI_MODEL": ("ai", "model"),
    "ai_model": ("ai", "model"),
    "AI_TIMEOUT": ("ai", "timeout_seconds"),
    "AI_TIMEOUT_SECONDS": ("ai", "timeout_seconds"),
    "ai_timeout_seconds": ("ai", "timeout_seconds"),
    "AI_MAX_RETRIES": ("ai", "max_retries"),
    "ai_max_retries": ("ai", "max_retries"),
    "AI_FALLBACK_PROVIDER": ("ai", "fallback_provider"),
    "ai_fallback_provider": ("ai", "fallback_provider"),
    "GEMINI_API_KEY": ("ai", "gemini_api_key"),
    "gemini_api_key": ("ai", "gemini_api_key"),
    "OPENAI_API_KEY": ("ai", "openai_api_key"),
    "openai_api_key": ("ai", "openai_api_key"),
    # Backend
    "REFACTORY_BACKEND_URL": ("backend", "url"),
    "BACKEND_URL": ("backend", "url"),
    "backend_url": ("backend", "url"),
    # Cache
    "CACHE_ENABLED": ("cache", "enabled"),
    "cache_enabled": ("cache", "enabled"),
    "CACHE_AI_RESPONSES": ("cache", "ai_responses"),
    "cache_ai_responses": ("cache", "ai_responses"),
    "CACHE_PATH": ("cache", "path"),
    "cache_path": ("cache", "path"),
    # Prompt
    "PROMPT_TEMPLATE_VERSION": ("prompt", "template_version"),
    "prompt_template_version": ("prompt", "template_version"),
    "PROMPT_MAX_TOKENS": ("prompt", "max_tokens"),
    "prompt_max_tokens": ("prompt", "max_tokens"),
    "PROMPT_MAX_RETRIEVED_FILES": ("prompt", "max_retrieved_files"),
    "prompt_max_retrieved_files": ("prompt", "max_retrieved_files"),
    "PROMPT_MAX_SYMBOLS": ("prompt", "max_symbols"),
    "prompt_max_symbols": ("prompt", "max_symbols"),
    "PROMPT_MAX_RELATED_FILES": ("prompt", "max_related_files"),
    "prompt_max_related_files": ("prompt", "max_related_files"),
    "PROMPT_MAX_GRAPH_DEPTH": ("prompt", "max_graph_depth"),
    "prompt_max_graph_depth": ("prompt", "max_graph_depth"),
    # GitHub
    "GITHUB_TOKEN": ("github", "token"),
    "github_token": ("github", "token"),
    # Embedding
    "EMBEDDING_MODEL": ("embedding", "model"),
    "embedding_model": ("embedding", "model"),
    "CHROMA_PATH": ("embedding", "chroma_path"),
    "chroma_path": ("embedding", "chroma_path"),
    "RETRIEVAL_TOP_K": ("embedding", "retrieval_top_k"),
    "retrieval_top_k": ("embedding", "retrieval_top_k"),
    # Logging
    "LOG_LEVEL": ("logging", "level"),
    "log_level": ("logging", "level"),
}

_GROUP_NAMES = frozenset(
    {"ai", "backend", "cache", "prompt", "github", "embedding", "logging"}
)


def find_project_root(start: Path | None = None) -> Path:
    """Locate the repository root by walking upward from ``start``.

    Starts from this module's path when ``start`` is omitted — never from
    ``os.getcwd()``. A directory is treated as the root when it contains any of
    ``pyproject.toml``, ``.git``, or ``.env``.
    """
    origin = Path(start) if start is not None else Path(__file__)
    origin = origin.resolve()
    directory = origin if origin.is_dir() else origin.parent
    for candidate in (directory, *directory.parents):
        for marker in _PROJECT_ROOT_MARKERS:
            if (candidate / marker).exists():
                return candidate
    return directory


def _dotenv_path() -> Path:
    return find_project_root() / ".env"


def _log_dotenv_resolution(root: Path, path: Path, *, exists: bool) -> None:
    global _dotenv_debug_logged
    if _dotenv_debug_logged:
        return
    _LOG.debug("Resolved project root: %s", root)
    _LOG.debug("Loaded dotenv: %s", path)
    _LOG.debug("Dotenv exists: %s", exists)
    _dotenv_debug_logged = True


def _dotenv_values() -> dict[str, str]:
    """Load the project-root ``.env`` if present (cwd-independent)."""
    try:
        from dotenv import dotenv_values
    except ImportError:
        return {}
    root = find_project_root()
    path = root / ".env"
    exists = path.is_file()
    _log_dotenv_resolution(root, path, exists=exists)
    if not exists:
        return {}
    raw = dotenv_values(path)
    return {str(k): str(v) for k, v in raw.items() if k and v is not None}


def _environ_map() -> dict[str, str]:
    """Merge project ``.env`` with process env (OS env wins)."""
    merged = _dotenv_values()
    merged.update({k: v for k, v in os.environ.items() if v is not None})
    return merged


def _nested_from_flat_map(flat: dict[str, Any]) -> dict[str, Any]:
    """Convert flat env/init keys into nested group dictionaries."""
    nested: dict[str, Any] = {name: {} for name in _GROUP_NAMES}
    passthrough: dict[str, Any] = {}

    for key, value in flat.items():
        if key in _GROUP_NAMES and isinstance(value, dict):
            nested[key] = {**nested.get(key, {}), **value}
            continue
        target = _FLAT_KEY_MAP.get(key) or _FLAT_KEY_MAP.get(key.upper())
        if target is None:
            # case-insensitive lookup for init kwargs
            target = _FLAT_KEY_MAP.get(key.lower())
            if target is None:
                for map_key, map_target in _FLAT_KEY_MAP.items():
                    if map_key.lower() == key.lower():
                        target = map_target
                        break
        if target is None:
            passthrough[key] = value
            continue
        group, field = target
        # First writer wins for env (so explicit init can override later via merge)
        if field not in nested[group]:
            nested[group][field] = value

    result = {**passthrough}
    for group, fields in nested.items():
        if fields:
            result[group] = fields
    return result


def nest_flat_settings_data(data: dict[str, Any] | None) -> dict[str, Any]:
    """Deep-merge nested groups with remapped flat keys (init-safe)."""
    if not data:
        return {}
    data = dict(data)
    existing_groups = {
        name: dict(data.pop(name))
        for name in list(data.keys())
        if name in _GROUP_NAMES and isinstance(data.get(name), dict)
    }
    remapped = _nested_from_flat_map(data)
    for name in _GROUP_NAMES:
        group_data = remapped.pop(name, {})
        if name in existing_groups or group_data:
            # Flat init keys (group_data) override env-hydrated nested groups.
            remapped[name] = {**existing_groups.get(name, {}), **group_data}
    remapped.update(data)
    return remapped


class _FlatEnvNestedSource(PydanticBaseSettingsSource):
    """Populate nested groups from historical flat environment variable names."""

    def get_field_value(
        self, field: Any, field_name: str
    ) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        env = _environ_map()
        nested = _nested_from_flat_map(env)
        # Root-level fields still use flat env names.
        if "IGNORE_DIRS" in env:
            nested["IGNORE_DIRS"] = env["IGNORE_DIRS"]
        elif "ignore_dirs" in env:
            nested["ignore_dirs"] = env["ignore_dirs"]
        if "REFACTORY_REPO_ROOT" in env:
            nested["REFACTORY_REPO_ROOT"] = env["REFACTORY_REPO_ROOT"]
        elif "repository_root" in env:
            nested["repository_root"] = env["repository_root"]
        return nested


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=str(find_project_root() / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    ai: AISettings = Field(default_factory=AISettings)
    backend: BackendSettings = Field(default_factory=BackendSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    prompt: PromptSettings = Field(default_factory=PromptSettings)
    github: GitHubSettings = Field(default_factory=GitHubSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    # Cross-cutting (parser / indexer)
    ignore_dirs: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_IGNORE_DIRS),
        alias="IGNORE_DIRS",
    )
    #: Default Local API repository when X-Repo-Root / ?root= are omitted.
    repository_root: str | None = Field(
        default=None,
        alias="REFACTORY_REPO_ROOT",
        description="Configured repository root path (Local API fallback).",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # init kwargs (incl. flat aliases) → flat env nested → ignore unused env
        return (
            init_settings,
            _FlatEnvNestedSource(settings_cls),
        )

    @model_validator(mode="before")
    @classmethod
    def _coerce_flat_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        return nest_flat_settings_data(data)

    @field_validator("ignore_dirs", mode="before")
    @classmethod
    def _parse_ignore_dirs(cls, value: object) -> list[str]:
        if value is None or value == "":
            return list(DEFAULT_IGNORE_DIRS)
        if isinstance(value, str):
            parts = [part.strip() for part in value.split(",") if part.strip()]
            return parts or list(DEFAULT_IGNORE_DIRS)
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        return list(DEFAULT_IGNORE_DIRS)

    # ------------------------------------------------------------------
    # Convenience delegates (paths)
    # ------------------------------------------------------------------

    def chroma_dir(self, repo_root: Path | None = None) -> Path:
        return self.embedding.chroma_dir(repo_root)

    def cache_dir(self, repo_root: Path | None = None) -> Path:
        return self.cache.dir(repo_root)

    def model_copy(
        self,
        *,
        update: dict[str, Any] | None = None,
        deep: bool = False,
    ) -> "Settings":
        """Support nested and legacy flat keys in ``update``."""
        if not update:
            return super().model_copy(deep=deep)
        nested_update = nest_flat_settings_data(dict(update))
        group_types: dict[str, type] = {
            "ai": AISettings,
            "backend": BackendSettings,
            "cache": CacheSettings,
            "prompt": PromptSettings,
            "github": GitHubSettings,
            "embedding": EmbeddingSettings,
            "logging": LoggingSettings,
        }
        final: dict[str, Any] = {}
        for key, value in nested_update.items():
            if key in group_types:
                current = getattr(self, key).model_dump()
                if isinstance(value, dict):
                    final[key] = group_types[key].model_validate({**current, **value})
                elif isinstance(value, group_types[key]):
                    final[key] = value
                else:
                    final[key] = group_types[key].model_validate(value)
            else:
                final[key] = value
        return super().model_copy(update=final, deep=deep)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
