"""Authentication service (JWT issue/refresh, user lookup)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from refactory_backend.core.config import Settings
from refactory_backend.core.security import (
    create_token,
    hash_password,
    safe_decode_token,
    verify_password,
)
from refactory_backend.models.user import User
from refactory_backend.schemas.auth import TokenResponse


class AuthService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    def get_user_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.lower())
        return self._db.scalar(stmt)

    def get_user_by_id(self, user_id: int) -> User | None:
        return self._db.get(User, user_id)

    def authenticate(self, email: str, password: str) -> User | None:
        user = self.get_user_by_email(email)
        if user is None or not user.is_active:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    def issue_tokens(self, user: User) -> TokenResponse:
        access = create_token(
            subject=user.email,
            token_type="access",
            settings=self._settings,
            extra_claims={"uid": user.id},
        )
        refresh = create_token(
            subject=user.email,
            token_type="refresh",
            settings=self._settings,
            extra_claims={"uid": user.id},
        )
        return TokenResponse(
            access_token=access,
            refresh_token=refresh,
            expires_in=self._settings.access_token_expire_minutes * 60,
        )

    def refresh_tokens(self, refresh_token: str) -> TokenResponse | None:
        payload = safe_decode_token(refresh_token, self._settings)
        if payload is None or payload.get("type") != "refresh":
            return None
        email = payload.get("sub")
        if not email:
            return None
        user = self.get_user_by_email(str(email))
        if user is None or not user.is_active:
            return None
        return self.issue_tokens(user)

    def ensure_seed_user(self) -> User | None:
        """Create the configured seed admin when missing (dev convenience)."""
        email = self._settings.seed_admin_email.strip().lower()
        password = self._settings.seed_admin_password
        if not email or not password:
            return None
        existing = self.get_user_by_email(email)
        if existing is not None:
            return existing
        user = User(
            email=email,
            full_name=self._settings.seed_admin_name,
            hashed_password=hash_password(password),
            is_active=True,
            is_superuser=True,
        )
        self._db.add(user)
        self._db.commit()
        self._db.refresh(user)
        return user
