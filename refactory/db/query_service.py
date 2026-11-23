"""RepositoryQueryService — read-only abstraction over the persistence layer.

Provides a clean, domain-oriented read API that decouples consumers from
SQLAlchemy ORM models. All methods are pure read operations — no writes,
no commits, no side effects beyond session management.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence

from refactory.api.serialize import iso_utc
from refactory.db.uow import UnitOfWork

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.db.session import SessionFactory


class RepositoryQueryService:
    """Read-only query layer over the Refactory relational database.

    Uses UnitOfWork internally for session management but never performs
    writes. Returns plain Python dictionaries to keep callers independent
    from SQLAlchemy models.
    """

    def __init__(self, session_factory: "SessionFactory", *, logger: "Logger | None" = None) -> None:
        self._sf = session_factory
        self._logger = logger

    def _uow(self) -> UnitOfWork:
        return UnitOfWork(self._sf)

    # ------------------------------------------------------------------
    # Repository queries
    # ------------------------------------------------------------------

    def get_repository(self, repository_id: str) -> dict[str, Any] | None:
        """Get a repository by its primary key."""
        with self._uow() as uow:
            repo = uow.repositories.get_by_id(repository_id)
            if repo is None:
                return None
            return self._repo_to_dict(repo)

    def get_repository_by_name(self, name: str) -> dict[str, Any] | None:
        """Get a repository by name."""
        with self._uow() as uow:
            repo = uow.repositories.get(name=name)
            if repo is None:
                return None
            return self._repo_to_dict(repo)

    def get_repository_by_root(self, root_path: str) -> dict[str, Any] | None:
        """Get a repository by filesystem root path."""
        with self._uow() as uow:
            repo = uow.repositories.get_by_root_path(root_path)
            if repo is None:
                return None
            return self._repo_to_dict(repo)

    def list_repositories(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """List all active repositories."""
        with self._uow() as uow:
            repos = uow.repositories.list_active(limit=limit)
            return [self._repo_to_dict(r) for r in repos]

    # ------------------------------------------------------------------
    # File queries
    # ------------------------------------------------------------------

    def get_files(self, repository_id: str, *, language: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        """List files in a repository, optionally filtered by language."""
        with self._uow() as uow:
            files = uow.files.list_by_repository(repository_id, language=language, limit=limit)
            return [self._file_to_dict(f) for f in files]

    def get_file(self, repository_id: str, path: str) -> dict[str, Any] | None:
        """Get a single file by repository and relative path."""
        with self._uow() as uow:
            f = uow.files.get_by_repo_path(repository_id, path)
            if f is None:
                return None
            return self._file_to_dict(f)

    # ------------------------------------------------------------------
    # Symbol & Import queries
    # ------------------------------------------------------------------

    def get_symbols(self, file_id: str) -> list[dict[str, Any]]:
        """List all symbols in a file."""
        with self._uow() as uow:
            symbols = uow.symbols.list_by_file(file_id)
            return [self._symbol_to_dict(s) for s in symbols]

    def get_imports(self, file_id: str) -> list[dict[str, Any]]:
        """List all imports in a file."""
        with self._uow() as uow:
            imports = uow.imports.list_by_file(file_id)
            return [self._import_to_dict(i) for i in imports]

    # ------------------------------------------------------------------
    # Review queries
    # ------------------------------------------------------------------

    def get_latest_review(self, repository_id: str) -> dict[str, Any] | None:
        """Get the most recent review for a repository."""
        with self._uow() as uow:
            review = uow.reviews.get_latest(repository_id)
            if review is None:
                return None
            suggestions = uow.review_suggestions.list_by_review(review.id)
            return self._review_to_dict(review, suggestions=suggestions)

    def get_review(self, review_id: str) -> dict[str, Any] | None:
        """Get a review by its primary key."""
        with self._uow() as uow:
            review = uow.reviews.get_by_id(review_id)
            if review is None:
                return None
            suggestions = uow.review_suggestions.list_by_review(review.id)
            return self._review_to_dict(review, suggestions=suggestions)

    def get_reviews(self, repository_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """List reviews for a repository, most recent first.

        Includes denormalized suggestion stats (counts) so History/list UIs
        match detail without embedding full suggestion payloads.
        """
        with self._uow() as uow:
            reviews = list(uow.reviews.list_by_repository(repository_id, limit=limit))
            ids = [r.id for r in reviews]
            all_suggestions = uow.review_suggestions.list_by_review_ids(ids)
            by_review: dict[str, list] = {rid: [] for rid in ids}
            for s in all_suggestions:
                by_review.setdefault(s.review_id, []).append(s)
            return [
                self._review_to_dict(r, suggestions=by_review.get(r.id, []))
                for r in reviews
            ]

    def get_review_suggestions(self, review_id: str) -> list[dict[str, Any]]:
        """List all suggestions for a review."""
        with self._uow() as uow:
            suggestions = uow.review_suggestions.list_by_review(review_id)
            return [self._suggestion_to_dict(s) for s in suggestions]

    # ------------------------------------------------------------------
    # Recommendation queries
    # ------------------------------------------------------------------

    def get_recommendations(
        self,
        repository_id: str,
        *,
        status: str | None = None,
        priority: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List recommendations for a repository with optional filters."""
        with self._uow() as uow:
            recs = uow.recommendations.list_by_repository(
                repository_id, status=status, priority=priority, limit=limit
            )
            return [self._rec_to_dict(r) for r in recs]

    def count_recommendations(
        self,
        repository_id: str,
        *,
        status: str | None = None,
        priority: str | None = None,
    ) -> int:
        """Count persisted recommendations (not capped by list limit).

        Prefer ``aggregate_recommendations`` / RecommendationStatsService for
        dashboard totals — this helper remains for narrow filtered checks.
        """
        with self._uow() as uow:
            return uow.recommendations.count_by_repository(
                repository_id, status=status, priority=priority
            )

    def aggregate_recommendations(self, repository_id: str) -> dict[str, Any]:
        """GROUP BY priority/status/type aggregates for RecommendationStatsService."""
        with self._uow() as uow:
            return uow.recommendations.aggregate_by_repository(repository_id)

    def get_recommendation(self, recommendation_id: str) -> dict[str, Any] | None:
        """Get a single persisted recommendation by id."""
        with self._uow() as uow:
            rec = uow.recommendations.get_by_id(recommendation_id)
            if rec is None:
                return None
            return self._rec_to_dict(rec)

    def get_patches_for_recommendation(
        self, recommendation_id: str, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        """List persisted AI patches for a recommendation (newest first)."""
        with self._uow() as uow:
            rows = uow.patches.list_by_recommendation(recommendation_id, limit=limit)
            return [self._patch_to_dict(r) for r in rows]

    def get_recommendation_patch(self, patch_id: str) -> dict[str, Any] | None:
        """Get a single persisted patch by id."""
        with self._uow() as uow:
            row = uow.patches.get_by_id(patch_id)
            if row is None:
                return None
            return self._patch_to_dict(row)

    # ------------------------------------------------------------------
    # Graph queries
    # ------------------------------------------------------------------

    def get_graph(self, repository_id: str) -> dict[str, Any]:
        """Get the complete graph (nodes + edges) for a repository."""
        with self._uow() as uow:
            nodes = uow.graph.list_nodes(repository_id, limit=100000)
            node_list = [self._node_to_dict(n) for n in nodes]
            edge_list: list[dict[str, Any]] = []
            for node in nodes:
                for edge in uow.graph.list_edges_outgoing(node.id):
                    edge_list.append(self._edge_to_dict(edge))
            return {
                "repository_id": repository_id,
                "nodes": node_list,
                "edges": edge_list,
                "node_count": len(node_list),
                "edge_count": len(edge_list),
            }

    def get_graph_nodes(self, repository_id: str, *, node_type: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        """List graph nodes for a repository, optionally filtered by type."""
        with self._uow() as uow:
            nodes = uow.graph.list_nodes(repository_id, node_type=node_type, limit=limit)
            return [self._node_to_dict(n) for n in nodes]

    def get_graph_edges(self, repository_id: str) -> list[dict[str, Any]]:
        """List all graph edges for a repository."""
        with self._uow() as uow:
            nodes = uow.graph.list_nodes(repository_id, limit=100000)
            edges: list[dict[str, Any]] = []
            for node in nodes:
                for edge in uow.graph.list_edges_outgoing(node.id):
                    edges.append(self._edge_to_dict(edge))
            return edges

    def get_graph_node(self, node_id: str) -> dict[str, Any] | None:
        """Get a graph node with its incoming/outgoing edges."""
        with self._uow() as uow:
            node = uow.graph.get_node_by_id(node_id)
            if node is None:
                return None
            outgoing = [self._edge_to_dict(e) for e in uow.graph.list_edges_outgoing(node_id)]
            incoming = [self._edge_to_dict(e) for e in uow.graph.list_edges_incoming(node_id)]
            return {
                **self._node_to_dict(node),
                "outgoing_edges": outgoing,
                "incoming_edges": incoming,
            }

    # ------------------------------------------------------------------
    # Embedding queries
    # ------------------------------------------------------------------

    def get_embeddings(self, file_id: str) -> list[dict[str, Any]]:
        """List embedding metadata for a file."""
        with self._uow() as uow:
            embeddings = uow.embeddings.list_by_file(file_id)
            return [self._embedding_to_dict(e) for e in embeddings]

    # ------------------------------------------------------------------
    # Metric queries
    # ------------------------------------------------------------------

    def get_metrics(
        self,
        repository_id: str,
        *,
        metric_name: str | None = None,
        branch: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List metrics for a repository with optional filters, most recent first."""
        with self._uow() as uow:
            metrics = uow.metrics.list_by_repository(
                repository_id, metric_name=metric_name, branch=branch, limit=limit
            )
            return [self._metric_to_dict(m) for m in metrics]

    def get_metrics_by_commit(
        self, repository_id: str, git_commit: str
    ) -> list[dict[str, Any]]:
        """List all metrics recorded for a specific commit."""
        with self._uow() as uow:
            metrics = uow.metrics.list_by_commit(repository_id, git_commit)
            return [self._metric_to_dict(m) for m in metrics]

    # ------------------------------------------------------------------
    # AnalysisRun queries
    # ------------------------------------------------------------------

    def get_analyses(
        self,
        repository_id: str,
        *,
        command: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List analysis runs for a repository with optional filters, most recent first."""
        with self._uow() as uow:
            runs = uow.analysis_runs.list_by_repository(
                repository_id, command=command, status=status, limit=limit
            )
            return [self._run_to_dict(r) for r in runs]

    def get_latest_analysis(
        self, repository_id: str, *, command: str | None = None
    ) -> dict[str, Any] | None:
        """Get the most recent analysis run for a repository."""
        with self._uow() as uow:
            run = uow.analysis_runs.get_latest(repository_id, command=command)
            if run is None:
                return None
            return self._run_to_dict(run)

    def get_analyses_by_commit(
        self, repository_id: str, git_commit: str
    ) -> list[dict[str, Any]]:
        """List all analysis runs for a specific commit."""
        with self._uow() as uow:
            runs = uow.analysis_runs.list_by_commit(repository_id, git_commit)
            return [self._run_to_dict(r) for r in runs]

    # ------------------------------------------------------------------
    # Converters (ORM model → plain dict)
    # ------------------------------------------------------------------

    @staticmethod
    def _repo_to_dict(repo) -> dict[str, Any]:
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
    def _file_to_dict(f) -> dict[str, Any]:
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
    def _symbol_to_dict(s) -> dict[str, Any]:
        return {
            "id": s.id,
            "file_id": s.file_id,
            "name": s.name,
            "type": s.type,
            "line": s.line,
        }

    @staticmethod
    def _import_to_dict(i) -> dict[str, Any]:
        return {
            "id": i.id,
            "file_id": i.file_id,
            "module": i.module,
            "symbol": i.symbol,
        }

    @staticmethod
    def suggestion_stats(suggestions: list | Sequence | None = None) -> dict[str, Any]:
        """Compute list/detail metrics from suggestion rows or dicts."""
        rows = list(suggestions or [])
        files: set[str] = set()
        critical = 0
        warning = 0
        for s in rows:
            if isinstance(s, dict):
                path = str(s.get("file") or "").strip()
                severity = str(s.get("severity") or "").lower()
            else:
                path = str(getattr(s, "file", "") or "").strip()
                severity = str(getattr(s, "severity", "") or "").lower()
            if path:
                files.add(path)
            if severity in {"critical", "high", "blocker"}:
                critical += 1
            elif severity in {"medium", "low", "warning", "warn"}:
                warning += 1
        return {
            "suggestion_count": len(rows),
            "file_count": len(files),
            "critical_count": critical,
            "warning_count": warning,
        }

    @classmethod
    def _review_to_dict(cls, r, *, suggestions: list | Sequence | None = None) -> dict[str, Any]:
        stats = cls.suggestion_stats(suggestions or [])
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
            "suggestion_count": stats["suggestion_count"],
            "file_count": stats["file_count"],
            "critical_count": stats["critical_count"],
            "warning_count": stats["warning_count"],
        }

    @staticmethod
    def _suggestion_to_dict(s) -> dict[str, Any]:
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

    def get_review_suggestion(self, suggestion_id: str) -> dict[str, Any] | None:
        with self._uow() as uow:
            row = uow.review_suggestions.get_by_id(suggestion_id)
            if row is None:
                return None
            return self._suggestion_to_dict(row)

    @staticmethod
    def _rec_to_dict(r) -> dict[str, Any]:
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
    def _patch_to_dict(p) -> dict[str, Any]:
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
            "apply_available": True,
        }

    @staticmethod
    def _node_to_dict(n) -> dict[str, Any]:
        return {
            "id": n.id,
            "repository_id": n.repository_id,
            "name": n.name,
            "type": n.type,
        }

    @staticmethod
    def _edge_to_dict(e) -> dict[str, Any]:
        return {
            "id": e.id,
            "source_node": e.source_node,
            "target_node": e.target_node,
            "relationship": e.relationship_,
        }

    @staticmethod
    def _embedding_to_dict(e) -> dict[str, Any]:
        return {
            "id": e.id,
            "file_id": e.file_id,
            "chunk_id": e.chunk_id,
            "provider": e.provider,
            "model": e.model,
            "vector_reference": e.vector_reference,
        }

    @staticmethod
    def _metric_to_dict(m) -> dict[str, Any]:
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
    def _run_to_dict(r) -> dict[str, Any]:
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
