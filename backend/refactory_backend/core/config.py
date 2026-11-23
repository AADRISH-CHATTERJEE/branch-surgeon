"""Backend settings (environment / .env)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Refactory Control Plane"
    app_version: str = "0.1.0"
    environment: str = Field(default="development", alias="REFACTORY_ENV")
    debug: bool = Field(default=False, alias="REFACTORY_DEBUG")

    # SQLite by default for local/dev; override with Postgres URL in production.
    database_url: str = Field(
        default="sqlite:///./refactory_backend.db",
        alias="REFACTORY_DATABASE_URL",
    )

    jwt_secret_key: str = Field(
        default="dev-only-change-me-refactory-control-plane",
        alias="REFACTORY_JWT_SECRET",
    )
    jwt_algorithm: str = Field(default="HS256", alias="REFACTORY_JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=30, alias="REFACTORY_ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_days: int = Field(default=14, alias="REFACTORY_REFRESH_TOKEN_EXPIRE_DAYS")

    # Seeded CLI user for local development (disabled when blank password).
    seed_admin_email: str = Field(default="cli@refactory.dev", alias="REFACTORY_SEED_ADMIN_EMAIL")
    seed_admin_password: str = Field(default="refactory-dev", alias="REFACTORY_SEED_ADMIN_PASSWORD")
    seed_admin_name: str = Field(default="CLI Developer", alias="REFACTORY_SEED_ADMIN_NAME")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
