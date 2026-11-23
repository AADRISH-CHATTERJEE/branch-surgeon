"""Persistence facade — bridges ORM repositories with business-layer services.

This module provides `PersistenceService`, which wraps the UnitOfWork
and repositories in a high-level API that existing services can call
without needing to know about SQLAlchemy sessions or ORM models.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Sequence

from refactory.api.serialize import iso_utc
from refactory.db.models import (
    AnalysisRunModel,
    EmbeddingModel,
    FileModel,
    GraphEdgeModel,
    GraphNodeModel,
    ImportModel,
    MetricModel,
    PatchModel,
    RecommendationModel,
    RepositoryModel,
    ReviewModel,
    ReviewSuggestionModel,
    SymbolModel,
)
from refactory.db.uow import UnitOfWork

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.db.session import SessionFactory


class PersistenceService:
    """High-level persistence API for Refactory services.

    Wraps ORM repositories and UnitOfWork behind a clean, domain-oriented
    interface that existing services can call without any SQLAlchemy knowledge.
    """

    def __init__(self, session_factory: SessionFactory, *, logger: "Logger | None" = None) -> None:
        self._sf = session_factory
        self._logger = logger
        self._history_service: Any = None

    def unit_of_work(self) -> UnitOfWork:
        """Create a new UnitOfWork context manager."""
        return UnitOfWork(self._sf)

    # ------------------------------------------------------------------
    # Repository
    # ------------------------------------------------------------------

    def get_or_create_repository(
        self,
        *,
        name: str,
        root_path: str,
        default_branch: str = "main",
        remote_url: str | None = None,
    ) -> dict[str, Any]:
        """Get or create a repository record, returning a plain dict."""
        with self.unit_of_work() as uow:
            repo = uow.repositories.get_or_create(
                name=name,
                root_path=root_path,
                default_branch=default_branch,
                remote_url=remote_url,
            )
            return self._repo_to_dict(repo)

    def list_repositories(self) -> list[dict[str, Any]]:
        with self.unit_of_work() as uow:
            repos = uow.repositories.list_active()
            return [self._repo_to_dict(r) for r in repos]

    # ------------------------------------------------------------------
    # File
    # ------------------------------------------------------------------

    def persist_file(
        self,
        *,
        repository_id: str,
        path: str,
        language: str = "unknown",
        sha256: str | None = None,
        size: int = 0,
    ) -> dict[str, Any]:
        with self.unit_of_work() as uow:
            f = uow.files.upsert(
                repository_id=repository_id,
                path=path,
                language=language,
                sha256=sha256,
                size=size,
                last_indexed=datetime.now(timezone.utc),
            )
            return self._file_to_dict(f)

    def persist_files_bulk(
        self,
        repository_id: str,
        files: list[dict[str, Any]],
    ) -> int:
        """Bulk-persist file records. Returns count persisted."""
        with self.unit_of_work() as uow:
            for fdata in files:
                uow.files.upsert(
                    repository_id=repository_id,
                    path=fdata["path"],
                    language=fdata.get("language", "unknown"),
                    sha256=fdata.get("sha256"),
                    size=fdata.get("size", 0),
                    last_indexed=datetime.now(timezone.utc),
                )
        return len(files)

    # ------------------------------------------------------------------
    # Symbols & Imports
    # ------------------------------------------------------------------

    def persist_symbols(
        self, file_id: str, symbols: list[dict[str, Any]]
    ) -> int:
        with self.unit_of_work() as uow:
            uow.symbols.delete_by_file(file_id)
            uow.symbols.bulk_insert([{**s, "file_id": file_id} for s in symbols])
        return len(symbols)

    def persist_imports(
        self, file_id: str, imports: list[dict[str, Any]]
    ) -> int:
        with self.unit_of_work() as uow:
            uow.imports.delete_by_file(file_id)
            uow.imports.bulk_insert([{**i, "file_id": file_id} for i in imports])
        return len(imports)

    # ------------------------------------------------------------------
    # Review
    # ------------------------------------------------------------------

    def persist_review(
        self,
        *,
        repository_id: str,
        pr_number: int | None = None,
        provider: str | None = None,
        model: str | None = None,
        risk: str = "unknown",
        confidence: float = 0.0,
        summary: str = "",
        suggestions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        with self.unit_of_work() as uow:
            review = uow.reviews.create(
                repository_id=repository_id,
                pr_number=pr_number,
                provider=provider,
                model=model,
                risk=risk,
                confidence=confidence,
                summary=summary,
            )
            if suggestions:
                allowed = {
                    "file",
                    "line",
                    "severity",
                    "category",
                    "title",
                    "explanation",
                    "suggested_fix",
                    "confidence",
                    "estimated_impact",
                    "status",
                    "recommendation_id",
                }
                for s in suggestions:
                    payload = {k: v for k, v in s.items() if k in allowed}
                    payload.setdefault("status", "pending")
                    uow.review_suggestions.create(review_id=review.id, **payload)
            return self._review_to_dict(review)

    def get_reviews(
        self, repository_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self.unit_of_work() as uow:
            reviews = uow.reviews.list_by_repository(repository_id, limit=limit)
            return [self._review_to_dict(r) for r in reviews]

    # ------------------------------------------------------------------
    # Recommendation
    # ------------------------------------------------------------------

    def persist_recommendations(
        self,
        repository_id: str,
        recommendations: list[dict[str, Any]],
    ) -> int:
        with self.unit_of_work() as uow:
            uow.recommendations.bulk_insert(
                [{**r, "repository_id": repository_id} for r in recommendations]
            )
        return len(recommendations)

    def reconcile_recommendations(
        self,
        repository_id: str,
        recommendations: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Reconcile persisted rows with a freshly generated set.

        - Still present → ``pending`` (clear ``resolved_at``); ignored/rejected kept
        - Missing from new set → ``resolved`` + ``resolved_at=now``
        - New → insert ``pending`` with ``created_at=now``
        """
        now = datetime.now(timezone.utc)
        preserve_status = frozenset({"ignored", "rejected", "deferred"})
        created = 0
        reopened = 0
        resolved = 0
        unchanged = 0

        with self.unit_of_work() as uow:
            existing = list(
                uow.recommendations.list_all_for_repository(repository_id)
            )
            by_id = {str(r.id): r for r in existing}
            by_key = {(str(r.type), str(r.title)): r for r in existing}

            seen_row_ids: set[str] = set()
            active_keys: set[tuple[str, str]] = set()
            for payload in recommendations:
                rid = str(payload.get("id") or "").strip()
                rtype = str(payload.get("type") or "")
                title = str(payload.get("title") or "")
                key = (rtype, title)
                active_keys.add(key)
                row = by_id.get(rid) if rid else None
                if row is None:
                    row = by_key.get(key)

                enrich = {
                    "reasoning": str(payload.get("reasoning") or ""),
                    "affected_files": list(payload.get("affected_files") or []),
                    "impact": list(payload.get("impact") or []),
                    "effort": str(payload.get("effort") or ""),
                    "confidence": payload.get("confidence"),
                    "verification_status": str(
                        payload.get("verification_status") or "unverified"
                    ),
                }

                if row is None:
                    kwargs: dict[str, Any] = {
                        "repository_id": repository_id,
                        "type": rtype,
                        "priority": str(payload.get("priority") or "medium"),
                        "title": title,
                        "description": str(payload.get("description") or ""),
                        "status": "pending",
                        "resolved_at": None,
                        "ignored_at": None,
                        "updated_at": now,
                        **enrich,
                    }
                    if rid:
                        kwargs["id"] = rid
                    created_row = uow.recommendations.create(**kwargs)
                    seen_row_ids.add(str(created_row.id))
                    created += 1
                    continue

                seen_row_ids.add(str(row.id))
                prior = str(row.status or "pending")
                if prior in preserve_status:
                    uow.recommendations.update(
                        row.id,
                        type=rtype,
                        priority=str(payload.get("priority") or "medium"),
                        title=title,
                        description=str(payload.get("description") or ""),
                        updated_at=now,
                        **enrich,
                    )
                    unchanged += 1
                    continue

                uow.recommendations.update(
                    row.id,
                    type=rtype,
                    priority=str(payload.get("priority") or "medium"),
                    title=title,
                    description=str(payload.get("description") or ""),
                    status="pending",
                    resolved_at=None,
                    ignored_at=None,
                    updated_at=now,
                    **enrich,
                )
                if prior == "pending":
                    unchanged += 1
                else:
                    reopened += 1

            for row in existing:
                rid = str(row.id)
                key = (str(row.type), str(row.title))
                if rid in seen_row_ids or key in active_keys:
                    continue
                if str(row.status or "") in {"resolved", "applied", "completed", "accepted", "implemented"}:
                    unchanged += 1
                    continue
                uow.recommendations.update(
                    row.id,
                    status="resolved",
                    resolved_at=now,
                )
                resolved += 1

        return {
            "created": created,
            "reopened": reopened,
            "resolved": resolved,
            "unchanged": unchanged,
            "active": len(recommendations),
        }

    def get_recommendations(
        self,
        repository_id: str,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self.unit_of_work() as uow:
            recs = uow.recommendations.list_by_repository(
                repository_id, status=status, limit=limit
            )
            return [self._rec_to_dict(r) for r in recs]

    # ------------------------------------------------------------------
    # Recommendation patches
    # ------------------------------------------------------------------

    def persist_recommendation_patch(
        self,
        *,
        repository_id: str,
        recommendation_id: str,
        payload: dict[str, Any],
    ) -> str:
        """Persist a generated patch; returns the new patch id."""
        with self.unit_of_work() as uow:
            row = uow.patches.create(
                repository_id=repository_id,
                recommendation_id=recommendation_id,
                explanation=payload.get("explanation") or "",
                confidence=float(payload.get("confidence") or 0.0),
                changed_files=payload.get("changed_files") or [],
                unified_diff=payload.get("unified_diff") or "",
                patches=payload.get("patches") or [],
                prompt_version=payload.get("prompt_version") or "",
                model=payload.get("model") or "",
                provider=payload.get("provider") or "",
                status="generated",
            )
            return row.id

    def get_patches_for_recommendation(
        self, recommendation_id: str, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        with self.unit_of_work() as uow:
            rows = uow.patches.list_by_recommendation(recommendation_id, limit=limit)
            return [self._patch_to_dict(r) for r in rows]

    def get_recommendation_patch(self, patch_id: str) -> dict[str, Any] | None:
        with self.unit_of_work() as uow:
            row = uow.patches.get_by_id(patch_id)
            if row is None:
                return None
            return self._patch_to_dict(row)

    def get_recommendation(self, recommendation_id: str) -> dict[str, Any] | None:
        with self.unit_of_work() as uow:
            row = uow.recommendations.get_by_id(recommendation_id)
            if row is None:
                return None
            return self._rec_to_dict(row)

    def update_recommendation_status(
        self,
        recommendation_id: str,
        status: str,
        *,
        updated_by: str | None = None,
        resolution_notes: str | None = None,
        verification_status: str | None = None,
    ) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        values: dict[str, Any] = {"status": status, "updated_at": now}
        if updated_by is not None:
            values["updated_by"] = updated_by
        if resolution_notes is not None:
            values["resolution_notes"] = resolution_notes
        if verification_status is not None:
            values["verification_status"] = verification_status
        if status == "resolved":
            values["resolved_at"] = now
            values["ignored_at"] = None
            values.setdefault("verification_status", "verified")
        elif status == "ignored":
            values["ignored_at"] = now
            values["resolved_at"] = None
        elif status == "applied":
            # Applied = patch landed; keep resolved_at clear until verified.
            values["resolved_at"] = None
            values["ignored_at"] = None
            values.setdefault("verification_status", "unverified")
        elif status == "pending":
            values["resolved_at"] = None
            values["ignored_at"] = None
            values.setdefault("verification_status", "unverified")
        elif status in {"completed", "accepted", "implemented"}:
            values["resolved_at"] = now
            values["ignored_at"] = None
        with self.unit_of_work() as uow:
            row = uow.recommendations.update(recommendation_id, **values)
            if row is None:
                return None
            return self._rec_to_dict(row)

    def get_review_suggestion(
        self, suggestion_id: str
    ) -> dict[str, Any] | None:
        with self.unit_of_work() as uow:
            row = uow.review_suggestions.get_by_id(suggestion_id)
            if row is None:
                return None
            return self._suggestion_to_dict(row)

    def update_review_suggestion_status(
        self,
        suggestion_id: str,
        status: str,
        *,
        updated_by: str | None = None,
        recommendation_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Set suggestion lifecycle status and timestamps."""
        now = datetime.now(timezone.utc)
        values: dict[str, Any] = {
            "status": status,
            "updated_at": now,
        }
        if updated_by is not None:
            values["updated_by"] = updated_by
        if recommendation_id is not None:
            values["recommendation_id"] = recommendation_id
        if status == "resolved":
            values["resolved_at"] = now
            values["ignored_at"] = None
        elif status == "ignored":
            values["ignored_at"] = now
            values["resolved_at"] = None
        elif status == "pending":
            values["resolved_at"] = None
            values["ignored_at"] = None
        with self.unit_of_work() as uow:
            row = uow.review_suggestions.update(suggestion_id, **values)
            if row is None:
                return None
            return self._suggestion_to_dict(row)

    def list_pending_review_suggestions(
        self, repository_id: str, *, limit: int = 5_000
    ) -> list[dict[str, Any]]:
        with self.unit_of_work() as uow:
            rows = uow.review_suggestions.list_pending_for_repository(
                repository_id, limit=limit
            )
            return [self._suggestion_to_dict(r) for r in rows]

    def update_recommendation_fields(
        self, recommendation_id: str, **fields: Any
    ) -> dict[str, Any] | None:
        """Update arbitrary recommendation columns (status, priority, …)."""
        allowed = {
            "status",
            "priority",
            "title",
            "description",
            "type",
            "reasoning",
            "affected_files",
            "impact",
            "effort",
            "confidence",
            "resolution_notes",
            "verification_status",
            "patch_history",
            "updated_at",
            "resolved_at",
            "ignored_at",
            "updated_by",
        }
        values = {k: v for k, v in fields.items() if k in allowed}
        if not values:
            return self.get_recommendation(recommendation_id)
        if "updated_at" not in values:
            values["updated_at"] = datetime.now(timezone.utc)
        with self.unit_of_work() as uow:
            row = uow.recommendations.update(recommendation_id, **values)
            if row is None:
                return None
            return self._rec_to_dict(row)

    def delete_recommendation(self, recommendation_id: str) -> bool:
        with self.unit_of_work() as uow:
            return bool(uow.recommendations.delete(recommendation_id))

    def mark_patch_applied(
        self,
        patch_id: str,
        *,
        applied_by: str,
        git_commit: str | None,
        applied_at: Any = None,
    ) -> dict[str, Any] | None:
        from datetime import datetime, timezone

        ts = applied_at or datetime.now(timezone.utc)
        with self.unit_of_work() as uow:
            row = uow.patches.mark_applied(
                patch_id,
                applied_by=applied_by,
                git_commit=git_commit,
                applied_at=ts,
            )
            return self._patch_to_dict(row) if row else None

    def mark_patch_failed(
        self, patch_id: str, *, failure_reason: str, status: str = "failed"
    ) -> dict[str, Any] | None:
        with self.unit_of_work() as uow:
            row = uow.patches.mark_failed(
                patch_id, failure_reason=failure_reason, status=status
            )
            return self._patch_to_dict(row) if row else None

    def mark_patch_rolled_back(
        self,
        patch_id: str,
        *,
        rollback_metadata: dict[str, Any] | None = None,
        failure_reason: str | None = None,
    ) -> dict[str, Any] | None:
        with self.unit_of_work() as uow:
            row = uow.patches.mark_rolled_back(
                patch_id,
                rollback_metadata=rollback_metadata,
                failure_reason=failure_reason,
            )
            return self._patch_to_dict(row) if row else None

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def persist_embeddings(
        self, file_id: str, embeddings: list[dict[str, Any]]
    ) -> int:
        with self.unit_of_work() as uow:
            uow.embeddings.delete_by_file(file_id)
            uow.embeddings.bulk_insert([{**e, "file_id": file_id} for e in embeddings])
        return len(embeddings)

    # ------------------------------------------------------------------
    # Graph
    # ------------------------------------------------------------------

    def persist_graph(
        self,
        repository_id: str,
        *,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> dict[str, int]:
        with self.unit_of_work() as uow:
            uow.graph.delete_graph(repository_id)
            created_nodes = uow.graph.bulk_insert_nodes(
                [{**n, "repository_id": repository_id} for n in nodes]
            )
            node_id_map = {n.name: n.id for n in created_nodes}
            mapped_edges = []
            for e in edges:
                mapped = dict(e)
                if "source_name" in mapped:
                    mapped["source_node"] = node_id_map.get(mapped.pop("source_name"), mapped.get("source_node", ""))
                if "target_name" in mapped:
                    mapped["target_node"] = node_id_map.get(mapped.pop("target_name"), mapped.get("target_node", ""))
                if "relationship" in mapped:
                    mapped["relationship_"] = mapped.pop("relationship")
                mapped_edges.append(mapped)
            uow.graph.bulk_insert_edges(mapped_edges)
        return {"nodes": len(nodes), "edges": len(edges)}

    # ------------------------------------------------------------------
    # Metric
    # ------------------------------------------------------------------

    def persist_metric(
        self,
        *,
        repository_id: str,
        metric_name: str,
        metric_value: float,
        git_commit: str | None = None,
        branch: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist a single historical metric data point."""
        with self.unit_of_work() as uow:
            m = uow.metrics.create(
                repository_id=repository_id,
                metric_name=metric_name,
                metric_value=metric_value,
                git_commit=git_commit,
                branch=branch,
                metadata_=metadata,
            )
            return self._metric_to_dict(m)

    def persist_metrics_bulk(
        self,
        repository_id: str,
        metrics: list[dict[str, Any]],
    ) -> int:
        """Bulk-persist metric records. Returns count persisted."""
        with self.unit_of_work() as uow:
            uow.metrics.bulk_insert(
                [{**m, "repository_id": repository_id} for m in metrics]
            )
        return len(metrics)

    # ------------------------------------------------------------------
    # AnalysisRun
    # ------------------------------------------------------------------

    def persist_analysis_run(
        self,
        *,
        repository_id: str,
        command: str,
        result_type: str,
        status: str = "completed",
        git_commit: str | None = None,
        branch: str | None = None,
        duration_ms: float = 0.0,
        result_data: dict[str, Any] | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
        summary: str = "",
        organization_id: str | None = None,
        created_by_user: str | None = None,
    ) -> dict[str, Any]:
        """Persist a single analysis run record and mirror into analysis_history."""
        meta = dict(metadata or {})
        if organization_id:
            meta.setdefault("organization_id", organization_id)
        if created_by_user:
            meta.setdefault("created_by_user", created_by_user)
        with self.unit_of_work() as uow:
            run = uow.analysis_runs.create(
                repository_id=repository_id,
                command=command,
                status=status,
                git_commit=git_commit,
                branch=branch,
                duration_ms=duration_ms,
                result_type=result_type,
                result_data=result_data,
                error_message=error_message,
                metadata_=meta or None,
            )
            out = self._run_to_dict(run)

        # Automatic History storage (best-effort; never breaks Activity write)
        history = getattr(self, "_history_service", None)
        if history is not None:
            try:
                history.record_from_analysis_run(
                    out,
                    summary=summary,
                    organization_id=organization_id,
                    created_by_user=created_by_user,
                )
            except Exception:  # noqa: BLE001
                pass
        return out

    def set_history_service(self, history_service: Any) -> None:
        """Wire AnalysisHistoryService after construction (container bootstrap)."""
        self._history_service = history_service

    # ------------------------------------------------------------------
    # Converters (ORM -> dict)
    # ------------------------------------------------------------------

    @staticmethod
    def _repo_to_dict(repo: RepositoryModel) -> dict[str, Any]:
        return {
            "id": repo.id,
            "name": repo.name,
            "root_path": repo.root_path,
            "default_branch": repo.default_branch,
            "remote_url": repo.remote_url,
            "created_at": iso_utc(repo.created_at),
            "updated_at": iso_utc(repo.updated_at),
        }

    @staticmethod
    def _file_to_dict(f: FileModel) -> dict[str, Any]:
        return {
            "id": f.id,
            "repository_id": f.repository_id,
            "path": f.path,
            "language": f.language,
            "sha256": f.sha256,
            "size": f.size,
            "last_indexed": iso_utc(f.last_indexed),
        }

    @staticmethod
    def _review_to_dict(r: ReviewModel) -> dict[str, Any]:
        return {
            "id": r.id,
            "repository_id": r.repository_id,
            "pr_number": r.pr_number,
            "provider": r.provider,
            "model": r.model,
            "risk": r.risk,
            "confidence": r.confidence,
            "summary": r.summary,
            "created_at": iso_utc(r.created_at),
        }

    @staticmethod
    def _suggestion_to_dict(s: ReviewSuggestionModel) -> dict[str, Any]:
        return {
            "id": s.id,
            "review_id": s.review_id,
            "file": s.file,
            "line": s.line,
            "severity": s.severity,
            "category": s.category,
            "title": s.title,
            "explanation": s.explanation,
            "suggested_fix": s.suggested_fix,
            "confidence": s.confidence,
            "estimated_impact": s.estimated_impact,
            "status": getattr(s, "status", None) or "pending",
            "created_at": iso_utc(
                getattr(s, "created_at", None) or getattr(s, "updated_at", None)
            ),
            "updated_at": iso_utc(getattr(s, "updated_at", None)),
            "resolved_at": iso_utc(getattr(s, "resolved_at", None)),
            "ignored_at": iso_utc(getattr(s, "ignored_at", None)),
            "updated_by": getattr(s, "updated_by", None),
            "recommendation_id": getattr(s, "recommendation_id", None),
        }

    @staticmethod
    def _rec_to_dict(r: RecommendationModel) -> dict[str, Any]:
        affected = getattr(r, "affected_files", None) or []
        impact = getattr(r, "impact", None) or []
        return {
            "id": r.id,
            "repository_id": r.repository_id,
            "type": r.type,
            "priority": r.priority,
            "status": r.status,
            "title": r.title,
            "description": r.description,
            "reasoning": getattr(r, "reasoning", None) or "",
            "affected_files": list(affected) if isinstance(affected, list) else [],
            "impact": list(impact) if isinstance(impact, list) else [],
            "effort": getattr(r, "effort", None) or "",
            "confidence": getattr(r, "confidence", None),
            "resolution_notes": getattr(r, "resolution_notes", None) or "",
            "verification_status": getattr(r, "verification_status", None)
            or "unverified",
            "patch_history": getattr(r, "patch_history", None) or [],
            "created_at": iso_utc(r.created_at),
            "updated_at": iso_utc(getattr(r, "updated_at", None)),
            "resolved_at": iso_utc(getattr(r, "resolved_at", None)),
            "ignored_at": iso_utc(getattr(r, "ignored_at", None)),
            "updated_by": getattr(r, "updated_by", None),
        }

    @staticmethod
    def _patch_to_dict(p: PatchModel) -> dict[str, Any]:
        status = getattr(p, "status", None) or "generated"
        return {
            "id": p.id,
            "recommendation_id": p.recommendation_id,
            "repository_id": p.repository_id,
            "explanation": p.explanation or "",
            "confidence": p.confidence or 0.0,
            "changed_files": p.changed_files or [],
            "unified_diff": p.unified_diff or "",
            "patches": p.patches or [],
            "prompt_version": p.prompt_version or "",
            "model": p.model or "",
            "provider": p.provider or "",
            "created_at": iso_utc(p.created_at),
            "status": status,
            "applied_at": iso_utc(getattr(p, "applied_at", None)),
            "applied_by": getattr(p, "applied_by", None),
            "git_commit": getattr(p, "git_commit", None),
            "failure_reason": getattr(p, "failure_reason", None),
            "rollback_metadata": getattr(p, "rollback_metadata", None) or {},
            "apply_available": status in {"generated", "failed", "rolled_back"},
        }

    @staticmethod
    def _metric_to_dict(m: MetricModel) -> dict[str, Any]:
        return {
            "id": m.id,
            "repository_id": m.repository_id,
            "metric_name": m.metric_name,
            "metric_value": m.metric_value,
            "git_commit": m.git_commit,
            "branch": m.branch,
            "created_at": iso_utc(m.created_at),
            "metadata": m.metadata_,
        }

    @staticmethod
    def _run_to_dict(r: AnalysisRunModel) -> dict[str, Any]:
        return {
            "id": r.id,
            "repository_id": r.repository_id,
            "command": r.command,
            "status": r.status,
            "git_commit": r.git_commit,
            "branch": r.branch,
            "duration_ms": r.duration_ms,
            "result_type": r.result_type,
            "result_data": r.result_data,
            "error_message": r.error_message,
            "created_at": iso_utc(r.created_at),
            "metadata": r.metadata_,
        }
