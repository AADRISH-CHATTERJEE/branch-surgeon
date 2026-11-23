"""Analysis History service — persist, query, metrics, export, retention."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import or_

from refactory.api.serialize import iso_utc
from refactory.history.types import resolve_analysis_type

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.db.session import SessionFactory


class AnalysisHistoryService:
    """Historical memory of analysis results (complements Activity)."""

    def __init__(
        self,
        *,
        logger: "Logger",
        session_factory: "SessionFactory",
    ) -> None:
        self._logger = logger
        self._sessions = session_factory

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(
        self,
        *,
        repository_id: str,
        analysis_type: str | None = None,
        command: str | None = None,
        result_type: str | None = None,
        repository_name: str = "",
        branch: str | None = None,
        commit: str | None = None,
        status: str = "completed",
        duration_ms: float = 0.0,
        summary: str = "",
        created_by: str = "local",
        metadata: dict[str, Any] | None = None,
        result_data: dict[str, Any] | None = None,
        analysis_run_id: str | None = None,
        organization_id: str | None = None,
        created_by_user: str | None = None,
    ) -> dict[str, Any]:
        """Persist a history entry. Never raises to callers (best-effort)."""
        from refactory.db.uow import UnitOfWork

        atype = resolve_analysis_type(
            command=command, result_type=result_type, explicit=analysis_type
        )
        if not summary:
            summary = self._default_summary(atype, status, result_data)

        try:
            with UnitOfWork(self._sessions) as uow:
                if not repository_name:
                    repo = uow.repositories.get_by_id(repository_id)
                    repository_name = (repo.name if repo else "") or ""
                row = uow.analysis_history.create(
                    analysis_type=atype,
                    repository_id=repository_id,
                    repository_name=repository_name,
                    branch=branch,
                    commit=commit,
                    status=status,
                    duration_ms=float(duration_ms or 0.0),
                    summary=summary,
                    created_by=created_by or "local",
                    metadata_=metadata or {},
                    result_data=result_data,
                    analysis_run_id=analysis_run_id,
                    organization_id=organization_id,
                    created_by_user=created_by_user or created_by or "local",
                )
                return self._to_dict(row)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Failed to persist analysis history: {}", exc)
            return {}

    def record_from_analysis_run(
        self,
        run: dict[str, Any],
        *,
        repository_name: str = "",
        summary: str = "",
        organization_id: str | None = None,
        created_by_user: str | None = None,
    ) -> dict[str, Any]:
        """Mirror an Activity analysis_run into History."""
        meta = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
        org = organization_id or meta.get("organization_id")
        actor = created_by_user or meta.get("created_by_user")
        return self.record(
            repository_id=str(run.get("repository_id") or ""),
            command=str(run.get("command") or ""),
            result_type=str(run.get("result_type") or ""),
            repository_name=repository_name,
            branch=run.get("branch"),
            commit=run.get("git_commit"),
            status=str(run.get("status") or "completed"),
            duration_ms=float(run.get("duration_ms") or 0.0),
            summary=summary,
            metadata=meta,
            result_data=run.get("result_data")
            if isinstance(run.get("result_data"), dict)
            else None,
            analysis_run_id=str(run.get("id") or "") or None,
            organization_id=str(org) if org else None,
            created_by_user=str(actor) if actor else None,
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def list_history(
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
    ) -> list[dict[str, Any]]:
        from refactory.db.uow import UnitOfWork

        with UnitOfWork(self._sessions) as uow:
            # SQLite-friendly search
            rows = self._list_with_search(
                uow,
                repository_id=repository_id,
                analysis_type=analysis_type,
                status=status,
                branch=branch,
                search=search,
                since=since,
                until=until,
                limit=limit,
                offset=offset,
            )
            return [self._to_dict(r) for r in rows]

    def get(self, history_id: str) -> dict[str, Any] | None:
        from refactory.db.uow import UnitOfWork

        with UnitOfWork(self._sessions) as uow:
            row = uow.analysis_history.get_by_id(history_id)
            return self._to_dict(row) if row else None

    def metrics(self, *, repository_id: str | None = None) -> dict[str, Any]:
        from refactory.db.uow import UnitOfWork

        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=now.weekday())

        with UnitOfWork(self._sessions) as uow:
            total = uow.analysis_history.count_filtered(repository_id=repository_id)
            today = uow.analysis_history.count_filtered(
                repository_id=repository_id, since=today_start
            )
            week = uow.analysis_history.count_filtered(
                repository_id=repository_id, since=week_start
            )
            failures = uow.analysis_history.count_filtered(
                repository_id=repository_id, status="failed"
            )
            # Also treat error status as failure
            errors = uow.analysis_history.count_filtered(
                repository_id=repository_id, status="error"
            )
            fail_total = failures + errors
            avg = uow.analysis_history.average_duration_ms(repository_id=repository_id)
            success_rate = (
                round(((total - fail_total) / total) * 100.0, 1) if total else 100.0
            )
        return {
            "total_analyses": total,
            "today": today,
            "this_week": week,
            "average_duration_ms": round(avg, 1),
            "failures": fail_total,
            "success_rate": success_rate,
        }

    def apply_retention(
        self,
        *,
        days: int | None,
        repository_id: str | None = None,
    ) -> dict[str, Any]:
        """Delete history older than ``days``. ``None`` / 0 = unlimited (no-op)."""
        if not days or days <= 0:
            return {"deleted": 0, "retention_days": None}
        from refactory.db.uow import UnitOfWork

        cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
        with UnitOfWork(self._sessions) as uow:
            deleted = uow.analysis_history.delete_older_than(
                cutoff, repository_id=repository_id
            )
        return {"deleted": deleted, "retention_days": days, "cutoff": cutoff.isoformat()}

    def export(
        self,
        *,
        format: str = "json",
        repository_id: str | None = None,
        limit: int = 500,
    ) -> tuple[str, str]:
        """Return (content, media_type) for export."""
        rows = self.list_history(repository_id=repository_id, limit=limit)
        fmt = (format or "json").lower()
        if fmt == "csv":
            return self._export_csv(rows), "text/csv; charset=utf-8"
        if fmt == "markdown" or fmt == "md":
            return self._export_markdown(rows), "text/markdown; charset=utf-8"
        return json.dumps({"version": "1.0", "items": rows}, indent=2), (
            "application/json; charset=utf-8"
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _list_with_search(self, uow, **kwargs: Any):
        from sqlalchemy import select

        from refactory.db.models import AnalysisHistoryModel

        search = kwargs.pop("search", None)
        repository_id = kwargs.get("repository_id")
        analysis_type = kwargs.get("analysis_type")
        status = kwargs.get("status")
        branch = kwargs.get("branch")
        since = kwargs.get("since")
        until = kwargs.get("until")
        limit = kwargs.get("limit") or 100
        offset = kwargs.get("offset") or 0

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
            q = f"%{search.lower()}%"
            stmt = stmt.where(
                or_(
                    AnalysisHistoryModel.summary.ilike(q),
                    AnalysisHistoryModel.repository_name.ilike(q),
                    AnalysisHistoryModel.analysis_type.ilike(q),
                    AnalysisHistoryModel.branch.ilike(q),
                    AnalysisHistoryModel.commit.ilike(q),
                )
            )
        stmt = (
            stmt.order_by(AnalysisHistoryModel.timestamp.desc())
            .offset(offset)
            .limit(limit)
        )
        return uow.session.execute(stmt).scalars().all()

    @staticmethod
    def _default_summary(
        analysis_type: str, status: str, result_data: dict[str, Any] | None
    ) -> str:
        data = result_data or {}
        if analysis_type == "rules_evaluation":
            return str(data.get("summary") or f"Rules check: {status}")
        if analysis_type == "recommendation":
            n = data.get("total_recommendations")
            if n is not None:
                return f"Generated {n} recommendations"
            return f"Recommendations ({status})"
        if analysis_type == "review":
            return str(data.get("summary") or f"Review {status}")
        if analysis_type == "patch_generation":
            files = data.get("changed_files") or []
            return f"Patch generated ({len(files)} file(s))"
        if analysis_type == "patch_apply":
            return str(data.get("message") or f"Patch apply {status}")
        if analysis_type == "repository_graph":
            return (
                f"Graph: {data.get('nodes', '?')} nodes, {data.get('edges', '?')} edges"
            )
        if analysis_type == "index":
            return f"Index updated ({status})"
        if analysis_type == "repository_health":
            scores = data.get("scores") or {}
            overall = scores.get("overall")
            return f"Health score {overall}" if overall is not None else f"Health {status}"
        if analysis_type == "branch_surgeon":
            return str(data.get("summary") or f"Branch Surgeon {status}")
        if analysis_type == "transform":
            return str(data.get("description") or f"Transform {status}")
        if analysis_type == "organization_admin":
            return str(data.get("summary") or data.get("message") or f"Organization admin ({status})")
        if analysis_type == "organization_rule":
            name = data.get("name") or data.get("rule_id") or "rule"
            return str(data.get("summary") or f"Organization rule: {name}")
        return f"{analysis_type.replace('_', ' ').title()} ({status})"

    @staticmethod
    def _to_dict(row: Any) -> dict[str, Any]:
        meta = row.metadata_ or {}
        return {
            "id": row.id,
            "timestamp": iso_utc(row.timestamp),
            "analysis_type": row.analysis_type,
            "repository_id": row.repository_id,
            "repository": row.repository_name or "",
            "repository_name": row.repository_name or "",
            "branch": row.branch,
            "commit": row.commit,
            "status": row.status,
            "duration_ms": row.duration_ms or 0.0,
            "summary": row.summary or "",
            "created_by": row.created_by or "local",
            "metadata": meta,
            "result_data": row.result_data,
            "analysis_run_id": row.analysis_run_id,
            "organization_id": getattr(row, "organization_id", None),
            "created_by_user": getattr(row, "created_by_user", None)
            or row.created_by
            or "local",
            "deep_link": _deep_link(row.analysis_type, row.result_data or {}, meta),
        }

    @staticmethod
    def _export_csv(rows: list[dict[str, Any]]) -> str:
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf,
            fieldnames=[
                "id",
                "timestamp",
                "analysis_type",
                "repository",
                "branch",
                "commit",
                "status",
                "duration_ms",
                "summary",
                "created_by",
            ],
        )
        writer.writeheader()
        for r in rows:
            writer.writerow(
                {
                    "id": r.get("id"),
                    "timestamp": r.get("timestamp"),
                    "analysis_type": r.get("analysis_type"),
                    "repository": r.get("repository") or r.get("repository_name"),
                    "branch": r.get("branch"),
                    "commit": r.get("commit"),
                    "status": r.get("status"),
                    "duration_ms": r.get("duration_ms"),
                    "summary": r.get("summary"),
                    "created_by": r.get("created_by"),
                }
            )
        return buf.getvalue()

    @staticmethod
    def _export_markdown(rows: list[dict[str, Any]]) -> str:
        lines = [
            "# Analysis History",
            "",
            f"Exported {len(rows)} item(s).",
            "",
        ]
        for r in rows:
            lines.append(f"## {r.get('analysis_type')} — {r.get('timestamp')}")
            lines.append("")
            lines.append(f"- **Repository:** {r.get('repository') or '—'}")
            lines.append(f"- **Branch:** {r.get('branch') or '—'}")
            lines.append(f"- **Commit:** {r.get('commit') or '—'}")
            lines.append(f"- **Status:** {r.get('status')}")
            lines.append(f"- **Duration:** {r.get('duration_ms')} ms")
            lines.append(f"- **Summary:** {r.get('summary')}")
            lines.append("")
        return "\n".join(lines)


def _deep_link(
    analysis_type: str, result_data: dict[str, Any], metadata: dict[str, Any]
) -> dict[str, str] | None:
    if analysis_type == "review":
        rid = result_data.get("id") or metadata.get("review_id")
        href = f"/reviews?id={rid}" if rid else "/reviews"
        return {"href": href, "label": "Open Review"}
    if analysis_type == "recommendation":
        return {"href": "/recommendations", "label": "Open Recommendation"}
    if analysis_type == "branch_surgeon":
        return {"href": "/surgeon", "label": "Open Surgeon"}
    if analysis_type == "repository_graph":
        return {"href": "/repository/graph", "label": "Open Graph"}
    if analysis_type == "repository_health":
        return {"href": "/repository/health", "label": "Open Health"}
    if analysis_type == "rules_evaluation":
        return {"href": "/rules", "label": "Open Rules"}
    if analysis_type in {"patch_generation", "patch_apply"}:
        return {"href": "/recommendations", "label": "Open Recommendations"}
    if analysis_type == "transform":
        return {"href": "/transform", "label": "Open Transform"}
    if analysis_type == "index":
        return {"href": "/repository", "label": "Open Repository"}
    if analysis_type == "organization_admin":
        org = result_data.get("organization_id") or metadata.get("organization_id")
        href = f"/organization?org={org}" if org else "/organization"
        return {"href": href, "label": "Open Organization"}
    if analysis_type == "organization_rule":
        return {"href": "/rules", "label": "Open Rules"}
    return None
