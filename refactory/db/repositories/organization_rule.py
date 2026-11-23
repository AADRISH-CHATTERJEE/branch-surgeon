"""Repositories for organization rules and audit entries."""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select

from refactory.db.models import OrganizationRuleAuditModel, OrganizationRuleModel
from refactory.db.repositories.base import BaseRepository


class OrganizationRuleRepository(BaseRepository[OrganizationRuleModel]):
    model_class = OrganizationRuleModel

    def list_all(self, *, limit: int = 500) -> Sequence[OrganizationRuleModel]:
        stmt = (
            select(OrganizationRuleModel)
            .order_by(OrganizationRuleModel.name.asc())
            .limit(limit)
        )
        return self._session.execute(stmt).scalars().all()


class OrganizationRuleAuditRepository(BaseRepository[OrganizationRuleAuditModel]):
    model_class = OrganizationRuleAuditModel

    def list_by_rule(
        self, rule_id: str, *, limit: int = 50
    ) -> Sequence[OrganizationRuleAuditModel]:
        stmt = (
            select(OrganizationRuleAuditModel)
            .where(OrganizationRuleAuditModel.rule_id == rule_id)
            .order_by(OrganizationRuleAuditModel.created_at.desc())
            .limit(limit)
        )
        return self._session.execute(stmt).scalars().all()

    def list_recent(self, *, limit: int = 50) -> Sequence[OrganizationRuleAuditModel]:
        stmt = (
            select(OrganizationRuleAuditModel)
            .order_by(OrganizationRuleAuditModel.created_at.desc())
            .limit(limit)
        )
        return self._session.execute(stmt).scalars().all()
