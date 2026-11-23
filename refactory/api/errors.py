"""Map Refactory errors to HTTP responses with the ApiResponse envelope."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from refactory.api.schemas import fail
from refactory.core.exceptions import (
    AIProviderError,
    ConfigurationError,
    PullRequestNotFound,
    RefactoryError,
    RepositoryNotFound,
)
from refactory.transformation.models import TransformationError


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RepositoryNotFound)
    async def _repo_not_found(_request: Request, exc: RepositoryNotFound) -> JSONResponse:
        body = fail(exc.message, message="Repository not found")
        return JSONResponse(status_code=404, content=body.model_dump(mode="json"))

    @app.exception_handler(PullRequestNotFound)
    async def _pr_not_found(_request: Request, exc: PullRequestNotFound) -> JSONResponse:
        body = fail(exc.message, message="Pull request not found")
        return JSONResponse(status_code=404, content=body.model_dump(mode="json"))

    @app.exception_handler(ConfigurationError)
    async def _config_error(_request: Request, exc: ConfigurationError) -> JSONResponse:
        body = fail(exc.message, message="Configuration error")
        return JSONResponse(status_code=400, content=body.model_dump(mode="json"))

    @app.exception_handler(AIProviderError)
    async def _ai_error(_request: Request, exc: AIProviderError) -> JSONResponse:
        body = fail(exc.message, message="AI provider error")
        return JSONResponse(status_code=502, content=body.model_dump(mode="json"))

    @app.exception_handler(TransformationError)
    async def _transform_error(_request: Request, exc: TransformationError) -> JSONResponse:
        errors = list(exc.errors) if exc.errors else [exc.reason or exc.message]
        body = fail(
            *errors,
            message=exc.message or "Transformation failed",
            meta=exc.meta,
        )
        status_code = int(getattr(exc, "status_code", None) or 422)
        return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details: list[str] = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
            msg = str(err.get("msg") or "Invalid value")
            details.append(f"{loc}: {msg}" if loc else msg)
        if not details:
            details = ["Invalid transformation request."]
        body = fail(
            *details,
            message="Invalid transformation request.",
            meta={"validation_errors": exc.errors()},
        )
        return JSONResponse(status_code=422, content=body.model_dump(mode="json"))

    @app.exception_handler(RefactoryError)
    async def _refactory_error(_request: Request, exc: RefactoryError) -> JSONResponse:
        body = fail(exc.message, message="Refactory error")
        return JSONResponse(status_code=400, content=body.model_dump(mode="json"))

    @app.exception_handler(Exception)
    async def _unexpected(_request: Request, exc: Exception) -> JSONResponse:
        body = fail(str(exc), message="Unexpected server error")
        return JSONResponse(status_code=500, content=body.model_dump(mode="json"))
