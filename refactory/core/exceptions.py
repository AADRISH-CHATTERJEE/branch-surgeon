"""Centralized exception hierarchy for Refactory.

Services and the review engine raise these typed errors. The CLI (and a future
FastAPI layer) map them to user-facing messages / HTTP status codes.
"""

from __future__ import annotations


class RefactoryError(Exception):
    """Base error for all application failures."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ConfigurationError(RefactoryError):
    """Invalid or missing configuration."""


class AuthenticationError(RefactoryError):
    """Credential or auth provider failure."""


class RepositoryNotFound(RefactoryError):
    """Working directory is not a Git repository, or remote repo is missing."""


class CommitNotFound(RefactoryError):
    """Requested commit hash does not exist or cannot be resolved."""


class PullRequestNotFound(RefactoryError):
    """Requested pull request does not exist or is inaccessible."""


class EmbeddingError(RefactoryError):
    """Local embedding generation or vector upsert failed."""


class AIProviderError(RefactoryError):
    """LLM provider call or response normalization failed."""


class TransientAIProviderError(AIProviderError):
    """Retryable AI provider failure (timeout, rate limit, 5xx)."""


class RateLimitAIProviderError(TransientAIProviderError):
    """Provider rate-limited the request (typically HTTP 429)."""


class IndexError_(RefactoryError):
    """Local index operations failed (name avoids shadowing builtin IndexError)."""


class StorageError(RefactoryError):
    """Persistence layer failure (e.g. ChromaDB)."""


class ParserError(RefactoryError):
    """Source parsing failed (unsupported language, IO, or fatal parse error)."""
