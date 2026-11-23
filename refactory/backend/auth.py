"""Local JWT persistence for CLI ↔ control-plane authentication."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from refactory.backend.exceptions import BackendAuthError
from refactory.backend.models import StoredAuth, TokenPair


def default_auth_path() -> Path:
    override = os.environ.get("REFACTORY_AUTH_PATH")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".refactory" / "auth.json"


class TokenStore:
    """Read/write ``~/.refactory/auth.json`` (access/refresh/expiry/URL only)."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or default_auth_path()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> StoredAuth | None:
        if not self._path.is_file():
            return None
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return StoredAuth.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            raise BackendAuthError(f"Corrupt auth file at {self._path}: {exc}") from exc

    def save(self, auth: StoredAuth) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = auth.model_dump(mode="json")
        # Never persist passwords (defense in depth).
        for forbidden in ("password", "passwd", "secret"):
            payload.pop(forbidden, None)
        self._path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass

    def save_tokens(self, tokens: TokenPair, *, backend_url: str) -> StoredAuth:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(tokens.expires_in, 0))
        auth = StoredAuth(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_at=expires_at,
            backend_url=backend_url.rstrip("/"),
            token_type=tokens.token_type or "bearer",
        )
        self.save(auth)
        return auth

    def clear(self) -> bool:
        """Remove stored tokens. Returns True if a file was deleted."""
        if self._path.is_file():
            self._path.unlink()
            return True
        return False

    def exists(self) -> bool:
        return self._path.is_file()

    def is_access_expired(self, auth: StoredAuth | None = None, *, skew_seconds: int = 30) -> bool:
        stored = auth if auth is not None else self.load()
        if stored is None:
            return True
        expires = stored.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= (expires - timedelta(seconds=skew_seconds))
