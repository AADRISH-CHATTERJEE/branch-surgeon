"""Centralized Loguru configuration with structured review context.

Services receive a bound logger from the DI container. Every record carries
structured fields (prefer ``bind`` / ``contextualize`` over string formatting):

- elapsed_ms
- repository
- review_id
- provider
- model
- request_id
- severity
"""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Iterator
from uuid import uuid4

from loguru import logger

if TYPE_CHECKING:
    from loguru import Logger


_CONFIGURED = False

# Wall-clock start for the active logging operation (elapsed on every record).
_operation_start: ContextVar[float | None] = ContextVar(
    "refactory_operation_start", default=None
)

STRUCTURED_DEFAULTS: dict[str, Any] = {
    "service": "-",
    "elapsed_ms": 0.0,
    "repository": "-",
    "review_id": "-",
    "provider": "-",
    "model": "-",
    "request_id": "-",
    "severity": "-",
    "cache": "-",
}

_STRUCTURED_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{extra[service]}</cyan> | "
    "elapsed_ms={extra[elapsed_ms]} "
    "repository={extra[repository]} "
    "review_id={extra[review_id]} "
    "provider={extra[provider]} "
    "model={extra[model]} "
    "request_id={extra[request_id]} "
    "severity={extra[severity]} | "
    "<level>{message}</level>"
)


def _patch_record(record: dict[str, Any]) -> None:
    """Ensure required structured fields exist on every Loguru record."""
    extra = record["extra"]
    for key, default in STRUCTURED_DEFAULTS.items():
        if key not in extra or extra[key] is None or extra[key] == "":
            extra[key] = default

    start = _operation_start.get()
    if start is not None:
        extra["elapsed_ms"] = round((time.perf_counter() - start) * 1000.0, 3)

    # Mirror Loguru level into severity when caller did not set a custom value.
    if extra.get("severity") in {None, "", "-"}:
        extra["severity"] = record["level"].name.lower()


def setup_logging(level: str = "INFO") -> "Logger":
    """Configure the process-wide Loguru sink once; return the root logger."""
    global _CONFIGURED
    if not _CONFIGURED:
        logger.remove()
        logger.configure(patcher=_patch_record)
        logger.add(
            sys.stderr,
            level=level.upper(),
            format=_STRUCTURED_FORMAT,
            enqueue=False,
            backtrace=False,
            diagnose=False,
        )
        _CONFIGURED = True
    return logger


def get_service_logger(service_name: str, level: str = "INFO") -> "Logger":
    """Return a logger bound with a service name.

    Other structured fields come from ``contextualize`` / ``bind_context`` /
    the process-wide patcher defaults — do not pre-bind ``repository`` etc.
    or they will shadow review-scoped context.
    """
    setup_logging(level)
    return logger.bind(service=service_name)


def bind_context(log: "Logger", **fields: Any) -> "Logger":
    """Bind non-empty structured fields onto ``log``."""
    cleaned: dict[str, Any] = {}
    for key, value in fields.items():
        if value is None or value == "":
            continue
        cleaned[key] = value
    return log.bind(**cleaned) if cleaned else log


@contextmanager
def logging_operation(start: float | None = None) -> Iterator[float]:
    """Track elapsed_ms for all logs inside the block via contextvar."""
    token = _operation_start.set(start if start is not None else time.perf_counter())
    try:
        begun = _operation_start.get()
        assert begun is not None
        yield begun
    finally:
        _operation_start.reset(token)


@contextmanager
def review_logging_context(
    *,
    repository: str | None = None,
    review_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    request_id: str | None = None,
) -> Iterator[str]:
    """Apply Loguru contextualize for a review-scoped correlation id."""
    rid = request_id or str(uuid4())
    with logger.contextualize(
        repository=repository or "-",
        review_id=review_id or "-",
        provider=provider or "-",
        model=model or "-",
        request_id=rid,
    ):
        with logging_operation():
            yield rid


def new_request_id() -> str:
    return str(uuid4())


def reset_logging_for_tests() -> None:
    """Test helper to allow reconfiguration between cases."""
    global _CONFIGURED
    _CONFIGURED = False
    logger.remove()
    logger.configure(patcher=None)
