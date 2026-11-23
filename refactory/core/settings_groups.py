"""Logical settings groups for maintainable configuration.

These are plain models (not env-aware). ``Settings`` hydrates them from the
historical flat environment variable names.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class AISettings(BaseModel):
    """AI gateway / provider preferences."""

    provider: str = "mock"
    model: str | None = None
    timeout_seconds: float = 60.0
    max_retries: int = 2
    fallback_provider: str | None = None
    gemini_api_key: str | None = None
    openai_api_key: str | None = None

    @field_validator("provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: object) -> str:
        text = str(value or "mock").strip().lower()
        return text or "mock"

    @field_validator("fallback_provider", mode="before")
    @classmethod
    def _normalize_fallback(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip().lower()
        if not text or text in {"none", "null", "off", "disabled"}:
            return None
        return text


class BackendSettings(BaseModel):
    """Control-plane client configuration."""

    url: str | None = "http://127.0.0.1:8000"

    @field_validator("url", mode="before")
    @classmethod
    def _normalize_url(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.lower() in {"none", "null", "off", "disabled"}:
            return None
        return text.rstrip("/")


class CacheSettings(BaseModel):
    """Deterministic pipeline cache configuration."""

    enabled: bool = True
    ai_responses: bool = False
    path: str = ".refactory/cache"

    def dir(self, repo_root: Path | None = None) -> Path:
        """Resolve cache directory (absolute or relative to repo)."""
        path = Path(self.path)
        if path.is_absolute():
            return path
        base = repo_root or Path.cwd()
        return (base / path).resolve()


class PromptSettings(BaseModel):
    """Prompt assembly / context budget configuration."""

    template_version: str = "2.0.0"
    max_tokens: int = 6000
    max_retrieved_files: int = 8
    max_symbols: int = 16
    max_related_files: int = 8
    max_graph_depth: int = 3


class GitHubSettings(BaseModel):
    """GitHub integration credentials."""

    token: str | None = None


class EmbeddingSettings(BaseModel):
    """Embedding model, vector store paths, and retrieval defaults."""

    model: str = "BAAI/bge-small-en-v1.5"
    chroma_path: str = ".refactory/chroma"
    retrieval_top_k: int = 12

    def chroma_dir(self, repo_root: Path | None = None) -> Path:
        """Resolve Chroma persistence directory (absolute or relative to repo)."""
        path = Path(self.chroma_path)
        if path.is_absolute():
            return path
        base = repo_root or Path.cwd()
        return (base / path).resolve()


class LoggingSettings(BaseModel):
    """Process logging configuration."""

    level: str = "INFO"
