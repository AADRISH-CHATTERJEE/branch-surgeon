"""ResponseParser skeleton — normalize provider JSON into ReviewResult."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from refactory.review.models import ReviewResult

if TYPE_CHECKING:
    from loguru import Logger


class ResponseParser:
    def __init__(self, logger: "Logger") -> None:
        self._logger = logger

    def parse_review(self, payload: dict[str, Any], *, pr_number: int) -> ReviewResult:
        self._logger.debug("ResponseParser.parse_review called for PR #{}", pr_number)
        raise NotImplementedError("Review response parsing not implemented yet")
