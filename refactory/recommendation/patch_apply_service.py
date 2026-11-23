"""PatchService — apply / dry-run / rollback of stored recommendation patches.

Working-tree file IO is performed against the configured repo root.
GitService supplies HEAD / dirty / merge-conflict checks (best-effort).
Controllers never call repositories or git directly.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from refactory.recommendation.patch_models import (
    FilePatchContent,
    PatchApplyError,
    PatchApplyResult,
    PatchConflictError,
    PatchValidationResult,
)

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.company.checker import CompanyRulesChecker
    from refactory.db.persistence import PersistenceService
    from refactory.db.query_service import RepositoryQueryService
    from refactory.git.service import GitService
    from refactory.graph.service import RepositoryGraphService
    from refactory.indexer.service import IndexerService
    from refactory.parser.service import ParserService


class PatchService:
    """Apply stored patches with validation, persistence, and history."""

    def __init__(
        self,
        *,
        logger: "Logger",
        git_service: "GitService",
        query_service: "RepositoryQueryService",
        persistence_service: "PersistenceService",
        parser_service: "ParserService | None" = None,
        indexer_service: "IndexerService | None" = None,
        graph_service: "RepositoryGraphService | None" = None,
        company_rules_checker: "CompanyRulesChecker | None" = None,
    ) -> None:
        self._logger = logger
        self._git = git_service
        self._query = query_service
        self._persistence = persistence_service
        self._parser = parser_service
        self._indexer = indexer_service
        self._graph = graph_service
        self._company_rules = company_rules_checker

    def apply(
        self,
        patch_id: str,
        repo_root: Path | None = None,
        *,
        dry_run: bool = False,
        applied_by: str = "local",
    ) -> PatchApplyResult:
        """Validate and optionally apply a stored patch to the working tree."""
        root = self._resolve_root(repo_root)
        repo = self._query.get_repository_by_root(str(root))
        if repo is None:
            raise PatchApplyError(
                "No repository record yet — configure repo root and run index first.",
                status_code=404,
            )

        stored = self._persistence.get_recommendation_patch(patch_id)
        if stored is None:
            raise PatchApplyError(f"Patch '{patch_id}' not found.", status_code=404)
        if stored.get("repository_id") != repo["id"]:
            raise PatchApplyError(
                "Patch does not belong to the configured repository.",
                status_code=404,
            )

        if stored.get("status") == "applied" and not dry_run:
            raise PatchApplyError(
                "Patch already applied. Use rollback before re-applying.",
                status_code=409,
            )

        file_patches = self._normalize_stored_patches(stored)
        if not file_patches:
            raise PatchApplyError(
                "Empty patch — no file contents to apply.",
                status_code=422,
            )
        if all(
            (fp.original or "") == (fp.modified or "") for fp in file_patches
        ):
            raise PatchApplyError(
                "Empty patch — original and modified contents are identical.",
                status_code=422,
            )

        changed_paths = [fp.file_path for fp in file_patches]
        proposed = {fp.file_path: fp.modified for fp in file_patches}
        originals = {fp.file_path: fp.original for fp in file_patches}

        self._enforce_org_gate(root, changed_paths, proposed)

        if self._safe_has_unmerged():
            reason = "Dirty working tree — unresolved merge conflicts present."
            self._record_failure(patch_id, reason)
            raise PatchApplyError(reason, status_code=409)

        missing: list[str] = []
        permission: list[str] = []
        for rel in changed_paths:
            target = self._safe_target(root, rel)
            if target is None or not target.is_file():
                missing.append(rel)
                continue
            try:
                target.read_text(encoding="utf-8", errors="replace")
            except PermissionError:
                permission.append(rel)
            except OSError as exc:
                raise PatchApplyError(
                    f"Unable to read '{rel}': {exc}",
                    status_code=422,
                ) from exc

        if missing:
            reason = "File missing — cannot apply patch: " + ", ".join(missing)
            self._record_failure(patch_id, reason)
            raise PatchApplyError(reason, status_code=422)
        if permission:
            reason = "Permission denied reading: " + ", ".join(permission)
            self._record_failure(patch_id, reason)
            raise PatchApplyError(reason, status_code=403)

        mismatches = self._find_mismatches(root, originals)
        if mismatches:
            reason = (
                "Patch outdated — the repository changed since the patch was "
                "generated. Generate a new patch from the current files."
            )
            self._record_failure(patch_id, reason)
            raise PatchConflictError(reason, files=mismatches)

        head_sha = self._safe_head()

        if dry_run:
            return PatchApplyResult(
                status="dry_run",
                applied=False,
                dry_run=True,
                patch_id=patch_id,
                recommendation_id=str(stored.get("recommendation_id") or ""),
                changed_files=changed_paths,
                message=f"Dry run OK — would apply patch to {len(changed_paths)} file(s).",
                git_commit=head_sha,
                details={"would_write": changed_paths},
            )

        written: list[tuple[Path, str, str]] = []
        try:
            for fp in file_patches:
                target = self._safe_target(root, fp.file_path)
                assert target is not None
                # Prefer GitService write when paths share the git root
                self._write_file(root, fp.file_path, fp.modified)
                written.append((target, fp.original, fp.file_path))
        except PermissionError as exc:
            self._restore(root, originals)
            reason = f"Permission denied writing patch files: {exc}"
            self._record_failure(patch_id, reason)
            raise PatchApplyError(reason, status_code=403) from exc
        except OSError as exc:
            self._restore(root, originals)
            reason = f"Git failure writing patch files: {exc}"
            self._record_failure(patch_id, reason)
            raise PatchApplyError(reason, status_code=422) from exc

        validation = self._validate_written(root, written)
        if not validation.ok:
            self._restore(root, originals)
            validation.rolled_back = True
            reason = "Validation failed — changes were rolled back."
            self._record_failure(patch_id, reason)
            return PatchApplyResult(
                status="failed",
                applied=False,
                patch_id=patch_id,
                recommendation_id=str(stored.get("recommendation_id") or ""),
                changed_files=changed_paths,
                validation=validation,
                failure_reason=reason,
                failure_code="validation_failed",
                message=reason,
                details={"errors": validation.errors},
            )

        index_updated, graph_updated = self._refresh_index_graph(root, repo)
        applied_at = datetime.now(timezone.utc)
        self._persistence.mark_patch_applied(
            patch_id,
            applied_by=applied_by or "local",
            git_commit=head_sha,
            applied_at=applied_at,
        )

        apply_result = PatchApplyResult(
            status="applied",
            applied=True,
            patch_id=patch_id,
            recommendation_id=str(stored.get("recommendation_id") or ""),
            changed_files=changed_paths,
            validation=validation,
            repository_updated=True,
            index_updated=index_updated,
            graph_updated=graph_updated,
            message=f"Applied patch to {len(changed_paths)} file(s).",
            git_commit=head_sha,
            applied_at=applied_at.isoformat(),
            applied_by=applied_by or "local",
            details={
                "content_hashes": {
                    rel: hashlib.sha256(path.read_bytes()).hexdigest()[:16]
                    for path, _, rel in written
                },
                "rollback": {"originals_available": True, "files": changed_paths},
            },
        )
        self._persist_history(repo["id"], apply_result, command="patch-apply")
        return apply_result

    def rollback(
        self,
        patch_id: str,
        repo_root: Path | None = None,
        *,
        applied_by: str = "local",
    ) -> PatchApplyResult:
        """Restore originals from a previously applied patch."""
        root = self._resolve_root(repo_root)
        repo = self._query.get_repository_by_root(str(root))
        if repo is None:
            raise PatchApplyError(
                "No repository record yet — configure repo root and run index first.",
                status_code=404,
            )
        stored = self._persistence.get_recommendation_patch(patch_id)
        if stored is None:
            raise PatchApplyError(f"Patch '{patch_id}' not found.", status_code=404)
        if stored.get("repository_id") != repo["id"]:
            raise PatchApplyError(
                "Patch does not belong to the configured repository.",
                status_code=404,
            )
        if stored.get("status") == "rolled_back":
            raise PatchApplyError(
                "Patch has already been rolled back.",
                status_code=409,
            )
        if stored.get("status") != "applied":
            raise PatchApplyError(
                "Nothing to rollback.",
                status_code=409,
            )

        file_patches = self._normalize_stored_patches(stored)
        if not file_patches:
            raise PatchApplyError(
                "Patch has no file contents to roll back.", status_code=422
            )

        modified = {fp.file_path: fp.modified for fp in file_patches}
        mismatches = self._find_mismatches(root, modified)
        if mismatches:
            raise PatchConflictError(
                "Cannot roll back — working tree no longer matches the applied patch.",
                files=mismatches,
            )

        originals = {fp.file_path: fp.original for fp in file_patches}
        try:
            self._restore(root, originals)
        except OSError as exc:
            raise PatchApplyError(
                f"Git failure during rollback: {exc}",
                status_code=422,
            ) from exc

        meta = {
            "rolled_back_by": applied_by or "local",
            "rolled_back_at": datetime.now(timezone.utc).isoformat(),
            "files": list(originals.keys()),
            "previous_git_commit": stored.get("git_commit"),
        }
        self._persistence.mark_patch_rolled_back(patch_id, rollback_metadata=meta)
        index_updated, graph_updated = self._refresh_index_graph(root, repo)
        result = PatchApplyResult(
            status="rolled_back",
            applied=False,
            patch_id=patch_id,
            recommendation_id=str(stored.get("recommendation_id") or ""),
            changed_files=list(originals.keys()),
            repository_updated=True,
            index_updated=index_updated,
            graph_updated=graph_updated,
            message=f"Rolled back patch on {len(originals)} file(s).",
            details={"rollback": meta},
            git_commit=self._safe_head(),
        )
        self._persist_history(repo["id"], result, command="patch-rollback")
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_root(self, repo_root: Path | None) -> Path:
        if repo_root is not None:
            return repo_root.resolve()
        return Path(self._git.get_root_path()).resolve()

    def _enforce_org_gate(
        self, root: Path, changed_paths: list[str], proposed: dict[str, str]
    ) -> None:
        if self._company_rules is None:
            return
        try:
            gate = self._company_rules.check(
                root,
                changed_files=changed_paths,
                file_contents=proposed,
            )
            org_blockers = [
                v
                for v in gate.violations
                if v.blocking and getattr(v, "source", "") == "organization"
            ]
            if org_blockers:
                detail = "; ".join(f"{v.rule}: {v.message}" for v in org_blockers[:3])
                raise PatchApplyError(
                    f"Cannot apply patch — blocking organization policy: {detail}",
                    status_code=409,
                )
        except PatchApplyError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Rules gate before patch apply skipped: {}", exc)

    def _record_failure(self, patch_id: str, reason: str) -> None:
        try:
            self._persistence.mark_patch_failed(patch_id, failure_reason=reason)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("Could not persist patch failure: {}", exc)

    def _refresh_index_graph(
        self, root: Path, repo: dict[str, Any]
    ) -> tuple[bool, bool]:
        index_updated = False
        graph_updated = False
        try:
            if self._indexer is not None:
                index = self._indexer.build_index(
                    root,
                    repository_name=repo.get("name"),
                    force=False,
                )
                index_updated = True
                if self._graph is not None:
                    try:
                        self._graph.build_graph(index, force=True)
                        graph_updated = True
                    except Exception as exc:  # noqa: BLE001
                        self._logger.warning(
                            "Graph refresh after patch apply failed: {}", exc
                        )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Index refresh after patch apply failed: {}", exc)
        return index_updated, graph_updated

    def _persist_history(
        self, repository_id: str, result: PatchApplyResult, *, command: str
    ) -> None:
        try:
            self._persistence.persist_analysis_run(
                repository_id=repository_id,
                command=command,
                result_type="patch_apply",
                status=(
                    "completed"
                    if result.status in {"applied", "rolled_back", "dry_run"}
                    else "failed"
                ),
                summary=result.message,
                result_data={
                    "patch_id": result.patch_id,
                    "recommendation_id": result.recommendation_id,
                    "changed_files": result.changed_files,
                    "status": result.status,
                    "git_commit": result.git_commit,
                    "message": result.message,
                },
                metadata={"patch_id": result.patch_id},
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("Patch history persist skipped: {}", exc)

    def _safe_head(self) -> str | None:
        try:
            return self._git.get_head_sha()
        except Exception:  # noqa: BLE001
            return None

    def _safe_has_unmerged(self) -> bool:
        try:
            return bool(self._git.has_unmerged_paths())
        except Exception:  # noqa: BLE001
            return False

    def _normalize_stored_patches(self, stored: dict[str, Any]) -> list[FilePatchContent]:
        raw = stored.get("patches") or []
        out: list[FilePatchContent] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            path = str(item.get("file_path") or "").replace("\\", "/").lstrip("./")
            original = item.get("original")
            modified = item.get("modified")
            if not path or not isinstance(original, str) or not isinstance(modified, str):
                continue
            out.append(
                FilePatchContent(file_path=path, original=original, modified=modified)
            )
        return out

    @staticmethod
    def _normalize_text(text: str) -> str:
        return text.replace("\r\n", "\n").replace("\r", "\n")

    @staticmethod
    def _safe_target(root: Path, relative: str) -> Path | None:
        from refactory.git.paths import safe_repo_relative_path

        return safe_repo_relative_path(root, relative)

    def _find_mismatches(self, root: Path, expected: dict[str, str]) -> list[str]:
        mismatches: list[str] = []
        for rel, baseline in expected.items():
            target = self._safe_target(root, rel)
            if target is None or not target.is_file():
                mismatches.append(rel)
                continue
            try:
                current = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                mismatches.append(rel)
                continue
            if self._normalize_text(current) != self._normalize_text(baseline):
                mismatches.append(rel)
        return mismatches

    def _write_file(self, root: Path, relative: str, content: str) -> None:
        """Write via GitService when roots align; otherwise direct Path write."""
        try:
            git_root = Path(self._git.get_root_path()).resolve()
        except Exception:  # noqa: BLE001
            git_root = None
        if git_root is not None and git_root == root:
            self._git.write_working_files({relative: content})
            return
        target = self._safe_target(root, relative)
        if target is None:
            raise OSError(f"Unsafe path: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def _restore(self, root: Path, originals: dict[str, str]) -> None:
        try:
            git_root = Path(self._git.get_root_path()).resolve()
        except Exception:  # noqa: BLE001
            git_root = None
        if git_root is not None and git_root == root:
            self._git.restore_working_files(originals)
            return
        for rel, content in originals.items():
            target = self._safe_target(root, rel)
            if target is None:
                continue
            try:
                target.write_text(content, encoding="utf-8")
            except OSError:
                pass

    def _validate_written(
        self,
        root: Path,
        written: list[tuple[Path, str, str]],
    ) -> PatchValidationResult:
        errors: list[str] = []
        checked: list[str] = []
        if self._parser is None:
            return PatchValidationResult(ok=True, checked_files=[], errors=[])

        supported = {ext.lower() for ext in self._parser.supported_extensions()}
        for path, _original, rel in written:
            if path.suffix.lower() not in supported:
                continue
            checked.append(rel)
            try:
                parsed = self._parser.parse_file(path, repo_root=root)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{rel}: parse failed — {exc}")
                continue
            if getattr(parsed, "has_syntax_errors", False):
                msg = getattr(parsed, "error_message", None) or "syntax errors detected"
                errors.append(f"{rel}: {msg}")

        return PatchValidationResult(
            ok=not errors,
            checked_files=checked,
            errors=errors,
            rolled_back=False,
        )
