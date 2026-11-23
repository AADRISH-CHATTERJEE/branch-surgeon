"""Repositories for Phase 11.5 organization management entities."""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select

from refactory.db.models import (
    OrganizationMemberModel,
    OrganizationModel,
    OrganizationRepositoryModel,
    TeamMemberModel,
    TeamModel,
    TeamRepositoryModel,
)
from refactory.db.repositories.base import BaseRepository


class OrganizationRepository(BaseRepository[OrganizationModel]):
    model_class = OrganizationModel

    def get_by_slug(self, slug: str) -> OrganizationModel | None:
        return self.get(slug=slug)

    def get_default(self) -> OrganizationModel | None:
        return self.get(is_default=True)

    def list_all(self, *, limit: int = 100) -> Sequence[OrganizationModel]:
        stmt = (
            select(OrganizationModel)
            .order_by(OrganizationModel.name.asc())
            .limit(limit)
        )
        return self._session.execute(stmt).scalars().all()


class TeamRepository(BaseRepository[TeamModel]):
    model_class = TeamModel

    def list_by_organization(
        self, organization_id: str, *, limit: int = 100
    ) -> Sequence[TeamModel]:
        stmt = (
            select(TeamModel)
            .where(TeamModel.organization_id == organization_id)
            .order_by(TeamModel.name.asc())
            .limit(limit)
        )
        return self._session.execute(stmt).scalars().all()

    def get_by_slug(self, organization_id: str, slug: str) -> TeamModel | None:
        return self.get(organization_id=organization_id, slug=slug)


class OrganizationMemberRepository(BaseRepository[OrganizationMemberModel]):
    model_class = OrganizationMemberModel

    def list_by_organization(
        self, organization_id: str, *, limit: int = 200
    ) -> Sequence[OrganizationMemberModel]:
        stmt = (
            select(OrganizationMemberModel)
            .where(OrganizationMemberModel.organization_id == organization_id)
            .order_by(OrganizationMemberModel.display_name.asc())
            .limit(limit)
        )
        return self._session.execute(stmt).scalars().all()


class TeamMemberRepository(BaseRepository[TeamMemberModel]):
    model_class = TeamMemberModel

    def list_by_team(self, team_id: str) -> Sequence[TeamMemberModel]:
        stmt = select(TeamMemberModel).where(TeamMemberModel.team_id == team_id)
        return self._session.execute(stmt).scalars().all()


class OrganizationRepositoryLinkRepository(BaseRepository[OrganizationRepositoryModel]):
    model_class = OrganizationRepositoryModel

    def list_by_organization(
        self, organization_id: str, *, limit: int = 200
    ) -> Sequence[OrganizationRepositoryModel]:
        stmt = (
            select(OrganizationRepositoryModel)
            .where(OrganizationRepositoryModel.organization_id == organization_id)
            .order_by(OrganizationRepositoryModel.repository_name.asc())
            .limit(limit)
        )
        return self._session.execute(stmt).scalars().all()

    def get_by_root(
        self, organization_id: str, root_path: str
    ) -> OrganizationRepositoryModel | None:
        return self.get(
            organization_id=organization_id, repository_root_path=root_path
        )


class TeamRepositoryLinkRepository(BaseRepository[TeamRepositoryModel]):
    model_class = TeamRepositoryModel

    def list_by_team(self, team_id: str) -> Sequence[TeamRepositoryModel]:
        stmt = select(TeamRepositoryModel).where(TeamRepositoryModel.team_id == team_id)
        return self._session.execute(stmt).scalars().all()
