"""PromptBuilder — assemble concise, versioned review prompts (no LLM calls)."""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING, Callable

from refactory.backend.models import ReviewPrompt, ReviewWorkflow
from refactory.cache.keys import file_hashes_digest, prompt_cache_key
from refactory.cache.store import CacheStore, NullCache
from refactory.core.logger import bind_context
from refactory.prompt.budget import ContextBudget
from refactory.prompt.models import PromptContext, PromptMetadata, PromptRequest, PromptSection
from refactory.prompt.renderer import MarkdownRenderer
from refactory.prompt.templates import (
    DEFAULT_EXPECTED_JSON,
    DEFAULT_REVIEW_INSTRUCTIONS,
    DEFAULT_REVIEW_PROMPT,
    PROMPT_TEMPLATE_VERSION,
    SECTION_ORDER,
)

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.backend.client import BackendClient


TemplateResolver = Callable[[], ReviewPrompt | None]
BackendClientFactory = Callable[[], "BackendClient | None"]


class PromptBuilder:
    """Build ``PromptRequest`` from index/graph/retrieval/workflow/template inputs."""

    def __init__(
        self,
        logger: "Logger",
        *,
        renderer: MarkdownRenderer | None = None,
        backend_client: "BackendClient | None" = None,
        backend_client_factory: BackendClientFactory | None = None,
        template_resolver: TemplateResolver | None = None,
        default_budget: ContextBudget | None = None,
        cache: CacheStore | None = None,
    ) -> None:
        self._logger = logger
        self._renderer = renderer or MarkdownRenderer()
        self._backend_client = backend_client
        self._backend_client_factory = backend_client_factory
        self._template_resolver = template_resolver
        self._default_budget = default_budget or ContextBudget(
            template_version=PROMPT_TEMPLATE_VERSION
        )
        self._cache: CacheStore = cache or NullCache()

    def build(self, context: PromptContext) -> PromptRequest:
        """Assemble system + user prompts. Never calls an LLM."""
        budget = context.budget or self._default_budget
        template, source = self._resolve_template(context)
        workflow = self._resolve_workflow(context)
        # Prefer configured local version when using local default
        if source == "local_default":
            template = template.model_copy(
                update={"version": budget.template_version or template.version}
            )
        cache_key = self._prompt_key(
            context,
            budget,
            template.version,
            source,
            workflow_version=workflow.version if workflow is not None else "",
        )
        cached = self._cache.get(cache_key)
        if isinstance(cached, dict):
            request = PromptRequest.model_validate(cached)
            if self._cache_entry_is_usable(request, context):
                bind_context(
                    self._logger,
                    repository=request.metadata.repository_name or "-",
                    cache="hit",
                ).debug(
                    "Reused cached review prompt — source={}, version={}, sections={}",
                    request.metadata.template_source,
                    request.metadata.template_version,
                    len(request.sections),
                )
                return request

        repo_name = ""
        if context.repository is not None:
            repo_name = context.repository.name
        elif context.index is not None:
            repo_name = context.index.summary.repository_name

        sections = self._build_sections(context, budget)
        # Bind backend placeholders before budget estimate (system text affects size).
        system_prompt = self._render_system_prompt(
            template.template, context, sections, repo_name=repo_name
        )
        sections = self._apply_token_budget(system_prompt, sections, budget)
        # Re-bind after budget stubs so {{diff_summary}} matches final sections.
        system_prompt = self._render_system_prompt(
            template.template, context, sections, repo_name=repo_name
        )
        user_prompt = self._renderer.join_sections(sections)

        feature_flags: dict[str, bool] = {}
        if workflow is not None:
            feature_flags = dict(sorted(workflow.feature_flags.items()))
        meta_flags = template.metadata.get("feature_flags")
        if isinstance(meta_flags, dict):
            for key, value in sorted(meta_flags.items(), key=lambda i: str(i[0])):
                if isinstance(value, bool):
                    feature_flags.setdefault(str(key), value)

        ranked_count = (
            len(context.ranked_context.entries) if context.ranked_context is not None else 0
        )
        metadata = PromptMetadata(
            template_source=source,
            template_name=template.name,
            template_version=template.version,
            repository_name=repo_name,
            pr_number=context.pull_request.number,
            section_keys=[section.key for section in sorted(sections, key=lambda s: s.order)],
            feature_flags=feature_flags,
            extras={
                "workflow": self._renderer.workflow_notes(workflow),
                "prompt_version": template.version,
                "changed_file_count": len(context.pull_request.changed_files),
                "retrieval_hit_count": (
                    len(context.retrieval.hits) if context.retrieval is not None else 0
                ),
                "ranked_context_count": ranked_count,
                "related_file_count": len(context.related_files),
                "impacted_file_count": len(context.impacted_files),
                "estimated_tokens": ContextBudget.estimate_tokens(system_prompt + user_prompt),
                "budget": budget.model_dump(),
            },
        )

        request = PromptRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            metadata=metadata,
            sections=sorted(sections, key=lambda s: (s.order, s.key)),
        )
        self._cache.set(cache_key, request.model_dump(mode="json"))
        bind_context(
            self._logger,
            repository=repo_name or "-",
            cache="miss",
        ).info(
            "Built review prompt — template_source={}, version={}, workflow={}, sections={}, tokens~{}",
            source,
            template.version,
            metadata.extras.get("workflow") or "(none)",
            len(sections),
            metadata.extras.get("estimated_tokens"),
        )
        return request

    @staticmethod
    def _cache_entry_is_usable(request: PromptRequest, context: PromptContext) -> bool:
        """Reject stale cache entries that predate the Git Diff section."""
        keys = request.metadata.section_keys or []
        if "diff" not in keys:
            return False
        has_real_diff = bool((context.pull_request.diff or "").strip()) or any(
            bool(cf.patch and cf.patch.strip()) for cf in context.pull_request.changed_files
        )
        if has_real_diff and "diff --git" not in request.user_prompt:
            return False
        return True

    def _render_system_prompt(
        self,
        template_text: str,
        context: PromptContext,
        sections: list[PromptSection],
        *,
        repo_name: str,
    ) -> str:
        """Render system instructions, binding backend ``{{...}}`` placeholders."""
        rendered = self._bind_template_variables(
            template_text,
            self._template_variables(context, sections, repo_name=repo_name),
        )
        return self._renderer.system_instructions(rendered)

    def _template_variables(
        self,
        context: PromptContext,
        sections: list[PromptSection],
        *,
        repo_name: str,
    ) -> dict[str, str]:
        by_key = {section.key: section.body.strip() for section in sections}
        related = by_key.get("relevant_code", "")
        diff_summary = by_key.get("diff", "")
        if not diff_summary or diff_summary.startswith("_No git diff"):
            patches = [
                cf.patch.strip()
                for cf in context.pull_request.changed_files
                if cf.patch and cf.patch.strip()
            ]
            if patches:
                diff_summary = "\n\n".join(patches)
            else:
                diff_summary = (context.pull_request.diff or "").strip()
        return {
            "repository_name": repo_name or "repository",
            "pr_number": str(context.pull_request.number),
            "related_context": related,
            "diff_summary": diff_summary,
        }

    @staticmethod
    def _bind_template_variables(template_text: str, variables: dict[str, str]) -> str:
        rendered = template_text
        for key, value in variables.items():
            rendered = rendered.replace("{{" + key + "}}", value)
        # Leave unknown placeholders empty rather than sending literal braces to the model.
        return re.sub(r"\{\{[a-zA-Z0-9_]+\}\}", "", rendered)

    def _get_backend_client(self) -> "BackendClient | None":
        if self._backend_client is not None:
            return self._backend_client
        if self._backend_client_factory is not None:
            return self._backend_client_factory()
        return None

    def _prompt_key(
        self,
        context: PromptContext,
        budget: ContextBudget,
        prompt_version: str,
        template_source: str,
        *,
        workflow_version: str = "",
    ) -> str:
        file_hashes = (
            context.index.file_hashes if context.index is not None else {}
        )
        diff_text = context.pull_request.diff or ""
        patch_blob = "\n".join(
            cf.patch or "" for cf in context.pull_request.changed_files
        )
        fingerprint = {
            "related": [
                (f.file_path, round(float(f.score), 6), f.best_symbol or "")
                for f in context.related_files
            ],
            "impacted": list(context.impacted_files),
            "cycles": list(context.dependency_cycles),
            "retrieval": [
                (h.file_path, h.symbol, round(float(h.score), 6))
                for h in (context.retrieval.hits if context.retrieval else [])
            ],
            "ranked": [
                (e.file_path, round(float(e.score), 6), e.best_symbol or "")
                for e in (
                    context.ranked_context.entries if context.ranked_context else []
                )
            ],
            "graph_nodes": (
                context.graph.statistics.total_nodes if context.graph is not None else 0
            ),
            "pr_title": context.pull_request.title,
            "standards": context.coding_standards or "",
            "company_docs": context.company_documentation or "",
            "workflow_version": workflow_version,
            "section_layout": list(SECTION_ORDER),
            "diff_sha": hashlib.sha256(diff_text.encode("utf-8")).hexdigest()[:16],
            "patch_sha": hashlib.sha256(patch_blob.encode("utf-8")).hexdigest()[:16],
        }
        return prompt_cache_key(
            repository_hash=file_hashes_digest(file_hashes),
            prompt_version=prompt_version,
            pr_number=context.pull_request.number,
            changed_paths=[cf.path for cf in context.pull_request.changed_files],
            budget=budget.model_dump(mode="json"),
            template_source=template_source,
            context_fingerprint=fingerprint,
        )

    def _resolve_template(self, context: PromptContext) -> tuple[ReviewPrompt, str]:
        if context.prompt_template is not None:
            self._logger.info(
                "Using backend review prompt — name={}, version={} (context override)",
                context.prompt_template.name,
                context.prompt_template.version,
            )
            return context.prompt_template, "backend"

        if self._template_resolver is not None:
            resolved = self._template_resolver()
            if resolved is not None:
                self._logger.info(
                    "Using backend review prompt — name={}, version={} (resolver)",
                    resolved.name,
                    resolved.version,
                )
                return resolved, "backend"

        client = self._get_backend_client()
        if client is not None:
            try:
                fetched = client.get_review_prompt()
                if _version_lt(fetched.version, PROMPT_TEMPLATE_VERSION):
                    self._logger.info(
                        "Backend prompt version {} is older than local {}; using local default",
                        fetched.version,
                        PROMPT_TEMPLATE_VERSION,
                    )
                else:
                    self._logger.info(
                        "Using backend review prompt — name={}, version={}",
                        fetched.name,
                        fetched.version,
                    )
                    return fetched, "backend"
            except Exception as exc:  # noqa: BLE001 — fall back locally
                self._logger.warning(
                    "Backend review prompt unavailable ({}); using local default",
                    exc,
                )

        self._logger.info(
            "Using local_default review prompt — name={}, version={}",
            DEFAULT_REVIEW_PROMPT.name,
            DEFAULT_REVIEW_PROMPT.version,
        )
        return DEFAULT_REVIEW_PROMPT, "local_default"

    def _resolve_workflow(self, context: PromptContext) -> ReviewWorkflow | None:
        if context.workflow is not None:
            return context.workflow

        client = self._get_backend_client()
        if client is not None:
            try:
                fetched = client.get_review_workflow()
                self._logger.info(
                    "Using backend review workflow — name={}, version={}",
                    fetched.name,
                    fetched.version,
                )
                return fetched
            except Exception as exc:  # noqa: BLE001 — continue without workflow
                self._logger.warning(
                    "Backend review workflow unavailable ({}); continuing without workflow",
                    exc,
                )
        return None

    def _build_sections(
        self, context: PromptContext, budget: ContextBudget
    ) -> list[PromptSection]:
        renderer = self._renderer
        # coding_standards may override review instructions; company docs are separate.
        instructions = context.coding_standards or DEFAULT_REVIEW_INSTRUCTIONS
        company_docs = (context.company_documentation or "").strip()
        builders: dict[str, Callable[[], str]] = {
            "repository": lambda: renderer.repository(
                context.repository, context.index, context.graph
            ),
            "company_documentation": lambda: renderer.company_documentation(company_docs),
            "pr_summary": lambda: renderer.pr_summary(context.pull_request),
            "changed_files": lambda: renderer.changed_files(
                context.pull_request.changed_files
            ),
            "diff": lambda: renderer.git_diff(context.pull_request),
            "relevant_code": lambda: renderer.relevant_code(
                context.ranked_context,
                context.retrieval,
                context.related_files,
                max_files=budget.max_related_files,
                max_symbols=budget.max_symbols,
            ),
            "dependency_impact": lambda: renderer.dependency_impact(
                context.impacted_files[: max(1, budget.max_retrieved_files * 2)],
                max_files=budget.max_retrieved_files,
                cycles=context.dependency_cycles,
            ),
            "review_instructions": lambda: renderer.review_instructions(instructions),
            "expected_json_output": lambda: renderer.expected_json_output(
                DEFAULT_EXPECTED_JSON
            ),
        }

        sections: list[PromptSection] = []
        order = 0
        for key in SECTION_ORDER:
            if key == "repository":
                body = builders[key]()
                sections.append(renderer.render_section(key, body, order=order))
                order += 1
                # Insert company docs immediately after repository when present.
                if company_docs:
                    sections.append(
                        renderer.render_section(
                            "company_documentation",
                            builders["company_documentation"](),
                            order=order,
                        )
                    )
                    order += 1
                continue
            body = builders[key]()
            sections.append(renderer.render_section(key, body, order=order))
            order += 1
        return sections

    def _apply_token_budget(
        self,
        system_prompt: str,
        sections: list[PromptSection],
        budget: ContextBudget,
    ) -> list[PromptSection]:
        """Drop lowest-priority optional sections until under max_tokens."""
        # Priority: keep instructions + output + changed files; trim context/diff last.
        drop_order = ("relevant_code", "dependency_impact", "repository", "diff")
        current = list(sections)
        estimate = ContextBudget.estimate_tokens(
            system_prompt + self._renderer.join_sections(current)
        )
        if estimate <= budget.max_tokens:
            return current

        for key in drop_order:
            if estimate <= budget.max_tokens:
                break
            trimmed: list[PromptSection] = []
            for section in current:
                if section.key == key:
                    # Keep a one-line stub so structure remains
                    stub = section.model_copy(
                        update={"body": f"_Omitted to fit token budget ({key})._\n"}
                    )
                    trimmed.append(stub)
                else:
                    trimmed.append(section)
            current = trimmed
            estimate = ContextBudget.estimate_tokens(
                system_prompt + self._renderer.join_sections(current)
            )
        return current


def _version_lt(a: str, b: str) -> bool:
    """Return True if semver string *a* is strictly older than *b*."""
    def _parts(v: str) -> tuple[int, ...]:
        try:
            return tuple(int(x) for x in v.split("."))
        except (ValueError, AttributeError):
            return (0,)
    return _parts(a) < _parts(b)
