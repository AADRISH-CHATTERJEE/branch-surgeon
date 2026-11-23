"""Compatibility shim — real PromptBuilder lives in ``refactory.prompt``.

AIService still type-hints this import path. Review prompt assembly is done via
``refactory.prompt.builder.PromptBuilder.build``; the legacy method remains a
stub until AI integration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from refactory.github.models import PullRequest
from refactory.prompt.builder import PromptBuilder as ReviewPromptBuilder
from refactory.review.models import Repository

if TYPE_CHECKING:
    from loguru import Logger

# Re-export the real builder for new code.
PromptBuilder = ReviewPromptBuilder


class LegacyPromptBuilder:
    """Deprecated thin wrapper kept for explicit legacy call sites."""

    def __init__(self, logger: "Logger") -> None:
        self._logger = logger
        self._builder = ReviewPromptBuilder(logger=logger)

    def build_review_prompt(
        self,
        repository: Repository,
        pull_request: PullRequest,
        related_context: list[str],
    ) -> str:
        self._logger.debug("LegacyPromptBuilder.build_review_prompt called")
        raise NotImplementedError(
            "Use refactory.prompt.PromptBuilder.build(PromptContext) instead"
        )
