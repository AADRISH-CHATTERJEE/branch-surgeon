"""Password hashing and JWT helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from jose import JWTError, jwt
from passlib.context import CryptContext

from refactory_backend.core.config import Settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_token(
    *,
    subject: str,
    token_type: TokenType,
    settings: Settings,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    if token_type == "access":
        expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    else:
        expire = now + timedelta(days=settings.refresh_token_expire_days)

    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": str(uuid4()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, settings: Settings) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def safe_decode_token(token: str, settings: Settings) -> dict[str, Any] | None:
    try:
        return decode_token(token, settings)
    except JWTError:
        return None
