"""AIService facade — orchestration helper above AIGateway (no GitHub/review wiring)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from refactory.ai.gateway import AIGateway
from refactory.ai.models import AIRequest, AIResponse
from refactory.ai.response_parser import ResponseParser
from refactory.github.models import PullRequest
from refactory.prompt.builder import PromptBuilder
from refactory.prompt.models import PromptRequest
from refactory.review.models import Repository, ReviewResult

if TYPE_CHECKING:
    from loguru import Logger


class AIService:
    """High-level AI entry for future ReviewEngine steps.

    ReviewEngine remains unchanged and still calls ``review_pull_request`` (stub).
    New code should prefer ``AIGateway.generate`` / ``AIService.complete``.
    """

    def __init__(
        self,
        gateway: AIGateway,
        prompt_builder: PromptBuilder,
        response_parser: ResponseParser,
        logger: "Logger",
    ) -> None:
        self._gateway = gateway
        self._prompt_builder = prompt_builder
        self._response_parser = response_parser
        self._logger = logger

    @property
    def gateway(self) -> AIGateway:
        return self._gateway

    def complete(self, request: AIRequest) -> AIResponse:
        """Pass-through to the gateway."""
        return self._gateway.generate(request)

    def complete_prompt(self, prompt: PromptRequest) -> AIResponse:
        """Convert PromptRequest → AIRequest and generate (CLI / future review)."""
        return self._gateway.generate(AIRequest.from_prompt_request(prompt))

    def review_pull_request(
        self,
        repository: Repository,
        pull_request: PullRequest,
        related_context: list[str],
    ) -> ReviewResult:
        """Build prompt → call provider → parse structured review."""
        self._logger.debug(
            "AIService.review_pull_request called for PR #{}",
            pull_request.number,
        )
        raise NotImplementedError("AI pull request review not implemented yet")

    def summarize_repository(self, repository: Repository, context: str) -> dict:
        self._logger.debug("AIService.summarize_repository called")
        raise NotImplementedError("Repository summarization not implemented yet")

    def summarize_diff(self, pull_request: PullRequest) -> dict:
        self._logger.debug("AIService.summarize_diff called")
        raise NotImplementedError("Diff summarization not implemented yet")
