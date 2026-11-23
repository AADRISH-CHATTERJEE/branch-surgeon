"""Unit of Work — transactional boundary for multi-repository operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from refactory.db.repositories.analysis_history import AnalysisHistoryRepository
from refactory.db.repositories.analysis_run import AnalysisRunRepository
from refactory.db.repositories.embedding import EmbeddingRepository
from refactory.db.repositories.file import FileRepository
from refactory.db.repositories.graph import GraphRepository
from refactory.db.repositories.import_ import ImportRepository
from refactory.db.repositories.metric import MetricRepository
from refactory.db.repositories.organization import (
    OrganizationMemberRepository,
    OrganizationRepository,
    OrganizationRepositoryLinkRepository,
    TeamMemberRepository,
    TeamRepository,
    TeamRepositoryLinkRepository,
)
from refactory.db.repositories.organization_rule import (
    OrganizationRuleAuditRepository,
    OrganizationRuleRepository,
)
from refactory.db.repositories.patch import PatchRepository
from refactory.db.repositories.recommendation import RecommendationRepository
from refactory.db.repositories.repository import RepositoryRepository
from refactory.db.repositories.review import ReviewRepository
from refactory.db.repositories.review_suggestion import ReviewSuggestionRepository
from refactory.db.repositories.symbol import SymbolRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from refactory.db.session import SessionFactory


class UnitOfWork:
    """Demarcates a transactional boundary.

    Usage::

        with UnitOfWork(session_factory) as uow:
            repo = uow.repositories.create(name="my-repo", root_path="/code")
            uow.files.create(repository_id=repo.id, path="app.py", language="python")
            # auto-commits on exit; auto-rolls-back on exception
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None

    def __enter__(self) -> UnitOfWork:
        self._session = self._session_factory()
        self.repositories = RepositoryRepository(self._session)
        self.files = FileRepository(self._session)
        self.symbols = SymbolRepository(self._session)
        self.imports = ImportRepository(self._session)
        self.reviews = ReviewRepository(self._session)
        self.review_suggestions = ReviewSuggestionRepository(self._session)
        self.recommendations = RecommendationRepository(self._session)
        self.patches = PatchRepository(self._session)
        self.embeddings = EmbeddingRepository(self._session)
        self.graph = GraphRepository(self._session)
        self.metrics = MetricRepository(self._session)
        self.analysis_runs = AnalysisRunRepository(self._session)
        self.analysis_history = AnalysisHistoryRepository(self._session)
        self.organization_rules = OrganizationRuleRepository(self._session)
        self.organization_rule_audits = OrganizationRuleAuditRepository(self._session)
        self.organizations = OrganizationRepository(self._session)
        self.teams = TeamRepository(self._session)
        self.organization_members = OrganizationMemberRepository(self._session)
        self.team_members = TeamMemberRepository(self._session)
        self.organization_repositories = OrganizationRepositoryLinkRepository(
            self._session
        )
        self.team_repositories = TeamRepositoryLinkRepository(self._session)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        self.close()

    def commit(self) -> None:
        if self._session:
            self._session.commit()

    def rollback(self) -> None:
        if self._session:
            self._session.rollback()

    def close(self) -> None:
        if self._session:
            self._session.close()
            self._session = None

    @property
    def session(self) -> Session:
        if self._session is None:
            raise RuntimeError("UnitOfWork is not active — use within a `with` block")
        return self._session
