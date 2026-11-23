"""Local FastAPI application — engine presentation layer.

Run::

    uvicorn refactory.api.app:app --host 127.0.0.1 --port 8741

This is distinct from ``backend/refactory_backend`` (control plane).
"""

from __future__ import annotations

from refactory import __version__


def create_app():
    """Build the local Refactory engine API."""
    import os

    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from refactory.api.errors import register_exception_handlers
    from refactory.api.routes import api_router
    from refactory.api.schemas import ApiResponse, ok

    app = FastAPI(
        title="Refactory Local API",
        version=__version__,
        description=(
            "Local REST presentation layer over Refactory's ServiceContainer. "
            "Exposes review, recommend, transform, graph, index, and company rules "
            "for the current repository. "
            "This is **not** the control-plane backend "
            "(``backend/refactory_backend``), which only distributes auth/config."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Local UI (Next.js default). Override with comma-separated REFACTORY_CORS_ORIGINS.
    cors_raw = os.environ.get(
        "REFACTORY_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    )
    allow_origins = [o.strip() for o in cors_raw.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get(
        "/health",
        response_model=ApiResponse,
        tags=["system"],
        summary="Local API liveness",
        description="Process health check (does not exercise engines).",
    )
    def health() -> ApiResponse:
        return ok(
            {"service": "refactory-local-api", "version": __version__},
            message="ok",
        )

    return app


def __getattr__(name: str):
    """Lazy-load ``app`` so importing refactory.api.app does not require FastAPI
    until the local API is actually used.

    Important: do **not** assign ``app = None`` at module level. That puts
    ``app`` in the module ``__dict__``, so Python never calls ``__getattr__``
    and uvicorn receives ``None`` (startup looks fine; every request 500s).
    """
    if name == "app":
        # Cache on the module so subsequent lookups hit __dict__ directly.
        instance = create_app()
        globals()["app"] = instance
        return instance
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
