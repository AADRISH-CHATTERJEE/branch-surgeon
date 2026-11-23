"""FastAPI application entrypoint — Refactory control plane."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from refactory_backend import __version__
from refactory_backend.api.router import api_router
from refactory_backend.core.config import get_settings
from refactory_backend.db.base import Base
from refactory_backend.db.session import get_engine, get_session_factory
from refactory_backend.services.auth import AuthService

# Ensure models are registered on Base.metadata before create_all.
from refactory_backend import models as _models  # noqa: F401


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = get_engine(settings)
    Base.metadata.create_all(bind=engine)
    session_factory = get_session_factory(settings)
    db = session_factory()
    try:
        AuthService(db=db, settings=settings).ensure_seed_user()
    finally:
        db.close()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Refactory control plane for CLI clients. "
            "Provides authentication and downloadable configuration: "
            "versioned prompts/workflows, organization and repository settings, "
            "coding standards, review policies, feature flags, and AI preferences. "
            "Does **not** parse repositories, generate embeddings, run AI reviews, "
            "or store customer source code. The CLI downloads configuration only."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.include_router(api_router)

    @app.get("/health", tags=["system"], summary="Liveness probe")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "refactory-backend", "version": __version__}

    return app


app = create_app()
