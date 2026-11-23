"""ReviewEngine — orchestrates existing services end-to-end (no duplicated logic)."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from refactory.core.logger import bind_context, new_request_id, review_logging_context
from refactory.git.models import ChangeKind, ChangedPath
from refactory.github.models import ChangedFile, PullRequest
from refactory.prompt.budget import ContextBudget
from refactory.prompt.models import PromptContext, PromptRequest
from refactory.retrieval.hybrid import HybridRanker
from refactory.retrieval.models import RankedContext, RetrievedFile, SearchResult
from refactory.review.interfaces import (
    AIGatewayPort,
    AIServicePort,
    GitHubServicePort,
    GitServicePort,
    IndexerServicePort,
    ParserServicePort,
    PromptBuilderPort,
    RepositoryGraphServicePort,
    ResponseParserPort,
    RetrievalServicePort,
)
from refactory.review.models import ReviewResult, ReviewSuggestion

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.company.checker import CompanyRulesChecker
    from refactory.db.persistence import PersistenceService
    from refactory.indexer.models import RepositoryIndex
    from refactory.response.models import ParsedReview
    from refactory.review.models import Repository


def _lookup_file_patch(patches: dict[str, str], path: str) -> str | None:
    normalized = path.replace("\\", "/")
    if normalized in patches:
        return patches[normalized]
    return patches.get(path)


def _split_unified_diff_by_path(diff_text: str) -> dict[str, str]:
    """Map file paths to their unified-diff chunks (from ``diff --git``)."""
    text = (diff_text or "").strip()
    if not text:
        return {}

    chunks = re.split(r"(?=^diff --git )", text, flags=re.MULTILINE)
    result: dict[str, str] = {}
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk.startswith("diff --git"):
            continue
        file_path: str | None = None
        for line in chunk.splitlines():
            if line.startswith("+++ b/"):
                file_path = line[6:]
                break
        if file_path is None:
            for line in chunk.splitlines():
                if line.startswith("--- a/"):
                    file_path = line[6:]
                    break
        if file_path is None:
            match = re.match(r"diff --git a/(.+?) b/(.+)", chunk.splitlines()[0])
            if match:
                file_path = (
                    match.group(2) if match.group(2) != "/dev/null" else match.group(1)
                )
        if not file_path:
            continue
        key = file_path.replace("\\", "/")
        result[key] = chunk if chunk.endswith("\n") else f"{chunk}\n"
    return result

class ReviewEngine:
    """Coordinates the PR review workflow across dedicated services."""

    def __init__(
        self,
        git_service: GitServicePort,
        github_service: GitHubServicePort,
        parser_service: ParserServicePort,
        indexer_service: IndexerServicePort,
        retrieval_service: RetrievalServicePort,
        ai_service: AIServicePort,
        logger: "Logger",
        *,
        graph_service: RepositoryGraphServicePort,
        prompt_builder: PromptBuilderPort,
        ai_gateway: AIGatewayPort,
        response_parser: ResponseParserPort,
        budget: ContextBudget | None = None,
        persistence_service: "PersistenceService | None" = None,
        company_rules_checker: "CompanyRulesChecker | None" = None,
    ) -> None:
        self._git = git_service
        self._github = github_service
        self._parser = parser_service
        self._indexer = indexer_service
        self._retrieval = retrieval_service
        self._ai = ai_service
        self._graph = graph_service
        self._prompt_builder = prompt_builder
        self._gateway = ai_gateway
        self._response_parser = response_parser
        self._budget = budget or ContextBudget()
        self._logger = logger
        self._persistence = persistence_service
        self._company_rules = company_rules_checker

    def build_prompt(self, review_target: int) -> PromptRequest:
        """Run the review pipeline through PromptBuilder only (no AI calls).

        Used by ``review()`` and the developer ``refactory prompt`` CLI.
        """
        repository = self._git.require_repository()
        with review_logging_context(
            repository=repository.name,
            review_id=f"pr-{review_target}",
            provider=getattr(self._gateway, "provider_name", None),
            model=getattr(self._gateway, "model", None),
            request_id=new_request_id(),
        ):
            return self._build_prompt_impl(review_target, repository=repository)

    def review(
        self,
        pr_number: int,
        *,
        base_branch: str | None = None,
        head_ref: str | None = None,
    ) -> ReviewResult:
        """Orchestrate a PR-scoped pull request review end-to-end.

        Local reviews use committed ``base...head`` diffs only. The working tree
        never contaminates PR scope. Empty diffs short-circuit without AI.
        """
        repository = self._git.require_repository()
        with review_logging_context(
            repository=repository.name,
            review_id=f"pr-{pr_number}",
            provider=getattr(self._gateway, "provider_name", None),
            model=getattr(self._gateway, "model", None),
            request_id=new_request_id(),
        ):
            bind_context(
                self._logger,
                repository=repository.name,
                review_id=f"pr-{pr_number}",
                provider=getattr(self._gateway, "provider_name", None),
                model=getattr(self._gateway, "model", None),
            ).info("Starting review orchestration for PR #{}", pr_number)

            started = time.perf_counter()
            pull_request = self._resolve_pull_request(
                repository,
                pr_number,
                base_branch=base_branch,
                head_ref=head_ref,
            )
            root = Path(repository.root_path)

            # Empty PR diff → succeed with zero suggestions (never call AI / index).
            if not pull_request.changed_files and not (pull_request.diff or "").strip():
                elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
                result = self._empty_pr_review_result(
                    pr_number, pull_request, elapsed_ms=elapsed_ms
                )
                self._persist_review(repository, result)
                self._logger.info(
                    "[review] PR #{} repository={} base={}/{} head={}/{} "
                    "changed_files=0 paths=[] — no changes to review",
                    pr_number,
                    repository.name,
                    pull_request.base_branch,
                    (result.metadata or {}).get("base_sha"),
                    pull_request.head_branch,
                    (result.metadata or {}).get("head_sha"),
                )
                return result

            gate = self._run_company_rules_gate(root, pull_request)
            if gate is not None and gate.outcome.value == "block":
                elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
                self._logger.warning(
                    "Review BLOCKED by company rules for PR #{} — {} blocker(s)",
                    pr_number,
                    len(gate.blockers),
                )
                result = self._blocked_review_result(
                    pr_number, gate, elapsed_ms=elapsed_ms
                )
                self._persist_review(repository, result)
                self._persist_gate_result(
                    repository, gate,
                    branch=pull_request.head_branch or "",
                    elapsed_ms=elapsed_ms,
                )
                return result

            prompt = self._build_prompt_impl(
                pr_number,
                repository=repository,
                pull_request=pull_request,
                company_documentation=(
                    gate.guidelines.combined_for_prompt() if gate is not None else None
                ),
                gate_warnings=gate.warnings if gate is not None else [],
            )

            # Local import avoids ai ↔ prompt ↔ review package init cycles.
            from refactory.ai.models import AIRequest

            ai_request = AIRequest.from_prompt_request(prompt)
            ai_response = self._gateway.generate(ai_request)
            parsed = self._response_parser.parse_response(ai_response)
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
            cache_hit = getattr(self._gateway, "last_cache_hit", None)

            result = self._to_engine_result(
                pr_number,
                parsed,
                ai_response=ai_response,
                cache_hit=cache_hit if isinstance(cache_hit, bool) else None,
                elapsed_ms=elapsed_ms,
                pull_request=pull_request,
            )
            if gate is not None and gate.warnings:
                result.warnings = list(result.warnings) + [
                    f"[company:{w.rule}] {w.message}" for w in gate.warnings
                ]
            bind_context(
                self._logger,
                repository=repository.name,
                review_id=f"pr-{pr_number}",
                provider=ai_response.provider,
                model=ai_response.model,
                severity=result.risk_level,
            ).info(
                "Review complete for PR #{} — risk={}, suggestions={}, confidence={}",
                pr_number,
                result.risk_level,
                len(result.suggestions),
                result.confidence,
            )

            self._persist_review(repository, result)
            if gate is not None:
                self._persist_gate_result(
                    repository, gate,
                    branch=pull_request.head_branch or "",
                    elapsed_ms=elapsed_ms,
                )

            return result

    def _empty_pr_review_result(
        self,
        pr_number: int,
        pull_request: PullRequest,
        *,
        elapsed_ms: float,
    ) -> ReviewResult:
        head_sha = None
        base_sha = None
        get_head = getattr(self._git, "get_head_sha", None)
        if callable(get_head):
            try:
                head_sha = get_head()
            except Exception:  # noqa: BLE001
                head_sha = None
        resolve_base = getattr(self._git, "resolve_diff_base_ref", None)
        if callable(resolve_base) and pull_request.base_branch:
            try:
                base_ref = resolve_base(pull_request.base_branch)
                open_repo = getattr(self._git, "_open_repo", None)
                if callable(open_repo):
                    base_sha = open_repo().commit(base_ref).hexsha
            except Exception:  # noqa: BLE001
                base_sha = None
        return ReviewResult(
            pull_request_number=pr_number,
            summary="No changes to review",
            risk_level="low",
            suggestions=[],
            confidence=1.0,
            elapsed_ms=elapsed_ms,
            metadata={
                "scope": "pr",
                "empty_pr": True,
                "changed_files": [],
                "changed_file_count": 0,
                "base_branch": pull_request.base_branch,
                "head_branch": pull_request.head_branch,
                "base_sha": base_sha,
                "head_sha": head_sha,
            },
        )

    def _run_company_rules_gate(
        self, root: Path, pull_request: PullRequest
    ):
        """Run the pre-review company rules check. Returns None if checker unset."""
        if self._company_rules is None:
            return None
        try:
            from refactory.company.context import resolve_gate_context

            ctx = resolve_gate_context(
                self._git,
                pull_request=pull_request,
            )
            file_imports = self._collect_changed_file_imports(
                root, pull_request, changed_files=ctx.changed_files
            )
            return self._company_rules.check(
                root,
                branch_name=ctx.branch_name,
                commit_message=ctx.commit_message,
                commit_messages=ctx.commit_messages,
                changed_files=ctx.changed_files,
                pull_request=pull_request,
                file_imports=file_imports,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Company rules check failed (continuing review): {}", exc)
            return None

    def _collect_changed_file_imports(
        self,
        root: Path,
        pull_request: PullRequest,
        *,
        changed_files: list[str] | None = None,
    ) -> dict[str, list[str]]:
        """Best-effort import map for architecture checks on changed files."""
        if changed_files:
            paths = list(changed_files)
        else:
            paths = [f.path for f in pull_request.changed_files]

        imports: dict[str, list[str]] = {}
        for raw in paths[:50]:
            rel = raw.replace("\\", "/")
            path = root / rel
            if not path.is_file() or path.suffix != ".py":
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            found: list[str] = []
            for m in re.finditer(
                r"^(?:from\s+(\S+)\s+import|import\s+(\S+))", text, re.MULTILINE
            ):
                mod = m.group(1) or m.group(2) or ""
                # Map dotted imports to plausible path-ish targets for layer matching
                found.append(mod.replace(".", "/") + ".py")
                found.append(mod)
            if found:
                imports[rel] = found
        return imports

    def _blocked_review_result(
        self, pr_number: int, gate, *, elapsed_ms: float
    ) -> ReviewResult:
        from refactory.company.models import GateResult

        assert isinstance(gate, GateResult)
        suggestions = [
            ReviewSuggestion(
                title=f"Company rule: {v.rule}",
                detail=v.message + (f"\n{v.detail}" if v.detail else ""),
                severity="critical" if v.blocking else "medium",
                file_path=v.file_path or None,
                category="company_rules",
                confidence=1.0,
                suggested_fix=v.detail or "Fix the violation and re-run the review.",
                estimated_impact="Blocks AI review until resolved",
            )
            for v in gate.violations
        ]
        return ReviewResult(
            pull_request_number=pr_number,
            summary=gate.summary_text(),
            risk_level="blocked",
            suggestions=suggestions,
            confidence=1.0,
            elapsed_ms=elapsed_ms,
            warnings=[f"[company:{v.rule}] {v.message}" for v in gate.warnings],
            metadata={
                "company_rules": {
                    "outcome": gate.outcome.value,
                    "blockers": len(gate.blockers),
                    "warnings": len(gate.warnings),
                }
            },
        )

    def _persist_review(self, repository: "Repository", result: ReviewResult) -> None:
        """Persist a completed review to the relational database.

        Never raises — persistence failures are logged but never abort
        the review pipeline.
        """
        if self._persistence is None:
            return

        persist_start = time.perf_counter()
        try:
            repo_data = self._persistence.get_or_create_repository(
                name=repository.name,
                root_path=repository.root_path,
                default_branch=repository.default_branch or "main",
                remote_url=repository.remote_url,
            )

            suggestions = [
                {
                    "file": s.file_path,
                    "line": s.line,
                    "severity": s.severity,
                    "category": s.category,
                    "title": s.title,
                    "explanation": s.detail,
                    "suggested_fix": s.suggested_fix,
                    "confidence": s.confidence,
                    "estimated_impact": s.estimated_impact,
                }
                for s in result.suggestions
            ]

            review_data = self._persistence.persist_review(
                repository_id=repo_data["id"],
                pr_number=result.pull_request_number,
                provider=result.provider,
                model=result.model,
                risk=result.risk_level,
                confidence=result.confidence,
                summary=result.summary,
                suggestions=suggestions,
            )

            # History + Activity: full review result
            try:
                self._persistence.persist_analysis_run(
                    repository_id=repo_data["id"],
                    command="review",
                    result_type="review",
                    status="completed",
                    branch=repository.current_branch or None,
                    git_commit=getattr(repository, "head_sha", None),
                    duration_ms=round((time.perf_counter() - persist_start) * 1000.0, 3),
                    summary=(result.summary or "")[:500],
                    result_data={
                        "id": review_data["id"],
                        "summary": result.summary,
                        "risk_level": result.risk_level,
                        "confidence": result.confidence,
                        "suggestion_count": len(suggestions),
                        "pull_request_number": result.pull_request_number,
                        "scope": (result.metadata or {}).get("scope", "pr"),
                        "changed_files": (result.metadata or {}).get(
                            "changed_files", []
                        ),
                        "changed_file_count": (result.metadata or {}).get(
                            "changed_file_count", 0
                        ),
                        "empty_pr": bool((result.metadata or {}).get("empty_pr")),
                        "base_branch": (result.metadata or {}).get("base_branch"),
                        "head_branch": (result.metadata or {}).get("head_branch"),
                    },
                    metadata={"review_id": review_data["id"]},
                )
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("Review history persist skipped: {}", exc)

            persist_ms = round((time.perf_counter() - persist_start) * 1000.0, 3)
            self._logger.info(
                "Review persisted — repository={}, review_id={}, suggestion_count={}, elapsed_ms={}",
                repository.name,
                review_data["id"],
                len(suggestions),
                persist_ms,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.error(
                "Failed to persist review for repository={}: {}\n{}",
                repository.name,
                exc,
                _format_traceback(exc),
            )

    def _persist_gate_result(
        self,
        repository: "Repository",
        gate,
        *,
        branch: str = "",
        elapsed_ms: float = 0.0,
    ) -> None:
        """Persist a company-rules gate result as an analysis run.

        Never raises — persistence failures are logged but never abort
        the review pipeline.
        """
        if self._persistence is None:
            return

        from refactory.company.models import GateResult

        if not isinstance(gate, GateResult):
            return

        try:
            repo_data = self._persistence.get_or_create_repository(
                name=repository.name,
                root_path=repository.root_path,
                default_branch=repository.default_branch or "main",
                remote_url=repository.remote_url,
            )
            self._persistence.persist_analysis_run(
                repository_id=repo_data["id"],
                command="rules-check",
                result_type="company_rules",
                status=gate.outcome.value,
                branch=branch or None,
                duration_ms=elapsed_ms,
                result_data={
                    "outcome": gate.outcome.value,
                    "violations": [v.model_dump() for v in gate.violations],
                    "blocker_count": len(gate.blockers),
                    "warning_count": len(gate.warnings),
                    "summary": gate.summary_text(),
                },
            )
            self._logger.info(
                "Gate result persisted — repository={}, outcome={}, blockers={}, warnings={}",
                repository.name,
                gate.outcome.value,
                len(gate.blockers),
                len(gate.warnings),
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.error(
                "Failed to persist gate result for repository={}: {}",
                repository.name,
                exc,
            )

    def _build_prompt_impl(
        self,
        review_target: int,
        *,
        repository: "Repository",
        pull_request: PullRequest | None = None,
        coding_standards: str | None = None,
        company_documentation: str | None = None,
        gate_warnings: list | None = None,
    ) -> PromptRequest:
        bind_context(
            self._logger,
            repository=repository.name,
            review_id=f"pr-{review_target}",
        ).info(
            "Building review prompt for target #{} (no AI gateway)", review_target
        )

        root = Path(repository.root_path)

        if pull_request is None:
            pull_request = self._resolve_pull_request(repository, review_target)

        self._indexer.ensure_index(repository)
        index = self._indexer.load_index(root) or self._indexer.get_last_index()
        if index is None:
            self._logger.warning("Index unavailable after ensure_index; building force=False")
            self._indexer.index_repository(repository, force=False)
            index = self._indexer.load_index(root) or self._indexer.get_last_index()
        if index is None:
            raise RuntimeError(f"Failed to build or load repository index at {root}")

        graph = self._graph.build_graph(index)

        retrieval, related_files, impacted, ranked, cycles = self._gather_context(
            pull_request, root=root, index=index
        )

        prompt = self._prompt_builder.build(
            PromptContext(
                pull_request=pull_request,
                repository=repository,
                index=index,
                graph=graph,
                retrieval=retrieval,
                ranked_context=ranked,
                related_files=related_files,
                impacted_files=impacted,
                dependency_cycles=cycles,
                coding_standards=coding_standards or None,
                company_documentation=company_documentation or None,
                budget=self._budget,
            )
        )
        bind_context(
            self._logger,
            repository=repository.name,
            review_id=f"pr-{review_target}",
        ).info(
            "Prompt built for #{} — source={}, sections={}",
            review_target,
            prompt.metadata.template_source,
            len(prompt.sections),
        )
        return prompt

    # ------------------------------------------------------------------
    # Pull request resolution (GitHub when available, else local Git)
    # ------------------------------------------------------------------

    def _resolve_pull_request(
        self,
        repository: "Repository",
        pr_number: int,
        *,
        base_branch: str | None = None,
        head_ref: str | None = None,
    ) -> PullRequest:
        try:
            pull_request = self._github.fetch_pull_request(repository, pr_number)
            self._logger.info("Loaded pull request #{} from GitHubService", pr_number)
            return pull_request
        except NotImplementedError:
            self._logger.info(
                "GitHubService unavailable — synthesizing local PR-scoped target for #{}",
                pr_number,
            )
        except Exception as exc:  # noqa: BLE001 — local PR synthesis (no network)
            self._logger.warning(
                "GitHub fetch failed for #{} ({}): {}; synthesizing local PR diff",
                pr_number,
                type(exc).__name__,
                exc,
            )
        return self._synthesize_local_pull_request(
            repository,
            pr_number,
            base_branch=base_branch,
            head_ref=head_ref,
        )

    def _synthesize_local_pull_request(
        self,
        repository: "Repository",
        pr_number: int,
        *,
        base_branch: str | None = None,
        head_ref: str | None = None,
    ) -> PullRequest:
        """Build a PullRequest from local committed base...head diff only.

        Never includes working-tree / untracked / staged-only changes.
        Raises RefactoryError when base cannot be resolved — never falls back
        to repository-wide analysis.
        """
        from refactory.core.exceptions import RefactoryError

        git = self._git
        default_branch = (base_branch or repository.default_branch or "").strip()
        if not default_branch:
            get_default = getattr(git, "get_default_branch", None)
            if callable(get_default):
                try:
                    default_branch = (get_default() or "").strip()
                except Exception:  # noqa: BLE001
                    default_branch = ""
        if not default_branch:
            raise RefactoryError(
                "Unable to determine PR base branch for local review. "
                "Set a default branch (main/master) or pass base_branch."
            )

        head = (head_ref or "HEAD").strip() or "HEAD"
        head_branch = repository.current_branch

        resolve_base = getattr(git, "resolve_diff_base_ref", None)
        three_dot_files = getattr(git, "get_changed_files_three_dot", None)
        three_dot_diff = getattr(git, "get_unified_diff_three_dot", None)

        try:
            base_ref = (
                resolve_base(default_branch)
                if callable(resolve_base)
                else default_branch
            )
        except Exception as exc:  # noqa: BLE001
            raise RefactoryError(
                f"Unable to resolve PR base branch '{default_branch}': {exc}"
            ) from exc

        try:
            if callable(three_dot_files):
                changed_paths = list(three_dot_files(base_ref, head))
            else:
                # Legacy GitService without three-dot helper
                vs_default = getattr(git, "get_changed_files_vs_default_branch", None)
                changed_paths = list(vs_default()) if callable(vs_default) else []
        except Exception as exc:  # noqa: BLE001
            raise RefactoryError(
                f"Failed to compute PR diff {base_ref}...{head}: {exc}"
            ) from exc

        try:
            if callable(three_dot_diff):
                diff = three_dot_diff(base_ref, head) or ""
            else:
                get_diff = getattr(git, "get_unified_diff_vs_default_branch", None)
                diff = (get_diff() or "") if callable(get_diff) else ""
        except Exception as exc:  # noqa: BLE001
            raise RefactoryError(
                f"Failed to generate PR unified diff {base_ref}...{head}: {exc}"
            ) from exc

        patches = _split_unified_diff_by_path(diff)
        changed_files = [
            ChangedFile(
                path=item.path,
                status=item.kind.value if isinstance(item.kind, ChangeKind) else str(item.kind),
                patch=_lookup_file_patch(patches, item.path),
            )
            for item in changed_paths
        ]

        title = f"Local PR review #{pr_number}"
        body = (
            f"PR-scoped review of committed changes "
            f"({base_ref}...{head}). Working tree excluded."
        )
        commit = None
        get_commit = getattr(git, "get_current_commit", None)
        if callable(get_commit):
            try:
                commit = get_commit()
            except Exception:  # noqa: BLE001
                commit = None
        if commit is not None:
            message = (getattr(commit, "message", "") or "").strip()
            if message:
                title = message.splitlines()[0].strip() or title
                body = message

        head_sha = None
        get_head = getattr(git, "get_head_sha", None)
        if callable(get_head):
            try:
                head_sha = get_head()
            except Exception:  # noqa: BLE001
                head_sha = None
        base_sha = None
        try:
            open_repo = getattr(git, "_open_repo", None)
            if callable(open_repo):
                base_sha = open_repo().commit(base_ref).hexsha
        except Exception:  # noqa: BLE001
            base_sha = None

        paths = [cf.path for cf in changed_files]
        self._logger.info(
            "[review] PR #{} repository={} base={}/{} head={}/{} "
            "changed_files={} paths={}",
            pr_number,
            repository.name,
            default_branch,
            (base_sha or "")[:12],
            head_branch,
            (head_sha or "")[:12],
            len(paths),
            paths,
        )

        return PullRequest(
            number=pr_number,
            title=title,
            body=body,
            state="open",
            base_branch=default_branch,
            head_branch=head_branch,
            changed_files=changed_files,
            diff=diff,
        )

    def _local_changed_paths(self, git: object) -> list[ChangedPath]:
        """PR-scoped changed paths vs default branch (committed three-dot only).

        Intentionally does **not** fall back to the working tree.
        """
        three_dot = getattr(git, "get_changed_files_three_dot", None)
        get_default = getattr(git, "get_default_branch", None)
        resolve_base = getattr(git, "resolve_diff_base_ref", None)
        if callable(three_dot) and callable(get_default):
            try:
                default_branch = get_default()
                if not default_branch:
                    return []
                base_ref = (
                    resolve_base(default_branch)
                    if callable(resolve_base)
                    else default_branch
                )
                return list(three_dot(base_ref, "HEAD"))
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("Could not compute three-dot PR paths: {}", exc)
                return []

        vs_default = getattr(git, "get_changed_files_vs_default_branch", None)
        if callable(vs_default):
            try:
                return list(vs_default())
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("Could not diff vs default branch: {}", exc)
                return []
        return []

    # ------------------------------------------------------------------
    # Context gathering
    # ------------------------------------------------------------------

    def _gather_context(
        self,
        pull_request: PullRequest,
        *,
        root: Path,
        index: "RepositoryIndex",
    ) -> tuple[
        SearchResult | None,
        list[RetrievedFile],
        list[str],
        RankedContext | None,
        list[list[str]],
    ]:
        budget = self._budget
        query = self._retrieval_query(pull_request)

        ranked: RankedContext | None = None
        try:
            ranker = HybridRanker(self._retrieval, graph=self._graph)  # type: ignore[arg-type]
            ranked = ranker.rank(
                pull_request,
                query=query,
                root=root,
                top_k=max(budget.max_related_files, budget.max_retrieved_files),
                max_symbols=budget.max_symbols,
                max_graph_depth=budget.max_graph_depth,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Hybrid ranking skipped: {}", exc)

        retrieval: SearchResult | None = None
        if ranked is not None and ranked.symbols:
            from refactory.retrieval.models import SearchQuery

            retrieval = SearchResult(
                query=SearchQuery(text=query or ranked.query, top_k=len(ranked.symbols)),
                hits=list(ranked.symbols),
            )
        elif query:
            try:
                result = self._retrieval.search(
                    query, top_k=budget.max_symbols, root=root
                )
                if isinstance(result, SearchResult):
                    retrieval = result
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("Retrieval search skipped: {}", exc)

        related: list[RetrievedFile] = []
        if ranked is not None:
            related = [
                RetrievedFile(
                    file_path=entry.file_path,
                    module_name=entry.module_name,
                    score=entry.score,
                    metric="hybrid",
                    best_symbol=entry.best_symbol,
                    best_kind=entry.kind,
                )
                for entry in ranked.entries[: budget.max_related_files]
            ]
        else:
            related = self._legacy_related(pull_request, root=root)

        impacted: list[str] = []
        seen_impact: set[str] = set()
        for changed in pull_request.changed_files:
            try:
                for path in self._graph.affected_files(changed.path):
                    norm = path.replace("\\", "/")
                    if norm not in seen_impact:
                        seen_impact.add(norm)
                        impacted.append(norm)
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("affected_files({}) skipped: {}", changed.path, exc)
        impacted = impacted[: max(1, budget.max_retrieved_files * 2)]

        cycles: list[list[str]] = []
        try:
            find_cycles = getattr(self._graph, "find_cycles", None)
            if callable(find_cycles):
                cycles = [list(c.files) for c in find_cycles()[:5]]
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("cycle detection skipped: {}", exc)

        if not pull_request.changed_files:
            self._logger.info(
                "PR change set empty — skipping index/graph-only prompt expansion"
            )
            return None, [], [], None, []

        return retrieval, related, impacted, ranked, cycles

    def _legacy_related(
        self, pull_request: PullRequest, *, root: Path
    ) -> list[RetrievedFile]:
        related: list[RetrievedFile] = []
        seen: set[str] = set()
        try:
            context_paths = self._retrieval.retrieve_related_context(
                pull_request, top_k=self._budget.max_related_files, root=root
            )
        except Exception:  # noqa: BLE001
            context_paths = []
        for path in context_paths:
            norm = path.replace("\\", "/")
            if norm and norm not in seen:
                seen.add(norm)
                related.append(
                    RetrievedFile(
                        file_path=norm, module_name="", score=0.0, metric="cosine"
                    )
                )
        return related

    @staticmethod
    def _retrieval_query(pull_request: PullRequest) -> str:
        parts = [pull_request.title.strip()]
        if pull_request.body.strip():
            parts.append(pull_request.body.strip()[:400])
        for changed in pull_request.changed_files[:12]:
            parts.append(changed.path)
        return "\n".join(p for p in parts if p).strip()

    @staticmethod
    def _to_engine_result(
        pr_number: int,
        parsed: "ParsedReview",
        *,
        ai_response: Any | None = None,
        cache_hit: bool | None = None,
        elapsed_ms: float | None = None,
        pull_request: PullRequest | None = None,
    ) -> ReviewResult:
        suggestions = [
            ReviewSuggestion(
                title=item.title or "(untitled)",
                detail=_suggestion_detail(item.explanation, item.recommendation),
                severity=item.severity or "info",
                file_path=item.file,
                line=item.line,
                category=item.category,
                confidence=item.confidence if item.confidence is not None else _infer_confidence(item.severity),
                suggested_fix=item.recommendation or "",
                estimated_impact=item.estimated_impact or _infer_impact(item.category, item.severity),
            )
            for item in parsed.suggestions
        ]
        # Drop suggestions that point at files outside the PR change set.
        if pull_request is not None and pull_request.changed_files:
            allowed = {
                f.path.replace("\\", "/") for f in pull_request.changed_files if f.path
            }
            suggestions = [
                s
                for s in suggestions
                if not s.file_path
                or s.file_path.replace("\\", "/") in allowed
            ]

        confidence = parsed.confidence if parsed.confidence is not None else 0.0
        metadata: dict[str, Any] = {
            "scope": "pr",
            "source_format": parsed.metadata.source_format,
            "is_partial": bool(parsed.is_partial),
            "raw_length": parsed.metadata.raw_length,
        }
        if pull_request is not None:
            paths = [f.path for f in pull_request.changed_files]
            metadata["changed_files"] = paths
            metadata["changed_file_count"] = len(paths)
            metadata["base_branch"] = pull_request.base_branch
            metadata["head_branch"] = pull_request.head_branch
        if parsed.metadata.extra:
            metadata["parser_extra"] = parsed.metadata.extra

        provider = parsed.metadata.provider
        model = parsed.metadata.model
        latency_ms = None
        prompt_tokens = None
        completion_tokens = None
        estimated_cost_usd = None
        if ai_response is not None:
            provider = getattr(ai_response, "provider", None) or provider
            model = getattr(ai_response, "model", None) or model
            latency_ms = getattr(ai_response, "latency_ms", None)
            prompt_tokens = getattr(ai_response, "prompt_tokens", None)
            completion_tokens = getattr(ai_response, "completion_tokens", None)
            estimated_cost_usd = getattr(ai_response, "estimated_cost_usd", None)

        return ReviewResult(
            pull_request_number=pr_number,
            summary=parsed.summary,
            risk_level=parsed.overall_risk or "unknown",
            suggestions=suggestions,
            confidence=confidence,
            provider=provider,
            model=model,
            latency_ms=latency_ms,
            elapsed_ms=elapsed_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=estimated_cost_usd,
            cache_hit=cache_hit,
            warnings=list(parsed.warnings),
            metadata=metadata,
        )


def _suggestion_detail(explanation: str, recommendation: str) -> str:
    parts = [p for p in (explanation.strip(), recommendation.strip()) if p]
    return "\n\n".join(parts)


_SEVERITY_CONFIDENCE: dict[str, float] = {
    "critical": 0.90,
    "high": 0.80,
    "medium": 0.70,
    "low": 0.55,
    "info": 0.40,
}

_CATEGORY_IMPACT: dict[str, str] = {
    "security": "Security — potential vulnerability or credential exposure",
    "performance": "Performance — runtime or resource efficiency degradation",
    "correctness": "Correctness — logic error or incorrect behavior",
    "maintainability": "Maintainability — harder to understand, extend, or refactor",
    "tests": "Reliability — reduced test coverage or missing regression guard",
    "style": "Maintainability — inconsistent style reduces readability",
    "bug_risk": "Correctness — risk of runtime failure or data corruption",
    "documentation": "Maintainability — missing or misleading documentation",
}

_SEVERITY_IMPACT: dict[str, str] = {
    "critical": "Reliability — critical defect affecting production stability",
    "high": "Correctness — significant defect requiring immediate attention",
    "medium": "Maintainability — moderate issue affecting code quality",
    "low": "Maintainability — minor issue with limited immediate effect",
    "info": "Maintainability — informational observation",
}


def _infer_confidence(severity: str | None) -> float:
    """Derive per-finding confidence from severity when AI omits it."""
    return _SEVERITY_CONFIDENCE.get(severity or "info", 0.50)


def _infer_impact(category: str | None, severity: str | None) -> str:
    """Derive estimated_impact from category/severity when AI omits it."""
    if category:
        result = _CATEGORY_IMPACT.get(category.lower())
        if result:
            return result
    return _SEVERITY_IMPACT.get(severity or "info", "Maintainability — general code quality")


def _format_traceback(exc: Exception) -> str:
    """Format an exception traceback for logging."""
    import traceback

    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
