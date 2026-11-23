"""GitHubService skeleton — PR fetch / auth (PyGithub in a later phase)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from refactory.core.settings_groups import GitHubSettings
from refactory.github.models import PullRequest
from refactory.review.models import Repository

if TYPE_CHECKING:
    from loguru import Logger


class GitHubService:
    def __init__(
        self,
        logger: "Logger",
        settings: GitHubSettings | None = None,
        *,
        token: str | None = None,
    ) -> None:
        # ``token`` retained for backwards-compatible call sites / tests.
        self._settings = settings or GitHubSettings(token=token)
        self._token = self._settings.token if token is None else token
        self._logger = logger

    def authenticate(self) -> str:
        """Validate credentials and return the authenticated login."""
        self._logger.debug("GitHubService.authenticate called")
        raise NotImplementedError("GitHub authentication not implemented yet")

    def fetch_pull_request(self, repository: Repository, pr_number: int) -> PullRequest:
        """Fetch pull request title, body, files, commits, and diff."""
        self._logger.debug(
            "GitHubService.fetch_pull_request called for {}#{}",
            repository.full_name or repository.name,
            pr_number,
        )
        raise NotImplementedError("GitHub pull request fetch not implemented yet")
