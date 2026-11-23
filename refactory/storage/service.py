"""StorageService — persistent storage for all Refactory analyses.

Stores analysis results, metrics, and session history in SQLite/PostgreSQL.
Uses background writes to avoid slowing CLI execution.
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from refactory.storage.database import DatabaseEngine
from refactory.storage.models import AnalysisRun, HistoricalMetric, RepositoryRecord, SessionRecord

if TYPE_CHECKING:
    from loguru import Logger


class StorageService:
    """Persistent storage for Refactory analysis results."""

    def __init__(
        self,
        logger: "Logger",
        database_url: str | None = None,
        *,
        background: bool = True,
        repo_root: Path | None = None,
    ) -> None:
        self._logger = logger
        self._db = DatabaseEngine(database_url, repo_root=repo_root)
        self._db.create_tables()
        self._background = background
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="storage")

    def store_analysis(
        self,
        *,
        repository_path: str,
        repository_name: str,
        command: str,
        result_type: str,
        result_data: dict[str, Any],
        git_commit: str | None = None,
        branch: str | None = None,
        duration_ms: float = 0.0,
        status: str = "completed",
    ) -> str:
        """Store an analysis result. Returns the analysis run ID."""
        run_id = str(uuid.uuid4())

        def _persist():
            try:
                session = self._db.get_session()
                try:
                    repo = self._get_or_create_repo(session, repository_path, repository_name)
                    run = AnalysisRun(
                        id=run_id,
                        repository_id=repo.id,
                        command=command,
                        status=status,
                        git_commit=git_commit,
                        branch=branch,
                        duration_ms=duration_ms,
                        result_type=result_type,
                        result_data=result_data,
                    )
                    session.add(run)
                    session.commit()
                    self._logger.debug("Stored analysis: {} ({})", command, run_id)
                finally:
                    session.close()
            except Exception as e:  # noqa: BLE001
                self._logger.warning("Storage write failed: {}", e)

        if self._background:
            self._executor.submit(_persist)
        else:
            _persist()
        return run_id

    def store_metric(
        self,
        *,
        repository_path: str,
        repository_name: str,
        metric_name: str,
        metric_value: float,
        git_commit: str | None = None,
        branch: str | None = None,
    ) -> None:
        """Store a historical metric."""
        def _persist():
            try:
                session = self._db.get_session()
                try:
                    repo = self._get_or_create_repo(session, repository_path, repository_name)
                    metric = HistoricalMetric(
                        repository_id=repo.id,
                        metric_name=metric_name,
                        metric_value=metric_value,
                        git_commit=git_commit,
                        branch=branch,
                    )
                    session.add(metric)
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
                finally:
                    session.close()
            except Exception as e:  # noqa: BLE001
                self._logger.warning("Metric write failed: {}", e)

        if self._background:
            self._executor.submit(_persist)
        else:
            _persist()

    def get_analyses(
        self,
        repository_path: str,
        *,
        command: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get recent analyses for a repository."""
        session = self._db.get_session()
        try:
            repo = session.query(RepositoryRecord).filter_by(path=repository_path).first()
            if not repo:
                return []
            query = session.query(AnalysisRun).filter_by(repository_id=repo.id)
            if command:
                query = query.filter_by(command=command)
            runs = query.order_by(AnalysisRun.timestamp.desc()).limit(limit).all()
            return [
                {
                    "id": r.id,
                    "command": r.command,
                    "status": r.status,
                    "git_commit": r.git_commit,
                    "branch": r.branch,
                    "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                    "duration_ms": r.duration_ms,
                    "result_type": r.result_type,
                    "result_data": r.result_data,
                }
                for r in runs
            ]
        finally:
            session.close()

    def get_metrics(
        self,
        repository_path: str,
        metric_name: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get historical metric values for a repository."""
        session = self._db.get_session()
        try:
            repo = session.query(RepositoryRecord).filter_by(path=repository_path).first()
            if not repo:
                return []
            metrics = (
                session.query(HistoricalMetric)
                .filter_by(repository_id=repo.id, metric_name=metric_name)
                .order_by(HistoricalMetric.timestamp.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "value": m.metric_value,
                    "git_commit": m.git_commit,
                    "branch": m.branch,
                    "timestamp": m.timestamp.isoformat() if m.timestamp else None,
                }
                for m in metrics
            ]
        finally:
            session.close()

    def get_repositories(self) -> list[dict[str, Any]]:
        """List all tracked repositories."""
        session = self._db.get_session()
        try:
            repos = session.query(RepositoryRecord).filter_by(is_active=True).all()
            return [
                {
                    "id": r.id,
                    "name": r.name,
                    "path": r.path,
                    "remote_url": r.remote_url,
                    "default_branch": r.default_branch,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in repos
            ]
        finally:
            session.close()

    def compare_analyses(
        self,
        repository_path: str,
        command: str,
        *,
        count: int = 2,
    ) -> list[dict[str, Any]]:
        """Get analyses for comparison (e.g., current vs previous)."""
        return self.get_analyses(repository_path, command=command, limit=count)

    def shutdown(self) -> None:
        """Shutdown background executor."""
        self._executor.shutdown(wait=True)

    def _get_or_create_repo(self, session, path: str, name: str) -> RepositoryRecord:
        """Get or create a repository record."""
        repo = session.query(RepositoryRecord).filter_by(path=path).first()
        if repo is None:
            repo = RepositoryRecord(name=name, path=path)
            session.add(repo)
            session.commit()
        return repo
