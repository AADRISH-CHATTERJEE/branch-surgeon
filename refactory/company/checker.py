"""Pre-review company rules checker — PASS / WARN / BLOCK."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from refactory.company.loader import (
    architecture_config_for_service,
    load_architecture_yaml,
    load_company_guidelines,
    load_company_standards,
)
from refactory.company.models import (
    CompanyRuleViolation,
    CompanyStandards,
    GateOutcome,
    GateResult,
)
from refactory.rules.engine import RuleContext
from refactory.rules.models import RuleSeverity

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.github.models import PullRequest
    from refactory.organization.service import OrganizationRuleService
    from refactory.policies.service import ArchitecturePolicyService
    from refactory.rules.engine import RuleEngine


class CompanyRulesChecker:
    """Evaluate built-in + company + organization rules before AI review."""

    def __init__(
        self,
        logger: "Logger",
        rule_engine: "RuleEngine",
        architecture_policy: "ArchitecturePolicyService | None" = None,
        organization_rule_service: "OrganizationRuleService | None" = None,
    ) -> None:
        self._logger = logger
        self._rules = rule_engine
        self._arch = architecture_policy
        self._org_rules = organization_rule_service
        self._organization_id: str | None = None
        self._team_id: str | None = None

    def set_organization_rule_service(
        self, service: "OrganizationRuleService | None"
    ) -> None:
        """Wire org-rules after construction (container bootstrap)."""
        self._org_rules = service

    def set_rule_scope(
        self,
        *,
        organization_id: str | None = None,
        team_id: str | None = None,
    ) -> None:
        """Set org/team scope for rule precedence (Phase 11.5)."""
        self._organization_id = organization_id
        self._team_id = team_id

    def check(
        self,
        repo_root: Path,
        *,
        branch_name: str = "",
        commit_message: str = "",
        commit_messages: list[str] | None = None,
        changed_files: list[str] | None = None,
        pull_request: "PullRequest | None" = None,
        file_imports: dict[str, list[str]] | None = None,
        file_contents: dict[str, str] | None = None,
        organization_id: str | None = None,
        team_id: str | None = None,
    ) -> GateResult:
        """Run all company + rules.yaml checks and return a gate result."""
        changed = list(changed_files or [])
        if pull_request is not None and not changed:
            changed = [f.path for f in pull_request.changed_files]
        if pull_request is not None:
            if not branch_name:
                branch_name = pull_request.head_branch or ""
            if not commit_message and not commit_messages:
                # Last-resort fallback when no git context was resolved
                commit_message = (pull_request.title or "").strip()

        messages = [m.strip() for m in (commit_messages or []) if m and m.strip()]
        if not messages and commit_message.strip():
            messages = [commit_message.strip()]
        primary_message = messages[0] if messages else commit_message.strip()

        proposed_contents = dict(file_contents or {})
        imports_map = dict(file_imports or {})
        if not imports_map and proposed_contents:
            imports_map = {
                path: self._extract_imports(text)
                for path, text in proposed_contents.items()
            }

        standards = load_company_standards(repo_root)
        guidelines = load_company_guidelines(repo_root)
        violations: list[CompanyRuleViolation] = []

        violations.extend(self._check_branch(standards, branch_name))
        violations.extend(self._check_commit(standards, messages))
        violations.extend(self._check_testing(standards, changed))
        violations.extend(
            self._check_architecture_company(standards, imports_map, repo_root)
        )
        violations.extend(self._check_architecture_yaml(repo_root, imports_map))
        org_id = organization_id if organization_id is not None else self._organization_id
        tid = team_id if team_id is not None else self._team_id
        violations.extend(
            self._check_rules_yaml(
                repo_root,
                branch_name=branch_name,
                commit_message=primary_message,
                commit_messages=messages,
                changed_files=changed,
                file_contents=proposed_contents or None,
                file_imports=imports_map or None,
                organization_id=org_id,
                team_id=tid,
            )
        )

        if any(v.blocking for v in violations):
            outcome = GateOutcome.BLOCK
        elif violations:
            outcome = GateOutcome.WARN
        else:
            outcome = GateOutcome.PASS

        self._logger.info(
            "Company rules check: outcome={}, violations={}, blockers={}",
            outcome.value,
            len(violations),
            sum(1 for v in violations if v.blocking),
        )
        return GateResult(
            outcome=outcome,
            violations=violations,
            guidelines=guidelines,
            standards=standards,
        )

    # ------------------------------------------------------------------
    # company.yaml checks
    # ------------------------------------------------------------------

    def _check_branch(
        self, standards: CompanyStandards, branch_name: str
    ) -> list[CompanyRuleViolation]:
        cfg = standards.branch
        if cfg is None or not cfg.pattern or not branch_name:
            return []
        if re.search(cfg.pattern, branch_name):
            return []
        msg = cfg.message or (
            f"Branch name must follow pattern: {cfg.pattern}\n"
            f"Current branch: {branch_name}"
        )
        return [
            CompanyRuleViolation(
                rule="branch_naming",
                message=msg,
                severity="error" if cfg.block else "warning",
                blocking=cfg.block,
                detail=f"Expected pattern: {cfg.pattern}",
            )
        ]

    def _check_commit(
        self, standards: CompanyStandards, commit_messages: list[str]
    ) -> list[CompanyRuleViolation]:
        cfg = standards.commit
        if cfg is None or not cfg.pattern or not commit_messages:
            return []

        failing: list[str] = []
        for raw in commit_messages:
            subject = raw.splitlines()[0].strip()
            if subject and not re.search(cfg.pattern, subject):
                failing.append(subject)

        if not failing:
            return []

        if len(failing) == 1:
            msg = cfg.message or (
                f"Commit message doesn't follow company convention.\n"
                f"Expected pattern: {cfg.pattern}\n"
                f"Got: {failing[0]}"
            )
            detail = f"Expected pattern: {cfg.pattern}"
        else:
            preview = "; ".join(f"'{s}'" for s in failing[:5])
            extra = f" (+{len(failing) - 5} more)" if len(failing) > 5 else ""
            msg = cfg.message or (
                f"{len(failing)} commit message(s) don't follow company convention.\n"
                f"Expected pattern: {cfg.pattern}\n"
                f"Failing: {preview}{extra}"
            )
            detail = f"Expected pattern: {cfg.pattern}; {len(failing)} failing"

        return [
            CompanyRuleViolation(
                rule="commit_message",
                message=msg,
                severity="error" if cfg.block else "warning",
                blocking=cfg.block,
                detail=detail,
            )
        ]

    def _check_testing(
        self, standards: CompanyStandards, changed_files: list[str]
    ) -> list[CompanyRuleViolation]:
        cfg = standards.testing
        if cfg is None or not cfg.require_tests or not changed_files:
            return []

        code_files = [
            f
            for f in changed_files
            if f.endswith(".py") and not re.search(cfg.test_path_pattern, f.replace("\\", "/"))
        ]
        test_files = [
            f
            for f in changed_files
            if re.search(cfg.test_path_pattern, f.replace("\\", "/"))
        ]
        if not code_files or test_files:
            return []

        msg = cfg.message or (
            "PR modifies production code without corresponding test changes.\n"
            f"Code files: {', '.join(code_files[:5])}"
        )
        return [
            CompanyRuleViolation(
                rule="require_tests",
                message=msg,
                severity="error" if cfg.block else "warning",
                blocking=cfg.block,
                detail="Add or update unit tests for the changed modules.",
            )
        ]

    def _check_architecture_company(
        self,
        standards: CompanyStandards,
        file_imports: dict[str, list[str]],
        repo_root: Path,
    ) -> list[CompanyRuleViolation]:
        cfg = standards.architecture
        if cfg is None or not cfg.forbidden_dependencies:
            return []

        # Prefer architecture.yaml layers for path→layer mapping when available
        arch_raw = load_architecture_yaml(repo_root) or {}
        layer_patterns = self._layer_patterns(arch_raw)
        if not layer_patterns:
            # Fall back to simple name-as-substring matching
            layer_patterns = {
                dep.from_layer: [f"*/{dep.from_layer}/*", f"{dep.from_layer}/*"]
                for dep in cfg.forbidden_dependencies
                if dep.from_layer
            }
            for dep in cfg.forbidden_dependencies:
                if dep.to_layer and dep.to_layer not in layer_patterns:
                    layer_patterns[dep.to_layer] = [
                        f"*/{dep.to_layer}/*",
                        f"{dep.to_layer}/*",
                    ]

        violations: list[CompanyRuleViolation] = []
        for source, imports in file_imports.items():
            src_layer = self._resolve_layer(source, layer_patterns)
            if not src_layer:
                continue
            for imp in imports:
                tgt_layer = self._resolve_layer(imp, layer_patterns)
                if not tgt_layer or tgt_layer == src_layer:
                    continue
                for dep in cfg.forbidden_dependencies:
                    if dep.from_layer == src_layer and dep.to_layer == tgt_layer:
                        msg = dep.message or (
                            f"Architecture violation: {src_layer} cannot access {tgt_layer}.\n"
                            f"{source} → {imp}"
                        )
                        violations.append(
                            CompanyRuleViolation(
                                rule="architecture",
                                message=msg,
                                severity="error" if cfg.block else "warning",
                                blocking=cfg.block,
                                file_path=source,
                                detail=f"{src_layer} → {tgt_layer}",
                            )
                        )
        return violations

    def _check_architecture_yaml(
        self, repo_root: Path, file_imports: dict[str, list[str]]
    ) -> list[CompanyRuleViolation]:
        if self._arch is None or not file_imports:
            return []
        raw = load_architecture_yaml(repo_root)
        if raw is None:
            return []
        try:
            config = architecture_config_for_service(raw)
            self._arch.load_policy_from_config(config)
            report = self._arch.evaluate(file_imports)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("Architecture YAML evaluation skipped: {}", exc)
            return []

        violations: list[CompanyRuleViolation] = []
        for v in report.violations:
            violations.append(
                CompanyRuleViolation(
                    rule="architecture",
                    message=v.description
                    or f"Architecture violation: {v.source_layer} → {v.target_layer}",
                    severity=v.severity or "error",
                    blocking=True,
                    file_path=v.source_file,
                    detail=f"{v.source_layer} → {v.target_layer}",
                )
            )
        return violations

    def _check_rules_yaml(
        self,
        repo_root: Path,
        *,
        branch_name: str,
        commit_message: str,
        commit_messages: list[str],
        changed_files: list[str],
        file_contents: dict[str, str] | None = None,
        file_imports: dict[str, list[str]] | None = None,
        organization_id: str | None = None,
        team_id: str | None = None,
    ) -> list[CompanyRuleViolation]:
        """Evaluate rules with precedence: org → team → repository rules.yaml.

        Built-in company checks run earlier in ``check()``. Repository
        ``rules.yaml`` is loaded last so repo policies refine org/team rules.
        """
        try:
            self._rules.clear_rules()
            org_count = 0
            if self._org_rules is not None:
                try:
                    org_rules = self._org_rules.enabled_as_rules(
                        organization_id=organization_id,
                        team_id=team_id,
                    )
                    self._rules.add_rules(org_rules)
                    org_count = len(org_rules)
                except Exception as exc:  # noqa: BLE001
                    self._logger.warning("Could not load organization rules: {}", exc)
            loaded = self._rules.load_rules(repo_root)
        except ValueError as exc:
            self._logger.warning("Could not load rules.yaml: {}", exc)
            return [
                CompanyRuleViolation(
                    rule="rules_yaml",
                    message=f"Invalid rules.yaml: {exc}",
                    severity="error",
                    blocking=True,
                    source="builtin",
                )
            ]
        if loaded == 0 and org_count == 0:
            return []

        contents: dict[str, str] = dict(file_contents or {})
        content_chunks: list[str] = list(contents.values())
        scan_paths = list(changed_files[:40])
        if not contents and not scan_paths:
            # Match organization rule preview: sample tracked sources when the
            # gate has no changed-file list (typical POST /rules/check body {}).
            for py in sorted(repo_root.rglob("*.py")):
                if any(
                    p in py.parts
                    for p in (".git", "node_modules", ".venv", "venv", "__pycache__")
                ):
                    continue
                try:
                    scan_paths.append(str(py.relative_to(repo_root)).replace("\\", "/"))
                except ValueError:
                    continue
                if len(scan_paths) >= 40:
                    break
        if not contents:
            for rel in scan_paths[:40]:
                path = repo_root / rel
                if path.is_file() and path.suffix in {".py", ".ts", ".tsx", ".js", ".jsx"}:
                    try:
                        text = path.read_text(encoding="utf-8", errors="replace")[
                            :50_000
                        ]
                        contents[rel] = text
                        content_chunks.append(text)
                    except OSError:
                        continue

        flat_imports: list[str] = []
        if file_imports:
            for path, imps in file_imports.items():
                for imp in imps:
                    flat_imports.append(str(imp))
                    flat_imports.append(f"{path}:{imp}")
        else:
            for path, text in contents.items():
                for imp in self._extract_imports(text):
                    flat_imports.append(imp)
                    flat_imports.append(f"{path}:{imp}")

        ctx = RuleContext(
            {
                "branch_name": branch_name,
                "commit_message": commit_message,
                "commit_messages": commit_messages,
                "changed_files": changed_files,
                "imports": flat_imports,
                "file_sizes": {},
                "function_sizes": {},
                "file_contents": contents,
                "content": "\n".join(content_chunks),
            }
        )

        result = self._rules.evaluate(ctx)
        out: list[CompanyRuleViolation] = []
        for v in result.violations:
            blocking = v.blocking or v.severity == RuleSeverity.BLOCKER
            out.append(
                CompanyRuleViolation(
                    rule=v.rule_name,
                    message=v.message,
                    severity=v.severity.value,
                    blocking=blocking,
                    file_path=v.file_path,
                    source=getattr(v, "source", None) or "builtin",
                    documentation_url=getattr(v, "documentation_url", None) or "",
                )
            )
        return out

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_imports(source: str) -> list[str]:
        """Best-effort import line extraction for architecture / forbidden-import rules."""
        out: list[str] = []
        for line in (source or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                out.append(stripped)
        return out

    @staticmethod
    def _layer_patterns(arch_raw: dict[str, Any]) -> dict[str, list[str]]:
        patterns: dict[str, list[str]] = {}
        for layer in arch_raw.get("layers") or []:
            if isinstance(layer, dict) and layer.get("name"):
                patterns[str(layer["name"])] = list(layer.get("patterns") or [])
        return patterns

    @staticmethod
    def _resolve_layer(path: str, layer_patterns: dict[str, list[str]]) -> str | None:
        normalized = path.replace("\\", "/")
        for name, patterns in layer_patterns.items():
            for pattern in patterns:
                # Convert glob-ish patterns to regex
                regex = (
                    pattern.replace(".", r"\.")
                    .replace("**/", "(.*/)?")
                    .replace("**", ".*")
                    .replace("*", "[^/]*")
                )
                if re.search(regex, normalized):
                    return name
                # Also try substring for simple layer names
                if name in normalized.split("/"):
                    return name
        return None
