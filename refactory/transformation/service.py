"""TransformationService — orchestrates the full transformation pipeline.

Recommendation → Plan → Patch → Preview → Validate → Apply → Persist
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from refactory.transformation.models import (
    ConflictType,
    TransformationConflict,
    TransformationError,
    TransformationHistory,
    TransformationPatch,
    TransformationPlan,
    TransformationPreview,
    TransformationRequest,
    TransformationResult,
    TransformationStatus,
    TransformationType,
    TransformationValidation,
    ValidationStatus,
)
from refactory.transformation.patch import PatchGenerator
from refactory.transformation.planner import TransformationPlanner
from refactory.transformation.preview import PreviewEngine
from refactory.transformation.validator import ValidationEngine

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.ai.gateway import AIGateway
    from refactory.db.persistence import PersistenceService
    from refactory.db.query_service import RepositoryQueryService
    from refactory.graph.service import RepositoryGraphService
    from refactory.indexer.service import IndexerService
    from refactory.parser.service import ParserService
    from refactory.policies.service import ArchitecturePolicyService
    from refactory.prompts import PromptTemplateService
    from refactory.rules.engine import RuleEngine
    from refactory.storage.service import StorageService


AI_ASSISTED_TYPES = {
    TransformationType.EXTRACT_METHOD,
    TransformationType.EXTRACT_CLASS,
    TransformationType.GENERATE_DOCSTRINGS,
    TransformationType.GENERATE_TESTS,
    TransformationType.ARCHITECTURE_REFACTORING,
    TransformationType.SPLIT_LARGE_CLASS,
    TransformationType.AI_PLAN,
}

SUPPORTED_TYPES = {
    TransformationType.RENAME_SYMBOL,
    TransformationType.RENAME_FUNCTION,
    TransformationType.RENAME_CLASS,
    TransformationType.RENAME_VARIABLE,
    TransformationType.RENAME_MODULE,
    TransformationType.RENAME_FILE,
    TransformationType.EXTRACT_METHOD,
    TransformationType.INLINE_METHOD,
    TransformationType.MOVE_SYMBOL,
    TransformationType.MOVE_METHOD,
    TransformationType.MOVE_CLASS,
    TransformationType.CHANGE_SIGNATURE,
    TransformationType.REMOVE_DEAD_CODE,
    TransformationType.REPLACE_DEPRECATED_API,
    TransformationType.UPDATE_IMPORTS,
    TransformationType.GENERATE_DOCSTRINGS,
    TransformationType.GENERATE_TESTS,
    TransformationType.AI_PLAN,
    TransformationType.ARCHITECTURE_REFACTORING,
}


class TransformationService:
    """Orchestrates the complete transformation pipeline."""

    def __init__(
        self,
        logger: "Logger",
        parser_service: "ParserService",
        indexer_service: "IndexerService",
        graph_service: "RepositoryGraphService",
        rule_engine: "RuleEngine",
        policy_service: "ArchitecturePolicyService",
        storage_service: "StorageService",
        ai_gateway: "AIGateway",
        prompt_service: "PromptTemplateService",
        *,
        query_service: "RepositoryQueryService | None" = None,
        persistence_service: "PersistenceService | None" = None,
    ) -> None:
        self._logger = logger
        self._parser = parser_service
        self._indexer = indexer_service
        self._graph = graph_service
        self._rules = rule_engine
        self._policy = policy_service
        self._storage = storage_service
        self._ai = ai_gateway
        self._prompts = prompt_service
        self._query = query_service
        self._persistence = persistence_service

        self._planner = TransformationPlanner(logger)
        from refactory.transformation.ai_planner import AIRefactoringPlanner

        self._ai_planner = AIRefactoringPlanner(
            logger,
            self._planner,
            ai_gateway=ai_gateway,
            graph_service=graph_service,
        )
        self._patch_gen = PatchGenerator()
        self._preview_engine = PreviewEngine(logger)
        self._validator = ValidationEngine(logger, parser_service, rule_engine, policy_service)

        self._history: list[TransformationHistory] = []
        self._load_history()

    # ------------------------------------------------------------------
    # Transformation type validation
    # ------------------------------------------------------------------

    def _validate_request(self, request: TransformationRequest) -> str | None:
        """Validate a transformation request. Returns error message or None."""
        try:
            TransformationType(request.transformation_type)
        except (ValueError, KeyError):
            return f"Unknown transformation type: {request.transformation_type}"

        if request.natural_language.strip():
            return None

        if request.transformation_type not in SUPPORTED_TYPES:
            return (
                f"Transformation type '{request.transformation_type.value}' "
                f"is not yet supported. Supported: "
                f"{', '.join(t.value for t in sorted(SUPPORTED_TYPES, key=lambda t: t.value))}"
            )
        return None

    def _validate_target_in_repo(
        self, request: TransformationRequest, root: Path
    ) -> str | None:
        """Ensure target paths stay inside the active repository root."""
        from refactory.git.paths import safe_repo_relative_path

        if not request.target_file or not str(request.target_file).strip():
            return None
        target = safe_repo_relative_path(root, request.target_file)
        if target is None:
            return (
                "Invalid target path — path traversal or escape outside "
                f"the repository root was rejected: {request.target_file}"
            )
        # Create-style ops may introduce new files; others need an existing file.
        create_like = {
            TransformationType.CREATE_FILE,
            TransformationType.CREATE_INTERFACE,
        }
        if request.transformation_type in create_like:
            return None
        if not target.is_file():
            return (
                "Target file does not exist inside the selected repository: "
                f"{request.target_file}"
            )
        return None

    # ------------------------------------------------------------------
    # History persistence
    # ------------------------------------------------------------------

    def _load_history(self, root: Path | None = None) -> None:
        """Load transformation history from storage.

        Newest apply/status rows win per ``history_id`` so a persisted
        ``rolled_back`` supersedes the original ``applied`` record after refresh.
        """
        try:
            from refactory.transformation.models import TransformationStep

            repo_path = str(root) if root is not None else ""
            stored = self._read_analyses(repo_path, command="apply", limit=100)
            seen: set[str] = set()
            loaded: list[TransformationHistory] = []
            for entry in stored:
                data = entry.get("result_data", {}) or {}
                history_id = str(data.get("history_id") or "")
                if not history_id or history_id in seen:
                    continue
                status_raw = str(data.get("status") or TransformationStatus.APPLIED.value)
                try:
                    status = TransformationStatus(status_raw)
                except ValueError:
                    status = TransformationStatus.APPLIED
                if status not in {
                    TransformationStatus.APPLIED,
                    TransformationStatus.ROLLED_BACK,
                }:
                    continue
                seen.add(history_id)
                try:
                    ttype = TransformationType(
                        data.get("transformation_type", "rename_symbol")
                    )
                except ValueError:
                    ttype = TransformationType.RENAME_SYMBOL
                steps_raw = data.get("steps") or []
                steps = []
                for s in steps_raw:
                    try:
                        steps.append(TransformationStep.model_validate(s))
                    except Exception:  # noqa: BLE001
                        continue
                rolled_at = data.get("rolled_back_at")
                rolled_dt = None
                if rolled_at:
                    try:
                        rolled_dt = datetime.fromisoformat(str(rolled_at).replace("Z", "+00:00"))
                    except ValueError:
                        rolled_dt = None
                created_at = entry.get("created_at") or data.get("created_at")
                created_dt = None
                if created_at:
                    try:
                        created_dt = datetime.fromisoformat(
                            str(created_at).replace("Z", "+00:00")
                        )
                    except ValueError:
                        created_dt = None
                history = TransformationHistory(
                    id=history_id,
                    plan_id=data.get("plan_id", ""),
                    patch_id=data.get("patch_id", ""),
                    status=status,
                    transformation_type=ttype,
                    description=data.get("description", ""),
                    target_file=data.get("target_file", ""),
                    target_symbol=data.get("target_symbol", ""),
                    files_modified=data.get("files_modified", []),
                    patch_content=data.get("patch_content", ""),
                    rollback_patch=data.get("rollback_patch", ""),
                    steps=steps,
                    validation_status=ValidationStatus(
                        data.get("validation_status", "passed")
                    ),
                    created_at=created_dt
                    or datetime.now(timezone.utc),
                    rolled_back_at=rolled_dt,
                )
                loaded.append(history)
            # Preserve in-memory-only rows not yet persisted, then merge loaded.
            memory_ids = {h.id for h in loaded}
            retained = [h for h in self._history if h.id not in memory_ids]
            # Loaded is newest-first from analyses; keep chronological oldest→newest.
            loaded.reverse()
            self._history = retained + loaded
        except Exception:  # noqa: BLE001
            pass

    def ensure_history_loaded(self, root: Path) -> None:
        """Reload applied/rolled-back history for a repository root."""
        self._load_history(root)

    def _read_analyses(
        self,
        repo_path: str,
        *,
        command: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Read analysis history, preferring RepositoryQueryService over StorageService.

        Returns a list of dicts with the same structure as StorageService.get_analyses
        for full backward compatibility.
        """
        if self._query is not None:
            try:
                repo = self._query.get_repository_by_root(repo_path)
                if repo is None:
                    return []
                raw = self._query.get_analyses(
                    repo["id"], command=command, limit=limit
                )
                return [
                    {
                        "id": r["id"],
                        "command": r["command"],
                        "status": r["status"],
                        "git_commit": r["git_commit"],
                        "branch": r["branch"],
                        "timestamp": r["created_at"],
                        "duration_ms": r["duration_ms"],
                        "result_type": r["result_type"],
                        "result_data": r["result_data"],
                    }
                    for r in raw
                ]
            except Exception:  # noqa: BLE001
                self._logger.debug(
                    "QueryService read failed for {}/{}, falling back to StorageService",
                    repo_path, command,
                )
        return self._storage.get_analyses(repo_path, command=command, limit=limit)

    def _get_repository_id(self, repository_path: str, repository_name: str) -> str:
        """Resolve a repository path to a PersistenceService repository ID."""
        repo = self._persistence.get_or_create_repository(  # type: ignore[union-attr]
            name=repository_name,
            root_path=repository_path,
        )
        return repo["id"]

    def _write_analysis(
        self,
        repository_path: str,
        repository_name: str,
        *,
        command: str,
        result_type: str,
        result_data: dict,
        duration_ms: float = 0.0,
        status: str = "completed",
        summary: str = "",
    ) -> None:
        """Write an analysis run, preferring PersistenceService when available."""
        if self._persistence is not None:
            try:
                repo_id = self._get_repository_id(repository_path, repository_name)
                self._persistence.persist_analysis_run(
                    repository_id=repo_id,
                    command=command,
                    result_type=result_type,
                    result_data=result_data,
                    duration_ms=duration_ms,
                    status=status,
                    summary=summary,
                )
                return
            except Exception:  # noqa: BLE001
                self._logger.debug(
                    "PersistenceService write failed, falling back to StorageService"
                )
        self._storage.store_analysis(
            repository_path=repository_path,
            repository_name=repository_name,
            command=command,
            result_type=result_type,
            result_data=result_data,
            duration_ms=duration_ms,
            status=status,
        )

    def _write_metric(
        self,
        repository_path: str,
        repository_name: str,
        *,
        metric_name: str,
        metric_value: float,
    ) -> None:
        """Write a metric, preferring PersistenceService when available."""
        if self._persistence is not None:
            try:
                repo_id = self._get_repository_id(repository_path, repository_name)
                self._persistence.persist_metric(
                    repository_id=repo_id,
                    metric_name=metric_name,
                    metric_value=metric_value,
                )
                return
            except Exception:  # noqa: BLE001
                self._logger.debug(
                    "PersistenceService metric write failed, falling back to StorageService"
                )
        self._storage.store_metric(
            repository_path=repository_path,
            repository_name=repository_name,
            metric_name=metric_name,
            metric_value=metric_value,
        )

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------

    def transform(self, request: TransformationRequest, root: Path) -> TransformationPreview:
        """Execute the full transformation pipeline up to preview (no apply)."""
        error = self._validate_request(request) or self._validate_target_in_repo(
            request, root
        )
        if error:
            self._logger.warning("Validation failed: {}", error)
            raise TransformationError(
                "Transformation failed",
                reason=error,
                errors=[error],
                meta={
                    "transformation_type": getattr(
                        request.transformation_type, "value", str(request.transformation_type)
                    ),
                    "target_file": request.target_file,
                    "target_symbol": request.target_symbol,
                },
            )

        self._logger.info(
            "Transformation: {} on {}", request.transformation_type.value, request.target_file
        )
        started = time.perf_counter()

        plan = self._create_plan(request, root)

        if not plan.steps:
            detail = plan.description or "Transformation produced no changes."
            raise TransformationError(
                "Transformation failed",
                reason=detail,
                errors=[detail],
                meta={
                    "transformation_type": request.transformation_type.value,
                    "target_file": request.target_file,
                    "target_symbol": request.target_symbol,
                },
            )

        patch = self._patch_gen.generate(plan, root)
        if not patch.diff_content:
            detail = plan.description or "Transformation produced no edits."
            raise TransformationError(
                "Transformation failed",
                reason=detail,
                errors=[detail],
                meta={
                    "transformation_type": request.transformation_type.value,
                    "target_file": request.target_file,
                    "target_symbol": request.target_symbol,
                },
            )

        conflicts = self._detect_conflicts(patch, root, plan=plan)
        if conflicts:
            self._logger.warning("Conflicts detected: {}", len(conflicts))
            plan.estimated_risk = "high"

        validation = self._validator.validate(plan, patch, root)
        if validation.status == ValidationStatus.FAILED:
            detail = "; ".join(validation.errors) or "Validation failed."
            raise TransformationError(
                "Transformation failed",
                reason=detail,
                errors=validation.errors or [detail],
                meta={
                    "transformation_type": request.transformation_type.value,
                    "target_file": request.target_file,
                    "target_symbol": request.target_symbol,
                },
            )

        preview = self._preview_engine.generate_preview(plan, patch, validation)

        duration_ms = (time.perf_counter() - started) * 1000
        self._persist_plan(plan, patch, duration_ms, root=root, request=request)

        self._logger.info(
            "Transformation planned in {:.0f}ms: {} files, +{}/-{}",
            duration_ms, len(patch.files_modified), patch.additions, patch.deletions,
        )
        return preview

    def apply(self, request: TransformationRequest, root: Path) -> TransformationResult:
        """Execute the full pipeline and apply the patch."""
        error = self._validate_request(request) or self._validate_target_in_repo(
            request, root
        )
        if error:
            self._logger.warning("Validation failed: {}", error)
            raise TransformationError(
                "Transformation failed",
                reason=error,
                errors=[error],
                meta={
                    "transformation_type": getattr(
                        request.transformation_type, "value", str(request.transformation_type)
                    ),
                    "target_file": request.target_file,
                    "target_symbol": request.target_symbol,
                },
            )

        self._logger.info("Applying transformation: {}", request.transformation_type.value)
        started = time.perf_counter()

        plan = self._create_plan(request, root)

        if not plan.steps:
            detail = plan.description or "Transformation produced no changes."
            raise TransformationError(
                "Transformation failed",
                reason=detail,
                errors=[detail],
                meta={
                    "transformation_type": request.transformation_type.value,
                    "target_file": request.target_file,
                    "target_symbol": request.target_symbol,
                },
            )

        patch = self._patch_gen.generate(plan, root)
        if not patch.diff_content:
            detail = plan.description or "Transformation produced no edits."
            raise TransformationError(
                "Transformation failed",
                reason=detail,
                errors=[detail],
                meta={
                    "transformation_type": request.transformation_type.value,
                    "target_file": request.target_file,
                    "target_symbol": request.target_symbol,
                },
            )

        conflicts = self._detect_conflicts(patch, root, plan=plan)
        if conflicts:
            duration_ms = (time.perf_counter() - started) * 1000
            return TransformationResult(
                plan_id=plan.id,
                patch_id=patch.id,
                status=TransformationStatus.CONFLICT,
                files_modified=[],
                duration_ms=duration_ms,
                rollback_available=False,
            )

        validation = self._validator.validate(plan, patch, root)
        if validation.status == ValidationStatus.FAILED:
            detail = "; ".join(validation.errors) or "Validation failed."
            raise TransformationError(
                "Transformation failed",
                reason=detail,
                errors=validation.errors or [detail],
                meta={
                    "transformation_type": request.transformation_type.value,
                    "target_file": request.target_file,
                    "target_symbol": request.target_symbol,
                },
            )

        applied_files = self._apply_patch(plan, root)

        rollback_patch = self._patch_gen.generate_rollback(patch)
        history = TransformationHistory(
            plan_id=plan.id,
            patch_id=patch.id,
            status=TransformationStatus.APPLIED,
            transformation_type=request.transformation_type,
            description=plan.description,
            target_file=request.target_file,
            target_symbol=request.target_symbol,
            files_modified=applied_files,
            patch_content=patch.diff_content,
            rollback_patch=rollback_patch,
            steps=list(plan.steps),
            validation_status=validation.status,
            duration_ms=(time.perf_counter() - started) * 1000,
        )
        self._history.append(history)

        self._incremental_update(applied_files, root)

        duration_ms = (time.perf_counter() - started) * 1000

        self._persist_result(plan, patch, history, duration_ms, root=root, request=request)

        self._logger.info(
            "Transformation applied: {} files modified in {:.0f}ms",
            len(applied_files), duration_ms,
        )

        return TransformationResult(
            id=history.id,
            plan_id=plan.id,
            patch_id=patch.id,
            status=TransformationStatus.APPLIED,
            files_modified=applied_files,
            validation=validation,
            duration_ms=duration_ms,
            rollback_available=True,
        )

    def rollback(
        self, root: Path, *, history_id: str | None = None
    ) -> TransformationResult:
        """Rollback an applied transformation once (state machine enforced)."""
        self.ensure_history_loaded(root)

        if not self._history:
            raise TransformationError(
                "Transformation not found",
                reason="Nothing to rollback",
                errors=["Nothing to rollback."],
                meta={"transformation_id": history_id or ""},
                status_code=404,
            )

        if history_id:
            target = next((h for h in self._history if h.id == history_id), None)
            if target is None:
                raise TransformationError(
                    "Transformation not found",
                    reason="Nothing to rollback",
                    errors=[f"Transformation not found: {history_id}"],
                    meta={"transformation_id": history_id},
                    status_code=404,
                )
        else:
            # Last applied (not rolled back) — prefer newest applied entry.
            applied = [h for h in self._history if h.status == TransformationStatus.APPLIED]
            target = applied[-1] if applied else self._history[-1]

        if target.status == TransformationStatus.ROLLED_BACK:
            raise TransformationError(
                "Transformation already rolled back.",
                reason="Rollback has already been performed.",
                errors=["Rollback has already been performed."],
                meta={"transformation_id": target.id},
                status_code=409,
            )

        if target.status != TransformationStatus.APPLIED:
            raise TransformationError(
                "Transformation cannot be rolled back.",
                reason=f"Transformation status is '{target.status.value}'.",
                errors=[
                    f"Only APPLIED transformations can be rolled back "
                    f"(current status: {target.status.value})."
                ],
                meta={"transformation_id": target.id, "status": target.status.value},
                status_code=409,
            )

        started = time.perf_counter()
        self._apply_rollback_from_history(target, root)

        target.status = TransformationStatus.ROLLED_BACK
        target.rolled_back_at = datetime.now(timezone.utc)

        self._incremental_update(target.files_modified, root)

        duration_ms = (time.perf_counter() - started) * 1000
        self._logger.info("Rollback completed in {:.0f}ms", duration_ms)

        # Persist ROLLED_BACK so refresh cannot resurrect an APPLIED rollback button.
        self._persist_rollback_state(target, root=root, duration_ms=duration_ms)

        # Single user-facing history/activity entry for this rollback.
        self._write_analysis(
            str(root),
            root.name,
            command="rollback",
            result_type="transformation_rollback",
            result_data={
                "history_id": target.id,
                "files": target.files_modified,
                "transformation_type": target.transformation_type.value,
                "target_file": target.target_file,
                "target_symbol": target.target_symbol,
                "description": target.description,
                "status": TransformationStatus.ROLLED_BACK.value,
                "rolled_back_at": target.rolled_back_at.isoformat()
                if target.rolled_back_at
                else None,
                "summary": (
                    f"Rollback Transformation: "
                    f"{target.description or target.transformation_type.value}"
                ),
            },
            duration_ms=duration_ms,
            summary=(
                f"Rollback Transformation: "
                f"{target.description or target.transformation_type.value}"
            ),
        )

        return TransformationResult(
            id=target.id,
            plan_id=target.plan_id,
            patch_id=target.patch_id,
            status=TransformationStatus.ROLLED_BACK,
            files_modified=target.files_modified,
            duration_ms=duration_ms,
            rollback_available=any(
                h.status == TransformationStatus.APPLIED for h in self._history
            ),
        )

    def preview(self, request: TransformationRequest, root: Path) -> TransformationPreview:
        """Generate a preview without applying."""
        return self.transform(request, root)

    def get_history(self) -> list[TransformationHistory]:
        """Get transformation history (oldest → newest)."""
        return list(self._history)

    def list_recent(self, *, limit: int = 5) -> list[TransformationHistory]:
        """Newest-first applied + rolled-back transformations."""
        rows = [
            h
            for h in self._history
            if h.status
            in {TransformationStatus.APPLIED, TransformationStatus.ROLLED_BACK}
        ]
        return list(reversed(rows[-limit:]))

    def get_record(self, history_id: str) -> TransformationHistory | None:
        return next((h for h in self._history if h.id == history_id), None)

    # ------------------------------------------------------------------
    # AI Enhancement (Task 8)
    # ------------------------------------------------------------------

    def _create_plan(
        self, request: TransformationRequest, root: Path
    ) -> TransformationPlan:
        """Create a plan via AI planner (NL) or deterministic planner."""
        if request.natural_language.strip() or request.transformation_type == TransformationType.AI_PLAN:
            text = request.natural_language.strip() or request.parameters.get("goal") or ""
            plan = self._ai_planner.plan_from_natural_language(text, root, seed=request)
            if plan.steps:
                return plan
            # Fall through to deterministic if NL mapping failed but typed fields exist.
        plan = self._planner.create_plan(request, root)
        if (request.ai_assisted or request.transformation_type in AI_ASSISTED_TYPES) and not plan.steps:
            plan = self._enhance_with_ai(plan, request, root)
        if not plan.goal:
            plan.goal = plan.description
        if not plan.affected_files:
            plan.affected_files = [s.file_path for s in plan.steps if s.file_path]
        return plan

    def plan_only(self, request: TransformationRequest, root: Path) -> TransformationPlan:
        """Public helper for POST /transform/plan (no patch / apply)."""
        error = self._validate_request(request)
        if error and not request.natural_language.strip():
            raise TransformationError(
                "Transformation failed",
                reason=error,
                errors=[error],
            )
        plan = self._create_plan(request, root)
        if not plan.affected_files:
            plan.affected_files = [s.file_path for s in plan.steps if s.file_path]
        return plan

    def _enhance_with_ai(
        self, plan: TransformationPlan, request: TransformationRequest, root: Path
    ) -> TransformationPlan:
        """Use AI to enhance/generate transformation steps."""
        if plan.steps:
            return plan

        if request.natural_language.strip():
            return self._ai_planner.plan_from_natural_language(
                request.natural_language, root, seed=request
            )

        try:
            from refactory.ai.models import AIRequest
            prompt = (
                f"Generate a code transformation for: {plan.description}\n"
                f"Type: {request.transformation_type.value}\n"
                f"File: {request.target_file}\n"
                f"Symbol: {request.target_symbol}\n"
            )
            resp = self._ai.generate(AIRequest(
                system_prompt="You are a code refactoring assistant. Generate only the new code content.",
                user_prompt=prompt,
                max_tokens=1000,
            ))
            self._logger.debug("AI enhancement generated {} chars", len(resp.content))
        except Exception:  # noqa: BLE001
            self._logger.debug("AI enhancement skipped")

        return plan

    # ------------------------------------------------------------------
    # Conflict Detection (Task 9)
    # ------------------------------------------------------------------

    def _detect_conflicts(
        self,
        patch: TransformationPatch,
        root: Path,
        *,
        plan: TransformationPlan | None = None,
    ) -> list[TransformationConflict]:
        """Detect conflicts that would prevent applying the patch."""
        conflicts: list[TransformationConflict] = []
        create_paths = {
            s.file_path
            for s in (plan.steps if plan is not None else [])
            if s.action == "create" or (not s.original_content and s.new_content)
        }
        delete_paths = {
            s.file_path
            for s in (plan.steps if plan is not None else [])
            if s.action == "delete"
        }

        for file_path in patch.files_modified:
            if file_path in create_paths or file_path in delete_paths:
                continue
            full_path = root / file_path
            if not full_path.is_file():
                conflicts.append(TransformationConflict(
                    conflict_type=ConflictType.DELETED_FILE,
                    file_path=file_path,
                    description=f"File not found: {file_path}",
                ))

        seen_files: set[str] = set()
        for hunk in patch.hunks:
            if hunk.file_path in seen_files:
                conflicts.append(TransformationConflict(
                    conflict_type=ConflictType.OVERLAPPING_EDIT,
                    file_path=hunk.file_path,
                    description=f"Multiple edits to {hunk.file_path}",
                ))
            seen_files.add(hunk.file_path)

        return conflicts

    # ------------------------------------------------------------------
    # Apply (Task 7)
    # ------------------------------------------------------------------

    def _apply_patch(self, plan: TransformationPlan, root: Path) -> list[str]:
        """Apply transformation steps to disk (modify / create / delete)."""
        from refactory.git.paths import safe_repo_relative_path

        applied: list[str] = []
        for step in plan.steps:
            if not step.file_path:
                continue
            target = safe_repo_relative_path(root, step.file_path)
            if target is None:
                self._logger.error(
                    "Rejected unsafe transformation path: {}", step.file_path
                )
                continue
            try:
                if step.action == "delete" or (
                    not step.new_content and step.original_content and step.action != "create"
                ):
                    if target.is_file():
                        target.unlink()
                    applied.append(step.file_path)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(step.new_content, encoding="utf-8")
                applied.append(step.file_path)
            except OSError as e:
                self._logger.error("Failed to write {}: {}", step.file_path, e)
        return applied

    def _apply_rollback_from_history(
        self, history: TransformationHistory, root: Path
    ) -> None:
        """Restore files from stored before-snapshots on the history record."""
        from refactory.git.paths import safe_repo_relative_path

        steps = list(history.steps)
        if not steps:
            # Fallback: locate matching apply analysis for this history id.
            for analysis in self._read_analyses(str(root), command="apply", limit=50):
                data = analysis.get("result_data", {})
                if data.get("history_id") != history.id:
                    continue
                for step in data.get("steps") or []:
                    file_path = step.get("file_path", "")
                    original = step.get("original_content", "")
                    action = step.get("action") or "modify"
                    if not file_path:
                        continue
                    target = safe_repo_relative_path(root, file_path)
                    if target is None:
                        self._logger.error(
                            "Rejected unsafe rollback path: {}", file_path
                        )
                        continue
                    if action == "create" and not original:
                        if target.is_file():
                            target.unlink()
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(original or "", encoding="utf-8")
                return

        for step in steps:
            if not step.file_path:
                continue
            target = safe_repo_relative_path(root, step.file_path)
            if target is None:
                self._logger.error(
                    "Rejected unsafe rollback path: {}", step.file_path
                )
                continue
            if step.action == "create" and not step.original_content:
                if target.is_file():
                    target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(step.original_content, encoding="utf-8")

    # ------------------------------------------------------------------
    # Incremental Updates (Task 13)
    # ------------------------------------------------------------------

    def _incremental_update(self, files: list[str], root: Path) -> None:
        """Incrementally update parser, graph, and embeddings for modified files."""
        if not files:
            return
        from refactory.git.paths import safe_repo_relative_path

        self._logger.debug("Incremental update for {} files", len(files))
        for file_path in files:
            target = safe_repo_relative_path(root, file_path)
            if target is None:
                self._logger.error(
                    "Rejected unsafe incremental path: {}", file_path
                )
                continue
            if target.is_file():
                try:
                    self._parser.parse_file(target)
                except Exception:  # noqa: BLE001
                    pass

    # ------------------------------------------------------------------
    # Persistence (Task 10)
    # ------------------------------------------------------------------

    def _persist_plan(
        self,
        plan: TransformationPlan,
        patch: TransformationPatch,
        duration_ms: float,
        *,
        root: Path,
        request: TransformationRequest,
    ) -> None:
        """Persist transformation plan."""
        self._write_analysis(
            str(root),
            root.name,
            command="transform",
            result_type="transformation_plan",
            result_data={
                "plan_id": plan.id,
                "patch_id": patch.id,
                "type": plan.transformation_type.value,
                "transformation_type": plan.transformation_type.value,
                "target_file": request.target_file,
                "target_symbol": request.target_symbol,
                "description": plan.description,
                "files": plan.affected_files,
                "steps": [s.model_dump(mode="json") for s in plan.steps],
                "additions": patch.additions,
                "deletions": patch.deletions,
                "summary": plan.description or f"Preview {plan.transformation_type.value}",
            },
            duration_ms=duration_ms,
            summary=plan.description or f"Preview {plan.transformation_type.value}",
        )

    def _persist_result(
        self,
        plan: TransformationPlan,
        patch: TransformationPatch,
        history: TransformationHistory,
        duration_ms: float,
        *,
        root: Path,
        request: TransformationRequest,
    ) -> None:
        """Persist transformation result with full rollback data."""
        self._write_analysis(
            str(root),
            root.name,
            command="apply",
            result_type="transformation_applied",
            result_data={
                "history_id": history.id,
                "plan_id": plan.id,
                "patch_id": patch.id,
                "status": history.status.value,
                "files_modified": history.files_modified,
                "validation_status": history.validation_status.value,
                "transformation_type": history.transformation_type.value,
                "target_file": request.target_file,
                "target_symbol": request.target_symbol,
                "description": history.description or plan.description,
                "patch_content": history.patch_content,
                "rollback_patch": history.rollback_patch,
                "steps": [s.model_dump(mode="json") for s in plan.steps],
                "rolled_back_at": None,
                "summary": history.description
                or plan.description
                or f"Apply {history.transformation_type.value}",
            },
            duration_ms=duration_ms,
            summary=history.description
            or plan.description
            or f"Apply {history.transformation_type.value}",
        )
        self._write_metric(
            str(root),
            root.name,
            metric_name="transformations_applied",
            metric_value=1.0,
        )

    def _persist_rollback_state(
        self,
        history: TransformationHistory,
        *,
        root: Path,
        duration_ms: float,
    ) -> None:
        """Persist ROLLED_BACK so GET /transform/recent survives process restart."""
        self._write_analysis(
            str(root),
            root.name,
            command="apply",
            result_type="transformation_applied",
            result_data={
                "history_id": history.id,
                "plan_id": history.plan_id,
                "patch_id": history.patch_id,
                "status": TransformationStatus.ROLLED_BACK.value,
                "files_modified": history.files_modified,
                "validation_status": history.validation_status.value,
                "transformation_type": history.transformation_type.value,
                "target_file": history.target_file,
                "target_symbol": history.target_symbol,
                "description": history.description,
                "patch_content": history.patch_content,
                "rollback_patch": history.rollback_patch,
                "steps": [s.model_dump(mode="json") for s in history.steps],
                "rolled_back_at": history.rolled_back_at.isoformat()
                if history.rolled_back_at
                else None,
                "summary": (
                    f"Rolled back: "
                    f"{history.description or history.transformation_type.value}"
                ),
            },
            duration_ms=duration_ms,
            summary=(
                f"Rolled back: "
                f"{history.description or history.transformation_type.value}"
            ),
        )
