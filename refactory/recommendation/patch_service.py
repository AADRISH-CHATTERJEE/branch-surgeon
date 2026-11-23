"""Generate reusable AI patches for persisted recommendations.

Orchestrates: load recommendation → resolve file context → LLM → unified diff → persist.
Reuses AIGateway, PromptTemplateService, PatchGenerator, and repository file reads.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from refactory.ai.models import AIRequest
from refactory.recommendation.patch_models import (
    FilePatchContent,
    PatchApplyError,
    PatchApplyResult,
    PatchGenerationError,
    RecommendationPatchResult,
)
from refactory.transformation.patch import PatchGenerator

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.ai.gateway import AIGateway
    from refactory.db.persistence import PersistenceService
    from refactory.db.query_service import RepositoryQueryService
    from refactory.company.checker import CompanyRulesChecker
    from refactory.graph.service import RepositoryGraphService
    from refactory.indexer.service import IndexerService
    from refactory.parser.service import ParserService
    from refactory.prompts import PromptTemplateService
    from refactory.recommendation.recommendation_service import RecommendationService

PROMPT_NAME = "recommendation_patch"
_PATH_RE = re.compile(
    r"(?:^|[\s`'\"(])([A-Za-z0-9_./\\-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|md))(?:$|[\s`'\")])"
)


class RecommendationPatchService:
    """End-to-end AI patch generation for existing recommendations only."""

    def __init__(
        self,
        *,
        logger: "Logger",
        ai_gateway: "AIGateway",
        prompt_service: "PromptTemplateService",
        query_service: "RepositoryQueryService",
        persistence_service: "PersistenceService",
        parser_service: "ParserService | None" = None,
        indexer_service: "IndexerService | None" = None,
        graph_service: "RepositoryGraphService | None" = None,
        company_rules_checker: "CompanyRulesChecker | None" = None,
        recommendation_service: "RecommendationService | None" = None,
    ) -> None:
        self._logger = logger
        self._ai = ai_gateway
        self._prompts = prompt_service
        self._query = query_service
        self._persistence = persistence_service
        self._parser = parser_service
        self._indexer = indexer_service
        self._graph = graph_service
        self._company_rules = company_rules_checker
        self._recommendation_service = recommendation_service
        self._patch_gen = PatchGenerator()
        self._ensure_prompt_template()

    def set_recommendation_service(self, service: "RecommendationService") -> None:
        """Wire RecommendationService after construction (container bootstrap)."""
        self._recommendation_service = service

    def generate_for_recommendation(
        self,
        recommendation_id: str,
        repo_root: Path,
    ) -> RecommendationPatchResult:
        """Generate, persist, and return a patch for an existing recommendation."""
        root = repo_root.resolve()
        repo = self._query.get_repository_by_root(str(root))
        if repo is None:
            raise PatchGenerationError(
                "No repository record yet — run index or recommend first."
            )

        rec = self._query.get_recommendation(recommendation_id)
        if rec is None or rec.get("repository_id") != repo["id"]:
            raise PatchGenerationError(
                f"Recommendation '{recommendation_id}' not found for this repository."
            )

        enriched = self._enrich_from_analysis(repo["id"], rec)
        target_files = self._resolve_target_files(enriched, root)
        if not target_files:
            raise PatchGenerationError(
                "Unable to generate patch — no target files could be resolved for "
                "this recommendation. Re-run recommend so analysis snapshots include "
                "affected_files, or ensure the description mentions a source file path."
            )

        file_contents: dict[str, str] = {}
        for rel in target_files:
            content = self._read_repo_file(root, rel)
            if content is None:
                self._logger.warning("Skipping missing file for patch: {}", rel)
                continue
            file_contents[rel] = content

        if not file_contents:
            raise PatchGenerationError(
                "Unable to generate patch — target files are missing on disk."
            )

        llm = self._call_llm(enriched, file_contents)
        patches = self._build_file_patches(file_contents, llm.get("patches") or [])
        if not patches:
            raise PatchGenerationError(
                "Unable to generate patch — model returned no usable file changes."
            )

        unified = self._build_unified_diff(patches)
        if not unified.strip():
            raise PatchGenerationError(
                "Unable to generate patch — model output produced an empty diff."
            )

        explanation = str(llm.get("explanation") or "").strip() or (
            f"AI patch for recommendation: {rec.get('title', recommendation_id)}"
        )
        try:
            confidence = float(llm.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        template = self._prompts.get(PROMPT_NAME)
        prompt_version = template.version if template else "1.0"
        model = str(llm.get("model") or "")
        provider = str(llm.get("provider") or "")

        result = RecommendationPatchResult(
            recommendation_id=recommendation_id,
            explanation=explanation,
            confidence=confidence,
            changed_files=[p.file_path for p in patches],
            unified_diff=unified,
            patches=patches,
            prompt_version=prompt_version,
            model=model,
            provider=provider,
            apply_available=True,
        )

        patch_id = self._persistence.persist_recommendation_patch(
            repository_id=repo["id"],
            recommendation_id=recommendation_id,
            payload={
                "explanation": result.explanation,
                "confidence": result.confidence,
                "changed_files": result.changed_files,
                "unified_diff": result.unified_diff,
                "patches": [p.model_dump() for p in result.patches],
                "prompt_version": result.prompt_version,
                "model": result.model,
                "provider": result.provider,
            },
        )
        result.id = patch_id
        try:
            self._persistence.persist_analysis_run(
                repository_id=repo["id"],
                command="patch",
                result_type="patch",
                status="completed",
                summary=(result.explanation or "Patch generated")[:500],
                result_data={
                    "patch_id": patch_id,
                    "recommendation_id": recommendation_id,
                    "changed_files": result.changed_files,
                    "confidence": result.confidence,
                },
                metadata={"patch_id": patch_id},
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("Patch history persist skipped: {}", exc)
        return result

    def list_patches(
        self, recommendation_id: str, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return previously persisted patches for a recommendation (reusable)."""
        return self._persistence.get_patches_for_recommendation(
            recommendation_id, limit=limit
        )

    def apply_patch(
        self,
        patch_id: str,
        repo_root: Path,
        *,
        dry_run: bool = False,
        applied_by: str = "local",
    ) -> PatchApplyResult:
        """Apply a stored patch via RecommendationService → PatchService → GitService."""
        if self._recommendation_service is None:
            raise PatchApplyError(
                "RecommendationService is not wired — cannot apply patches.",
                status_code=500,
            )
        return self._recommendation_service.apply_patch_by_id(
            patch_id,
            dry_run=dry_run,
            applied_by=applied_by,
            repo_root=repo_root.resolve(),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_prompt_template(self) -> None:
        if self._prompts.get(PROMPT_NAME) is not None:
            return
        from refactory.prompts import PromptTemplate

        self._prompts.register(
            PromptTemplate(
                name=PROMPT_NAME,
                category="patch",
                version="1.0.0",
                system_prompt=(
                    "You are a code refactoring expert. Generate minimal, correct "
                    "file modifications that address the recommendation. "
                    "Never invent repository files that were not provided. "
                    "Return JSON only."
                ),
                user_prompt_template="Generate a patch for:\n{context}",
                max_tokens=4000,
                temperature=0.2,
                description="Recommendation → AI patch (structured JSON)",
            )
        )

    def _enrich_from_analysis(
        self, repository_id: str, rec: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge slim DB row with rich snapshot fields when available."""
        enriched = dict(rec)
        analysis = self._query.get_latest_analysis(repository_id, command="recommend")
        if not analysis:
            return enriched
        data = analysis.get("result_data") or {}
        recommendations = data.get("recommendations") or []
        title = (rec.get("title") or "").strip()
        match = None
        for item in recommendations:
            if not isinstance(item, dict):
                continue
            if (item.get("title") or "").strip() == title:
                match = item
                break
        if match is None and title:
            for item in recommendations:
                if not isinstance(item, dict):
                    continue
                if title.lower() in (item.get("title") or "").lower():
                    match = item
                    break
        if match:
            enriched["affected_files"] = match.get("affected_files") or []
            enriched["affected_modules"] = match.get("affected_modules") or []
            enriched["transformation_type"] = match.get("transformation_type") or ""
            enriched["confidence"] = match.get("confidence", enriched.get("confidence"))
            expl = match.get("explanation") or {}
            if isinstance(expl, dict):
                enriched["reasoning"] = expl.get("why") or ""
            enriched["snapshot_id"] = match.get("id")
        return enriched

    def _resolve_target_files(
        self, rec: dict[str, Any], root: Path
    ) -> list[str]:
        files: list[str] = []
        for f in rec.get("affected_files") or []:
            if isinstance(f, str) and f.strip():
                files.append(f.replace("\\", "/").lstrip("./"))
        existing = self._dedupe_existing(files, root)[:5]
        if existing:
            return existing

        hay = f"{rec.get('title', '')}\n{rec.get('description', '')}\n{rec.get('reasoning', '')}"
        for match in _PATH_RE.finditer(hay):
            files.append(match.group(1).replace("\\", "/").lstrip("./"))
        existing = self._dedupe_existing(files, root)[:5]
        if existing:
            return existing

        # Last resort: scan repo for patterns implied by the recommendation
        # (e.g. "Rule violation: no-eval" → files containing eval().
        return self._discover_files_by_content(root, rec)[:5]

    def _discover_files_by_content(
        self, root: Path, rec: dict[str, Any]
    ) -> list[str]:
        patterns = self._content_patterns_for_recommendation(rec)
        if not patterns:
            return []
        hits: list[str] = []
        for py_file in sorted(root.rglob("*.py")):
            rel = str(py_file.relative_to(root)).replace("\\", "/")
            if any(
                part in rel.split("/")
                for part in (".git", ".venv", "venv", "node_modules", "__pycache__", ".refactory")
            ):
                continue
            try:
                text = py_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if any(p.search(text) for p in patterns):
                hits.append(rel)
            if len(hits) >= 5:
                break
        return hits

    @staticmethod
    def _content_patterns_for_recommendation(rec: dict[str, Any]) -> list[re.Pattern[str]]:
        title = str(rec.get("title") or "").lower()
        description = str(rec.get("description") or "").lower()
        hay = f"{title}\n{description}"
        patterns: list[re.Pattern[str]] = []

        if "no-eval" in hay or "eval()" in hay or re.search(r"\beval\b", hay):
            patterns.append(re.compile(r"\beval\s*\("))
        if "no-wildcard" in hay or "wildcard import" in hay:
            patterns.append(re.compile(r"from\s+\S+\s+import\s+\*"))
        if "pickle" in hay:
            patterns.append(re.compile(r"\bpickle\.(loads?|load)\s*\("))
        if "subprocess" in hay and ("shell=true" in hay or "shell true" in hay):
            patterns.append(re.compile(r"subprocess\.[a-z_]+\([^)]*shell\s*=\s*True"))

        # Title like "Rule violation: some-rule" — try bare identifier as code token.
        m = re.search(r"rule violation:\s*([a-z0-9_-]+)", title)
        if m and not patterns:
            token = m.group(1).replace("-", "_")
            if token not in {"max_function_length", "max_file_length"} and len(token) >= 3:
                patterns.append(re.compile(rf"\b{re.escape(token)}\b"))

        return patterns

    def _dedupe_existing(self, paths: list[str], root: Path) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for p in paths:
            key = p.replace("\\", "/")
            if key in seen:
                continue
            seen.add(key)
            if self._read_repo_file(root, key) is not None:
                out.append(key)
        return out

    @staticmethod
    def _read_repo_file(root: Path, relative: str) -> str | None:
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        if not candidate.is_file():
            return None
        try:
            return candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def _call_llm(
        self, rec: dict[str, Any], file_contents: dict[str, str]
    ) -> dict[str, Any]:
        context_parts = [
            f"Title: {rec.get('title', '')}",
            f"Description: {rec.get('description', '')}",
            f"Type: {rec.get('type', '')}",
            f"Priority: {rec.get('priority', '')}",
        ]
        if rec.get("reasoning"):
            context_parts.append(f"Reasoning: {rec['reasoning']}")
        if rec.get("transformation_type"):
            context_parts.append(f"Suggested transformation: {rec['transformation_type']}")

        for path, content in file_contents.items():
            clipped = content if len(content) <= 6000 else content[:6000] + "\n# ... truncated ..."
            context_parts.append(f"\n### File: {path}\n```\n{clipped}\n```")

        context = "\n".join(context_parts)
        template = self._prompts.get(PROMPT_NAME)
        system = (
            template.system_prompt
            if template
            else "You are a code refactoring expert. Return JSON only."
        )
        user = (
            "Given the recommendation and file contents, produce a minimal correct fix.\n"
            "Return ONLY valid JSON with this shape:\n"
            "{\n"
            '  "explanation": "why these changes address the recommendation",\n'
            '  "confidence": 0.0,\n'
            '  "patches": [\n'
            '    {"file_path": "relative/path.py", "modified": "full new file content"}\n'
            "  ]\n"
            "}\n"
            "Rules:\n"
            "- Only include files provided above.\n"
            "- modified must be the complete new file content.\n"
            "- Do not wrap the JSON in markdown fences.\n"
            "- Do not invent fake code unrelated to the recommendation.\n\n"
            f"{context}"
        )

        response = self._ai.generate(
            AIRequest(system_prompt=system, user_prompt=user)
        )
        parsed = self._parse_llm_json(response.text)
        parsed["model"] = response.model
        parsed["provider"] = response.provider
        return parsed

    def _parse_llm_json(self, text: str) -> dict[str, Any]:
        raw = (text or "").strip()
        if not raw:
            raise PatchGenerationError(
                "Unable to generate patch — empty model response."
            )
        if raw.startswith("```"):
            raw = re.sub(r"^```\w*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract the first JSON object
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                try:
                    data = json.loads(raw[start : end + 1])
                except json.JSONDecodeError as exc:
                    raise PatchGenerationError(
                        "Unable to generate patch — model response was not valid JSON."
                    ) from exc
            else:
                raise PatchGenerationError(
                    "Unable to generate patch — model response was not valid JSON."
                )
        if not isinstance(data, dict):
            raise PatchGenerationError(
                "Unable to generate patch — model response was not a JSON object."
            )
        return data

    def _build_file_patches(
        self,
        originals: dict[str, str],
        llm_patches: list[Any],
    ) -> list[FilePatchContent]:
        out: list[FilePatchContent] = []
        for item in llm_patches:
            if not isinstance(item, dict):
                continue
            path = str(item.get("file_path") or "").replace("\\", "/").lstrip("./")
            modified = item.get("modified")
            if not path or not isinstance(modified, str):
                continue
            if path not in originals:
                # Allow basename match
                matches = [k for k in originals if k.endswith("/" + path) or k == path]
                if len(matches) != 1:
                    continue
                path = matches[0]
            original = originals[path]
            if modified == original:
                continue
            out.append(
                FilePatchContent(
                    file_path=path,
                    original=original,
                    modified=modified,
                )
            )
        return out

    def _build_unified_diff(self, patches: list[FilePatchContent]) -> str:
        chunks: list[str] = []
        for p in patches:
            result = self._patch_gen.generate_from_content(
                p.file_path, p.original, p.modified
            )
            if result.diff_content.strip():
                chunks.append(result.diff_content.strip())
        return "\n\n".join(chunks) + ("\n" if chunks else "")

