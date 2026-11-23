"""Repository for analysis_history rows."""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from sqlalchemy import delete, func, select

from refactory.db.models import AnalysisHistoryModel
from refactory.db.repositories.base import BaseRepository


class AnalysisHistoryRepository(BaseRepository[AnalysisHistoryModel]):
    model_class = AnalysisHistoryModel

    def list_filtered(
        self,
        *,
        repository_id: str | None = None,
        analysis_type: str | None = None,
        status: str | None = None,
        branch: str | None = None,
        search: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AnalysisHistoryModel]:
        stmt = select(AnalysisHistoryModel)
        if repository_id:
            stmt = stmt.where(AnalysisHistoryModel.repository_id == repository_id)
        if analysis_type:
            stmt = stmt.where(AnalysisHistoryModel.analysis_type == analysis_type)
        if status:
            stmt = stmt.where(AnalysisHistoryModel.status == status)
        if branch:
            stmt = stmt.where(AnalysisHistoryModel.branch == branch)
        if since is not None:
            stmt = stmt.where(AnalysisHistoryModel.timestamp >= since)
        if until is not None:
            stmt = stmt.where(AnalysisHistoryModel.timestamp <= until)
        if search:
            q = f"%{search}%"
            stmt = stmt.where(
                AnalysisHistoryModel.summary.ilike(q)
                | AnalysisHistoryModel.repository_name.ilike(q)
                | AnalysisHistoryModel.analysis_type.ilike(q)
                | AnalysisHistoryModel.branch.ilike(q)
                | AnalysisHistoryModel.commit.ilike(q)
            )
        stmt = (
            stmt.order_by(AnalysisHistoryModel.timestamp.desc())
            .offset(offset)
            .limit(limit)
        )
        return self._session.execute(stmt).scalars().all()

    def count_filtered(
        self,
        *,
        repository_id: str | None = None,
        analysis_type: str | None = None,
        status: str | None = None,
        since: datetime | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(AnalysisHistoryModel)
        if repository_id:
            stmt = stmt.where(AnalysisHistoryModel.repository_id == repository_id)
        if analysis_type:
            stmt = stmt.where(AnalysisHistoryModel.analysis_type == analysis_type)
        if status:
            stmt = stmt.where(AnalysisHistoryModel.status == status)
        if since is not None:
            stmt = stmt.where(AnalysisHistoryModel.timestamp >= since)
        return int(self._session.execute(stmt).scalar() or 0)

    def average_duration_ms(self, *, repository_id: str | None = None) -> float:
        stmt = select(func.avg(AnalysisHistoryModel.duration_ms))
        if repository_id:
            stmt = stmt.where(AnalysisHistoryModel.repository_id == repository_id)
        val = self._session.execute(stmt).scalar()
        return float(val or 0.0)

    def delete_older_than(self, cutoff: datetime, *, repository_id: str | None = None) -> int:
        stmt = delete(AnalysisHistoryModel).where(AnalysisHistoryModel.timestamp < cutoff)
        if repository_id:
            stmt = stmt.where(AnalysisHistoryModel.repository_id == repository_id)
        result = self._session.execute(stmt)
        self._session.flush()
        return int(result.rowcount or 0)
