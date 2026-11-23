"""Deterministic compact renderer for review prompt sections."""

from __future__ import annotations

from refactory.backend.models import ReviewWorkflow
from refactory.github.models import ChangedFile, PullRequest
from refactory.graph.models import RepositoryGraph
from refactory.indexer.models import RepositoryIndex
from refactory.prompt.models import PromptSection
from refactory.prompt.templates import SECTION_SEPARATOR, SECTION_TITLES
from refactory.retrieval.models import RankedContext, RetrievedFile, SearchResult
from refactory.review.models import Repository


class MarkdownRenderer:
    """Convert structured review context into compact delimited sections."""

    def render_section(self, key: str, body: str, *, order: int) -> PromptSection:
        title = SECTION_TITLES.get(key, key.replace("_", " ").title())
        return PromptSection(key=key, title=title, body=body.rstrip() + "\n", order=order)

    def join_sections(self, sections: list[PromptSection]) -> str:
        ordered = sorted(sections, key=lambda s: (s.order, s.key))
        blocks: list[str] = []
        for section in ordered:
            body = section.body.rstrip()
            if not body:
                continue
            blocks.append(
                f"{SECTION_SEPARATOR}\n"
                f"{section.title}\n"
                f"{SECTION_SEPARATOR}\n"
                f"\n"
                f"{body}"
            )
        return "\n\n".join(blocks).rstrip() + ("\n" if blocks else "")

    def system_instructions(self, template_text: str) -> str:
        return template_text.strip() + "\n"

    # ------------------------------------------------------------------
    # v2 section bodies
    # ------------------------------------------------------------------

    def repository(
        self,
        repository: Repository | None,
        index: RepositoryIndex | None,
        graph: RepositoryGraph | None,
    ) -> str:
        lines: list[str] = []
        if repository is not None:
            lines.append(f"- name: `{repository.name}`")
            lines.append(f"- branch: `{repository.current_branch}`")
            if repository.default_branch:
                lines.append(f"- default: `{repository.default_branch}`")
        if index is not None:
            s = index.summary
            lines.append(
                f"- index: files={s.total_indexed_files} fn={s.total_functions} "
                f"cls={s.total_classes} imports={s.total_imports}"
            )
            if s.languages:
                lang = ", ".join(
                    f"{k}={v}" for k, v in sorted(s.languages.items(), key=lambda i: i[0])
                )
                lines.append(f"- languages: {lang}")
        if graph is not None:
            st = graph.statistics
            lines.append(
                f"- graph: nodes={st.total_nodes} edges={st.total_edges} "
                f"cycles={st.cyclic_dependency_count} orphans={st.orphan_module_count}"
            )
        return "\n".join(lines) + "\n" if lines else "_No repository context._\n"

    def pr_summary(self, pull_request: PullRequest) -> str:
        lines = [
            f"- #{pull_request.number}: {pull_request.title}",
            f"- state: `{pull_request.state}`",
        ]
        if pull_request.author:
            lines.append(f"- author: `{pull_request.author}`")
        if pull_request.base_branch or pull_request.head_branch:
            lines.append(
                f"- branches: `{pull_request.base_branch or '?'}` ← `{pull_request.head_branch or '?'}`"
            )
        body = (pull_request.body or "").strip()
        if body:
            # Cap body to reduce tokens
            clipped = body if len(body) <= 600 else body[:600].rstrip() + "…"
            lines.append("- body:")
            for line in clipped.splitlines()[:20]:
                lines.append(f"  {line}")
        return "\n".join(lines) + "\n"

    def changed_files(self, files: list[ChangedFile]) -> str:
        if not files:
            return "_No changed files._\n"
        ordered = sorted(files, key=lambda f: f.path.replace("\\", "/"))
        lines = [
            f"- `{item.path.replace(chr(92), '/')}` ({item.status}"
            f"{f', +{item.additions}/-{item.deletions}' if item.additions or item.deletions else ''})"
            for item in ordered
        ]
        return "\n".join(lines) + "\n"

    def git_diff(self, pull_request: PullRequest) -> str:
        """Prefer per-file patches; fall back to the full unified diff."""
        patches = [
            (cf.path.replace("\\", "/"), cf.patch.strip())
            for cf in pull_request.changed_files
            if cf.patch and cf.patch.strip()
        ]
        if patches:
            ordered = sorted(patches, key=lambda item: item[0])
            body = "\n\n".join(patch for _, patch in ordered)
            return body.rstrip() + "\n"
        diff = (pull_request.diff or "").strip()
        if diff:
            return diff + "\n"
        return "_No git diff available._\n"

    def relevant_code(
        self,
        ranked: RankedContext | None,
        retrieval: SearchResult | None,
        related: list[RetrievedFile],
        *,
        max_files: int = 8,
        max_symbols: int = 16,
    ) -> str:
        lines: list[str] = []
        if ranked is not None and ranked.entries:
            lines.append("Files:")
            for entry in ranked.entries[:max_files]:
                reasons = ",".join(entry.reasons[:4]) if entry.reasons else "ranked"
                sym = f" `{entry.best_symbol}`" if entry.best_symbol else ""
                lines.append(
                    f"- `{entry.file_path}` score={entry.score:.3f} ({reasons}){sym}"
                )
            if ranked.symbols:
                lines.append("Symbols:")
                for hit in ranked.symbols[:max_symbols]:
                    path = hit.file_path.replace("\\", "/")
                    lines.append(
                        f"- `{hit.symbol}` ({hit.kind.value}) `{path}` {hit.score:.3f}"
                    )
            return "\n".join(lines) + "\n"

        # Fallback: legacy retrieval + related lists (deduped)
        seen: set[str] = set()
        if retrieval is not None:
            for hit in retrieval.hits[:max_symbols]:
                path = hit.file_path.replace("\\", "/")
                if path in seen:
                    continue
                seen.add(path)
                lines.append(f"- `{path}` `{hit.symbol}` {hit.score:.3f}")
        for item in sorted(related, key=lambda f: (-f.score, f.file_path))[:max_files]:
            path = item.file_path.replace("\\", "/")
            if path in seen:
                continue
            seen.add(path)
            lines.append(f"- `{path}` {item.score:.3f}")
        return "\n".join(lines) + "\n" if lines else "_No relevant code context._\n"

    def dependency_impact(
        self,
        impacted_paths: list[str],
        *,
        max_files: int = 12,
        cycles: list[list[str]] | None = None,
    ) -> str:
        lines: list[str] = []
        ordered = sorted({p.replace("\\", "/") for p in impacted_paths})[:max_files]
        if ordered:
            lines.append("Impacted:")
            lines.extend(f"- `{path}`" for path in ordered)
        if cycles:
            lines.append("Cycles:")
            for cycle in cycles[:5]:
                lines.append("- " + " → ".join(f"`{p}`" for p in cycle[:8]))
        return "\n".join(lines) + "\n" if lines else "_No dependency impact._\n"

    def review_instructions(self, text: str) -> str:
        return text.strip() + "\n"

    def company_documentation(self, text: str) -> str:
        return text.strip() + "\n"

    def expected_json_output(self, text: str) -> str:
        return text.strip() + "\n"

    # ------------------------------------------------------------------
    # Legacy aliases (keep older builder/tests working)
    # ------------------------------------------------------------------

    def repository_summary(
        self,
        repository: Repository | None,
        index: RepositoryIndex | None,
        graph: RepositoryGraph | None,
    ) -> str:
        return self.repository(repository, index, graph)

    def pull_request_metadata(self, pull_request: PullRequest) -> str:
        return self.pr_summary(pull_request)

    def retrieved_context(self, retrieval: SearchResult | None) -> str:
        return self.relevant_code(None, retrieval, [], max_files=8, max_symbols=16)

    def related_files(self, related: list[RetrievedFile]) -> str:
        return self.relevant_code(None, None, related, max_files=8, max_symbols=16)

    def impact_analysis(self, impacted_paths: list[str]) -> str:
        return self.dependency_impact(impacted_paths)

    def coding_standards(self, text: str) -> str:
        return self.review_instructions(text)

    def required_output_format(self, text: str) -> str:
        return self.expected_json_output(text)

    def workflow_notes(self, workflow: ReviewWorkflow | None) -> str:
        if workflow is None:
            return ""
        flags = ", ".join(
            f"{key}={str(value).lower()}"
            for key, value in sorted(workflow.feature_flags.items(), key=lambda i: i[0])
        )
        steps = ", ".join(step.id for step in workflow.steps)
        parts = [f"workflow={workflow.name}@{workflow.version}"]
        if flags:
            parts.append(f"flags={flags}")
        if steps:
            parts.append(f"steps={steps}")
        return "; ".join(parts)
