"""Structured Loguru fields for review pipeline logs."""

from __future__ import annotations

import io

from loguru import logger

from refactory.core.logger import (
    STRUCTURED_DEFAULTS,
    get_service_logger,
    reset_logging_for_tests,
    review_logging_context,
    setup_logging,
)


def test_setup_logging_includes_structured_fields():
    reset_logging_for_tests()
    stream = io.StringIO()
    setup_logging("DEBUG")
    logger.remove()
    logger.add(stream, format="{extra[service]}|{extra[elapsed_ms]}|{extra[repository]}|"
                "{extra[review_id]}|{extra[provider]}|{extra[model]}|"
                "{extra[request_id]}|{extra[severity]}|{message}")

    log = get_service_logger("test.svc")
    with review_logging_context(
        repository="demo",
        review_id="pr-7",
        provider="mock",
        model="mock-1",
        request_id="req-abc",
    ):
        log.info("hello structured")

    line = stream.getvalue()
    assert "test.svc" in line
    assert "demo" in line
    assert "pr-7" in line
    assert "mock" in line
    assert "mock-1" in line
    assert "req-abc" in line
    assert "hello structured" in line
    # severity mirrors level
    assert "info" in line.lower()
    reset_logging_for_tests()


def test_structured_defaults_keys():
    assert {
        "elapsed_ms",
        "repository",
        "review_id",
        "provider",
        "model",
        "request_id",
        "severity",
    }.issubset(STRUCTURED_DEFAULTS.keys())
