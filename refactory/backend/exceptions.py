"""Typed errors for BackendClient / CLI auth."""

from __future__ import annotations

from refactory.core.exceptions import AuthenticationError, RefactoryError


class BackendError(RefactoryError):
    """Base error for control-plane client failures."""


class BackendUnavailableError(BackendError):
    """Backend host unreachable or timed out."""


class BackendAuthError(AuthenticationError, BackendError):
    """Invalid credentials, missing/expired tokens, or unauthorized response."""


class BackendNotConfiguredError(BackendError):
    """REFACTORY_BACKEND_URL is not set."""


class BackendResponseError(BackendError):
    """Unexpected HTTP status or payload from the backend."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
