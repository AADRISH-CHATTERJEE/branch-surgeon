"""Protocols the ReviewEngine depends on.

Defining stable interfaces here keeps the orchestration layer decoupled from
concrete infrastructure (GitPython, PyGithub, Chroma, Gemini, etc.).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from refactory.github.models import PullRequest
from refactory.graph.models import RepositoryGraph
from refactory.indexer.models import RepositoryIndex
from refactory.prompt.models import PromptContext, PromptRequest
from refactory.review.models import Repository, RepositorySummary, ReviewResult

if TYPE_CHECKING:
    from refactory.ai.models import AIRequest, AIResponse
    from refactory.response.models import ParsedReview


@runtime_checkable
class GitServicePort(Protocol):
    def require_repository(self) -> Repository: ...

    def get_repository_metadata(self) -> Repository: ...


@runtime_checkable
class GitHubServicePort(Protocol):
    def authenticate(self) -> str: ...

    def fetch_pull_request(self, repository: Repository, pr_number: int) -> PullRequest: ...


@runtime_checkable
class ParserServicePort(Protocol):
    def parse_repository(self, repository: Repository) -> RepositorySummary: ...


@runtime_checkable
class IndexerServicePort(Protocol):
    def index_repository(self, repository: Repository, *, force: bool = False) -> int: ...

    def ensure_index(self, repository: Repository) -> int: ...

    def clear_index(self, repository: Repository) -> None: ...

    def has_index(self, repository: Repository) -> bool: ...

    def load_index(self, root: Path | str) -> RepositoryIndex | None: ...

    def get_last_index(self) -> RepositoryIndex | None: ...


@runtime_checkable
class RepositoryGraphServicePort(Protocol):
    def build_graph(self, index: RepositoryIndex) -> RepositoryGraph: ...

    def affected_files(self, path: str) -> list[str]: ...


@runtime_checkable
class RetrievalServicePort(Protocol):
    def retrieve_related_context(
        self,
        pull_request: PullRequest,
        *,
        top_k: int = 8,
        root: Path | str | None = None,
    ) -> list[str]: ...

    def search(self, query: str, *, top_k: int = 8, root: Path | str | None = None) -> object: ...

    def related_files(
        self,
        path: str,
        *,
        top_k: int = 8,
        root: Path | str | None = None,
    ) -> object: ...


@runtime_checkable
class PromptBuilderPort(Protocol):
    def build(self, context: PromptContext) -> PromptRequest: ...


@runtime_checkable
class AIGatewayPort(Protocol):
    def generate(self, request: AIRequest) -> AIResponse: ...


@runtime_checkable
class ResponseParserPort(Protocol):
    def parse(
        self, text: str, *, provider: str | None = None, model: str | None = None
    ) -> ParsedReview: ...

    def parse_response(self, response: AIResponse) -> ParsedReview: ...


@runtime_checkable
class AIServicePort(Protocol):
    def review_pull_request(
        self,
        repository: Repository,
        pull_request: PullRequest,
        related_context: list[str],
    ) -> ReviewResult: ...
