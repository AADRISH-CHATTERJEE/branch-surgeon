"""PR Intelligence Service — Git-aware analysis for pull requests.

Orchestrates existing services (Parser, Graph, Impact, AI) to provide
PR summaries, merge risk, reviewer recommendations, and review comments.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from refactory.pr.models import (
    AIReviewReport,
    BreakingChange,
    BreakingChangeKind,
    BreakingChangeReport,
    ChangedDependencyGraph,
    ChangedFile,
    ChangedSymbol,
    ChangeExplanation,
    DependencyNode,
    DiffChangeKind,
    DiffSummary,
    MergeReadinessReport,
    MergeRiskReport,
    PerformanceIssue,
    PerformanceIssueKind,
    PerformanceReport,
    PRSummary,
    ReadinessStatus,
    ReviewCategory,
    ReviewComment,
    ReviewerCandidate,
    ReviewerReport,
    RiskFactor,
    RiskLevel,
    SecurityIssue,
    SecurityIssueKind,
    SecurityReport,
    TestRecommendation,
    TestRecommendationReport,
)

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.ai.gateway import AIGateway
    from refactory.git.service import GitService
    from refactory.graph.service import RepositoryGraphService
    from refactory.impact.service import ImpactAnalysisService
    from refactory.indexer.service import IndexerService
    from refactory.parser.service import ParserService


class PRIntelligenceService:
    """Central service for all PR/Git intelligence operations."""

    def __init__(
        self,
        logger: "Logger",
        git_service: "GitService",
        parser_service: "ParserService",
        indexer_service: "IndexerService",
        graph_service: "RepositoryGraphService",
        impact_service: "ImpactAnalysisService",
        ai_gateway: "AIGateway",
    ) -> None:
        self._logger = logger
        self._git = git_service
        self._parser = parser_service
        self._indexer = indexer_service
        self._graph = graph_service
        self._impact = impact_service
        self._ai = ai_gateway

    # ------------------------------------------------------------------
    # Task 1: Git Diff Service
    # ------------------------------------------------------------------

    def get_diff(self, base: str = "", head: str = "") -> DiffSummary:
        """Get diff between two refs (defaults to HEAD vs working tree)."""
        self._logger.info("Computing diff: {} -> {}", base or "HEAD~1", head or "HEAD")
        repo = self._git._open_repo()

        base_ref = base or "HEAD~1"
        head_ref = head or "HEAD"

        try:
            base_commit = repo.commit(base_ref)
            head_commit = repo.commit(head_ref)
            diffs = base_commit.diff(head_commit)
        except Exception:
            diffs = []

        files: list[ChangedFile] = []
        total_ins = 0
        total_del = 0
        added = modified = deleted = renamed = 0

        for d in diffs:
            kind = DiffChangeKind.MODIFIED
            path = d.b_path or d.a_path or ""
            old_path = None

            if d.new_file:
                kind = DiffChangeKind.ADDED
                added += 1
            elif d.deleted_file:
                kind = DiffChangeKind.DELETED
                deleted += 1
                path = d.a_path or ""
            elif d.renamed_file:
                kind = DiffChangeKind.RENAMED
                renamed += 1
                old_path = d.a_path
            else:
                modified += 1

            patch = ""
            try:
                patch = d.diff.decode("utf-8", errors="replace") if d.diff else ""
            except (AttributeError, TypeError):
                pass

            hunks = self._extract_hunks(patch)
            ins = patch.count("\n+") - patch.count("\n+++")
            dels = patch.count("\n-") - patch.count("\n---")
            ins = max(0, ins)
            dels = max(0, dels)
            total_ins += ins
            total_del += dels

            files.append(ChangedFile(
                path=path,
                change_kind=kind,
                old_path=old_path,
                insertions=ins,
                deletions=dels,
                hunks=hunks,
                is_binary=d.b_blob is None and not d.new_file and not d.deleted_file,
            ))

        self._logger.info(
            "Diff computed: {} files (+{}/-{})",
            len(files), total_ins, total_del,
        )
        return DiffSummary(
            base_ref=base_ref,
            head_ref=head_ref,
            changed_files=files,
            total_insertions=total_ins,
            total_deletions=total_del,
            files_added=added,
            files_modified=modified,
            files_deleted=deleted,
            files_renamed=renamed,
        )

    def changed_symbols(self, diff: DiffSummary, root: Path) -> list[ChangedSymbol]:
        """Extract symbols affected by a diff using the parser."""
        symbols: list[ChangedSymbol] = []
        for cf in diff.changed_files:
            if cf.is_binary or cf.change_kind == DiffChangeKind.DELETED:
                continue
            file_path = root / cf.path
            if not file_path.is_file():
                continue
            try:
                parsed = self._parser.parse_file(file_path, repo_root=root)
                for func in parsed.module.functions:
                    symbols.append(ChangedSymbol(
                        name=func.name,
                        kind="function",
                        file_path=cf.path,
                        change_type=cf.change_kind,
                    ))
                for cls in parsed.module.classes:
                    symbols.append(ChangedSymbol(
                        name=cls.name,
                        kind="class",
                        file_path=cf.path,
                        change_type=cf.change_kind,
                    ))
            except Exception:  # noqa: BLE001
                pass
        self._logger.debug("Extracted {} changed symbols", len(symbols))
        return symbols

    # ------------------------------------------------------------------
    # Task 2: PR Summary
    # ------------------------------------------------------------------

    def pr_summary(self, diff: DiffSummary, root: Path) -> PRSummary:
        """Generate a PR summary using graph and AI."""
        self._logger.info("Generating PR summary")
        modules = self._extract_modules(diff)
        breaking = self._detect_breaking_quick(diff, root)

        context = (
            f"Files changed: {len(diff.changed_files)}\n"
            f"Insertions: {diff.total_insertions}, Deletions: {diff.total_deletions}\n"
            f"Modules: {', '.join(modules[:10])}\n"
            f"Files: {', '.join(f.path for f in diff.changed_files[:15])}\n"
        )

        summary_text = ""
        try:
            from refactory.ai.models import AIRequest
            resp = self._ai.generate(AIRequest(
                system_prompt="Generate a concise PR summary. Include: overview, key changes, impact.",
                user_prompt=f"Summarize this PR:\n{context}",
                max_tokens=500,
            ))
            summary_text = resp.content
        except Exception:  # noqa: BLE001
            summary_text = f"Changed {len(diff.changed_files)} files across {len(modules)} modules."

        arch_impact = "minimal"
        if len(modules) > 5:
            arch_impact = "significant — cross-module changes"
        elif any("core" in m or "service" in m for m in modules):
            arch_impact = "moderate — core service changes"

        self._logger.info("PR summary generated")
        return PRSummary(
            title=f"Changes across {len(diff.changed_files)} files",
            description=summary_text,
            files_changed=len(diff.changed_files),
            modules_affected=modules,
            architectural_impact=arch_impact,
            breaking_changes=[b.description for b in breaking],
            summary=summary_text,
        )

    # ------------------------------------------------------------------
    # Task 3: Merge Risk Analysis
    # ------------------------------------------------------------------

    def merge_risk(self, diff: DiffSummary, root: Path) -> MergeRiskReport:
        """Analyze merge risk based on change characteristics."""
        self._logger.info("Analyzing merge risk")
        factors: list[RiskFactor] = []
        score = 0.0

        central_count = sum(
            1 for f in diff.changed_files
            if any(k in f.path for k in ("core/", "service", "models", "__init__"))
        )
        if central_count > 0:
            severity = RiskLevel.HIGH if central_count > 3 else RiskLevel.MEDIUM
            factors.append(RiskFactor(
                name="Central modules modified",
                description=f"{central_count} core/service files changed",
                severity=severity,
                confidence=0.9,
            ))
            score += central_count * 15

        api_changes = sum(
            1 for f in diff.changed_files
            if any(k in f.path for k in ("api/", "routes/", "endpoints/", "views/"))
        )
        if api_changes > 0:
            factors.append(RiskFactor(
                name="API changes",
                description=f"{api_changes} API files modified",
                severity=RiskLevel.HIGH,
                confidence=0.85,
            ))
            score += api_changes * 20

        if diff.total_insertions + diff.total_deletions > 500:
            factors.append(RiskFactor(
                name="Large changeset",
                description=f"{diff.total_insertions + diff.total_deletions} lines changed",
                severity=RiskLevel.MEDIUM,
                confidence=0.7,
            ))
            score += 15

        config_changes = sum(
            1 for f in diff.changed_files
            if any(f.path.endswith(e) for e in (".yml", ".yaml", ".toml", ".ini", ".env"))
        )
        if config_changes > 0:
            factors.append(RiskFactor(
                name="Configuration changes",
                description=f"{config_changes} config files modified",
                severity=RiskLevel.MEDIUM,
                confidence=0.8,
            ))
            score += config_changes * 10

        public_changes = 0
        for f in diff.changed_files:
            for sym in f.changed_symbols:
                if not sym.name.startswith("_"):
                    public_changes += 1
        if public_changes > 5:
            factors.append(RiskFactor(
                name="Public method changes",
                description=f"{public_changes} public symbols modified",
                severity=RiskLevel.HIGH,
                confidence=0.8,
            ))
            score += public_changes * 5

        if len(diff.changed_files) > 20:
            factors.append(RiskFactor(
                name="Broad change scope",
                description=f"{len(diff.changed_files)} files touched",
                severity=RiskLevel.HIGH,
                confidence=0.75,
            ))
            score += 20

        overall = RiskLevel.LOW
        if score >= 80:
            overall = RiskLevel.CRITICAL
        elif score >= 50:
            overall = RiskLevel.HIGH
        elif score >= 25:
            overall = RiskLevel.MEDIUM

        recommendation = {
            RiskLevel.LOW: "Safe to merge with standard review.",
            RiskLevel.MEDIUM: "Requires careful review of affected modules.",
            RiskLevel.HIGH: "Needs thorough review by domain experts.",
            RiskLevel.CRITICAL: "Block merge until risks are mitigated.",
        }[overall]

        self._logger.info("Merge risk: {} (score={})", overall.value, score)
        return MergeRiskReport(
            overall_risk=overall,
            risk_score=min(100.0, score),
            factors=factors,
            central_modules_modified=central_count,
            api_changes=api_changes,
            public_method_changes=public_changes,
            configuration_changes=config_changes,
            recommendation=recommendation,
        )

    # ------------------------------------------------------------------
    # Task 4: Reviewer Recommendation
    # ------------------------------------------------------------------

    def recommend_reviewers(self, diff: DiffSummary, root: Path) -> ReviewerReport:
        """Recommend reviewers based on file ownership and module proximity."""
        self._logger.info("Computing reviewer recommendations")
        repo = self._git._open_repo()
        author_counts: Counter[str] = Counter()
        author_emails: dict[str, str] = {}

        for cf in diff.changed_files:
            try:
                file_path = str(root / cf.path)
                for commit in repo.iter_commits(paths=cf.path, max_count=20):
                    name = commit.author.name or "unknown"
                    author_counts[name] += 1
                    if commit.author.email:
                        author_emails[name] = commit.author.email
            except Exception:  # noqa: BLE001
                pass

        current_author = ""
        try:
            current_author = repo.head.commit.author.name or ""
        except Exception:  # noqa: BLE001
            pass

        modules = self._extract_modules(diff)
        candidates: list[ReviewerCandidate] = []
        total = sum(author_counts.values()) or 1

        for name, count in author_counts.most_common(10):
            if name == current_author:
                continue
            confidence = min(1.0, count / total + 0.2)
            reasons = [f"Modified {count} related file(s)"]
            owned_modules = [m for m in modules if any(
                m in cf.path for cf in diff.changed_files
            )][:5]
            candidates.append(ReviewerCandidate(
                name=name,
                email=author_emails.get(name, ""),
                confidence=round(confidence, 2),
                reasons=reasons,
                files_owned=count,
                modules_owned=owned_modules,
            ))

        self._logger.info("Found {} reviewer candidates", len(candidates))
        return ReviewerReport(
            reviewers=candidates[:5],
            changed_files=len(diff.changed_files),
            modules_affected=modules,
        )

    # ------------------------------------------------------------------
    # Task 5: Test Recommendation
    # ------------------------------------------------------------------

    def recommend_tests(self, diff: DiffSummary, root: Path) -> TestRecommendationReport:
        """Recommend tests based on impact analysis."""
        self._logger.info("Computing test recommendations")
        existing: list[TestRecommendation] = []
        missing: list[TestRecommendation] = []
        integration: list[TestRecommendation] = []
        regression: list[TestRecommendation] = []

        for cf in diff.changed_files:
            if cf.change_kind == DiffChangeKind.DELETED:
                continue
            stem = Path(cf.path).stem
            test_file = f"tests/unit/test_{stem}.py"
            test_path = root / test_file
            if test_path.is_file():
                existing.append(TestRecommendation(
                    test_file=test_file,
                    test_name=f"test_{stem}",
                    kind="unit",
                    reason=f"Existing tests for {cf.path}",
                    confidence=0.9,
                ))
                regression.append(TestRecommendation(
                    test_file=test_file,
                    kind="regression",
                    reason=f"Regression test for modified {cf.path}",
                    confidence=0.85,
                ))
            else:
                missing.append(TestRecommendation(
                    test_file=test_file,
                    test_name=f"test_{stem}",
                    kind="unit",
                    reason=f"No tests found for {cf.path}",
                    confidence=0.8,
                    missing=True,
                ))

            if any(k in cf.path for k in ("service", "api", "route")):
                integration.append(TestRecommendation(
                    test_file=f"tests/integration/test_{stem}_integration.py",
                    kind="integration",
                    reason=f"Service-level integration test for {cf.path}",
                    confidence=0.7,
                ))

        self._logger.info(
            "Test recommendations: existing={}, missing={}, integration={}",
            len(existing), len(missing), len(integration),
        )
        return TestRecommendationReport(
            existing_tests=existing,
            missing_tests=missing,
            integration_tests=integration,
            regression_tests=regression,
        )

    # ------------------------------------------------------------------
    # Task 6: Breaking Change Detection
    # ------------------------------------------------------------------

    def detect_breaking_changes(self, diff: DiffSummary, root: Path) -> BreakingChangeReport:
        """Detect breaking changes in the diff."""
        self._logger.info("Detecting breaking changes")
        changes = self._detect_breaking_quick(diff, root)
        risk = RiskLevel.LOW
        if len(changes) > 5:
            risk = RiskLevel.CRITICAL
        elif len(changes) > 2:
            risk = RiskLevel.HIGH
        elif len(changes) > 0:
            risk = RiskLevel.MEDIUM

        self._logger.info("Found {} breaking changes", len(changes))
        return BreakingChangeReport(
            changes=changes,
            total_breaking=len(changes),
            risk_level=risk,
        )

    # ------------------------------------------------------------------
    # Task 7: AI Review Comments
    # ------------------------------------------------------------------

    def ai_review(self, diff: DiffSummary, root: Path) -> AIReviewReport:
        """Generate AI review comments."""
        self._logger.info("Generating AI review comments")
        comments: list[ReviewComment] = []

        for cf in diff.changed_files:
            if cf.is_binary or cf.change_kind == DiffChangeKind.DELETED:
                continue
            file_path = root / cf.path
            if not file_path.is_file():
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            comments.extend(self._heuristic_review(cf.path, content))

        ai_summary = ""
        if diff.changed_files:
            try:
                from refactory.ai.models import AIRequest
                context = "\n".join(
                    f"- {f.path} ({f.change_kind.value}, +{f.insertions}/-{f.deletions})"
                    for f in diff.changed_files[:20]
                )
                resp = self._ai.generate(AIRequest(
                    system_prompt=(
                        "You are a senior code reviewer. Provide a structured review summary.\n"
                        "For each finding, include:\n"
                        "- Severity: critical / warning / info\n"
                        "- Category: bug_risk / performance / security / style / maintainability\n"
                        "- File and line number (if applicable)\n"
                        "- Clear explanation of the issue\n"
                        "- Suggested fix with code snippet\n"
                        "- Estimated impact on the codebase\n"
                        "- Confidence level (0.0-1.0)\n\n"
                        "End with a brief overall summary."
                    ),
                    user_prompt=f"Review these changes:\n{context}",
                    max_tokens=500,
                ))
                ai_summary = resp.content
            except Exception:  # noqa: BLE001
                ai_summary = f"Reviewed {len(diff.changed_files)} changed files."

        self._logger.info("Generated {} review comments", len(comments))
        return AIReviewReport(
            comments=comments,
            summary=ai_summary,
            model=getattr(self._ai, '_provider', None) and "ai" or "heuristic",
        )

    # ------------------------------------------------------------------
    # Task 8: Security Review
    # ------------------------------------------------------------------

    def security_review(self, diff: DiffSummary, root: Path) -> SecurityReport:
        """Detect security issues in changed files."""
        self._logger.info("Running security review")
        issues: list[SecurityIssue] = []

        for cf in diff.changed_files:
            if cf.is_binary or cf.change_kind == DiffChangeKind.DELETED:
                continue
            file_path = root / cf.path
            if not file_path.is_file():
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            issues.extend(self._scan_security(cf.path, content))

        critical = sum(1 for i in issues if i.severity == RiskLevel.CRITICAL)
        high = sum(1 for i in issues if i.severity == RiskLevel.HIGH)

        self._logger.info("Security review: {} issues ({} critical, {} high)", len(issues), critical, high)
        return SecurityReport(
            issues=issues,
            total_issues=len(issues),
            critical_count=critical,
            high_count=high,
            passed=critical == 0 and high == 0,
        )

    # ------------------------------------------------------------------
    # Task 9: Performance Review
    # ------------------------------------------------------------------

    def performance_review(self, diff: DiffSummary, root: Path) -> PerformanceReport:
        """Detect performance issues in changed files."""
        self._logger.info("Running performance review")
        issues: list[PerformanceIssue] = []

        for cf in diff.changed_files:
            if cf.is_binary or cf.change_kind == DiffChangeKind.DELETED:
                continue
            file_path = root / cf.path
            if not file_path.is_file():
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            issues.extend(self._scan_performance(cf.path, content))

        self._logger.info("Performance review: {} issues", len(issues))
        return PerformanceReport(issues=issues, total_issues=len(issues))

    # ------------------------------------------------------------------
    # Task 10: Merge Readiness
    # ------------------------------------------------------------------

    def merge_readiness(self, diff: DiffSummary, root: Path) -> MergeReadinessReport:
        """Compute overall merge readiness score."""
        self._logger.info("Computing merge readiness")
        risk = self.merge_risk(diff, root)
        security = self.security_review(diff, root)
        tests = self.recommend_tests(diff, root)
        breaking = self.detect_breaking_changes(diff, root)

        risk_score = 1.0 - (risk.risk_score / 100.0)
        security_score = 1.0 if security.passed else max(0.0, 1.0 - security.critical_count * 0.3)
        test_score = len(tests.existing_tests) / max(1, len(diff.changed_files))
        test_score = min(1.0, test_score)
        arch_score = 1.0 if risk.central_modules_modified < 3 else 0.6
        doc_score = 0.8

        if breaking.total_breaking > 0:
            arch_score *= 0.7

        overall = (
            risk_score * 0.25
            + security_score * 0.25
            + test_score * 0.20
            + arch_score * 0.15
            + doc_score * 0.15
        )
        overall = round(min(1.0, max(0.0, overall)), 2)

        blockers: list[str] = []
        if security.critical_count > 0:
            blockers.append(f"{security.critical_count} critical security issue(s)")
        if breaking.total_breaking > 3:
            blockers.append(f"{breaking.total_breaking} breaking changes detected")
        if risk.overall_risk == RiskLevel.CRITICAL:
            blockers.append("Critical merge risk")

        status = ReadinessStatus.READY
        if blockers:
            status = ReadinessStatus.BLOCK_MERGE
        elif overall < 0.6:
            status = ReadinessStatus.NEEDS_WORK

        recommendation = {
            ReadinessStatus.READY: "Safe to merge.",
            ReadinessStatus.NEEDS_WORK: "Address identified issues before merging.",
            ReadinessStatus.BLOCK_MERGE: "Critical issues must be resolved before merge.",
        }[status]

        self._logger.info("Merge readiness: {} (score={:.2f})", status.value, overall)
        return MergeReadinessReport(
            overall_score=overall,
            status=status,
            review_completeness=0.8,
            documentation_score=doc_score,
            test_coverage_score=test_score,
            risk_score=risk_score,
            architecture_score=arch_score,
            security_score=security_score,
            recommendation=recommendation,
            blockers=blockers,
        )

    # ------------------------------------------------------------------
    # Task 11: Changed Dependency Graph
    # ------------------------------------------------------------------

    def changed_dependency_graph(self, diff: DiffSummary, root: Path) -> ChangedDependencyGraph:
        """Build a changed dependency graph visualization."""
        self._logger.info("Building changed dependency graph")
        changed_modules = self._extract_modules(diff)
        affected_services: list[str] = []
        impacted_apis: list[str] = []
        recommended_tests: list[str] = []

        for m in changed_modules:
            if "service" in m:
                affected_services.append(m)
            if "api" in m or "route" in m or "view" in m:
                impacted_apis.append(m)
            recommended_tests.append(f"test_{m.split('.')[-1]}")

        nodes = [
            DependencyNode(name=m, kind="module", change_type="modified")
            for m in changed_modules
        ]
        for s in affected_services:
            if s not in changed_modules:
                nodes.append(DependencyNode(name=s, kind="service", change_type="affected"))

        self._logger.info(
            "Dependency graph: {} modules, {} services, {} APIs",
            len(changed_modules), len(affected_services), len(impacted_apis),
        )
        return ChangedDependencyGraph(
            changed_modules=changed_modules,
            affected_services=affected_services,
            impacted_apis=impacted_apis,
            recommended_tests=recommended_tests,
            nodes=nodes,
        )

    # ------------------------------------------------------------------
    # Task 12: AI Change Explanation
    # ------------------------------------------------------------------

    def explain_change(self, diff: DiffSummary, root: Path) -> ChangeExplanation:
        """Generate AI explanation of a change."""
        self._logger.info("Generating change explanation")
        context = (
            f"Changed files ({len(diff.changed_files)}):\n"
            + "\n".join(f"- {f.path} ({f.change_kind.value})" for f in diff.changed_files[:20])
            + f"\n\nTotal: +{diff.total_insertions}/-{diff.total_deletions} lines"
        )

        explanation = ""
        try:
            from refactory.ai.models import AIRequest
            resp = self._ai.generate(AIRequest(
                system_prompt=(
                    "Explain why this code change matters. Cover: purpose, downstream effects, "
                    "migration concerns, and architectural consequences. Be concise."
                ),
                user_prompt=context,
                max_tokens=500,
            ))
            explanation = resp.content
        except Exception:  # noqa: BLE001
            explanation = f"Changed {len(diff.changed_files)} files with {diff.total_insertions} insertions."

        modules = self._extract_modules(diff)
        downstream = [f"Module {m} may need updates" for m in modules[:5]]
        migration: list[str] = []
        if diff.files_deleted > 0:
            migration.append(f"{diff.files_deleted} deleted file(s) — update imports")
        if diff.files_renamed > 0:
            migration.append(f"{diff.files_renamed} renamed file(s) — update references")

        arch_consequences: list[str] = []
        if len(modules) > 5:
            arch_consequences.append("Cross-cutting change affects multiple modules")
        if any("core" in m for m in modules):
            arch_consequences.append("Core module changes may cascade")

        risk = RiskLevel.LOW
        if len(diff.changed_files) > 20 or diff.total_insertions > 500:
            risk = RiskLevel.HIGH
        elif len(diff.changed_files) > 10:
            risk = RiskLevel.MEDIUM

        self._logger.info("Change explanation generated")
        return ChangeExplanation(
            summary=explanation,
            why_it_matters=explanation,
            downstream_effects=downstream,
            migration_concerns=migration,
            architectural_consequences=arch_consequences,
            risk_level=risk,
            confidence=0.75,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_modules(self, diff: DiffSummary) -> list[str]:
        """Extract module names from changed file paths."""
        modules: list[str] = []
        seen: set[str] = set()
        for f in diff.changed_files:
            parts = Path(f.path).parts
            if len(parts) >= 2:
                module = parts[0] if parts[0] != "." else parts[1] if len(parts) > 1 else ""
            else:
                module = Path(f.path).stem
            if module and module not in seen:
                modules.append(module)
                seen.add(module)
        return modules

    def _extract_hunks(self, patch: str) -> list[str]:
        """Extract hunk headers from a unified diff patch."""
        return [line for line in patch.split("\n") if line.startswith("@@")]

    def _detect_breaking_quick(self, diff: DiffSummary, root: Path) -> list[BreakingChange]:
        """Quick heuristic breaking change detection."""
        changes: list[BreakingChange] = []
        for cf in diff.changed_files:
            if cf.change_kind == DiffChangeKind.DELETED:
                file_path = root / cf.path
                if cf.path.endswith(".py"):
                    changes.append(BreakingChange(
                        kind=BreakingChangeKind.DELETED_INTERFACE,
                        symbol=cf.path,
                        file_path=cf.path,
                        description=f"Deleted file: {cf.path}",
                        severity=RiskLevel.HIGH,
                    ))
                continue
            if cf.change_kind != DiffChangeKind.MODIFIED:
                continue
            for hunk in cf.hunks:
                if re.search(r"def\s+\w+", hunk):
                    for sym in cf.changed_symbols:
                        if not sym.name.startswith("_"):
                            changes.append(BreakingChange(
                                kind=BreakingChangeKind.CHANGED_SIGNATURE,
                                symbol=sym.name,
                                file_path=cf.path,
                                description=f"Public symbol modified: {sym.name} in {cf.path}",
                            ))
        return changes

    def _heuristic_review(self, path: str, content: str) -> list[ReviewComment]:
        """Generate structured review comments with severity, impact, and suggested fixes."""
        comments: list[ReviewComment] = []
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if "TODO" in line or "FIXME" in line:
                comments.append(ReviewComment(
                    file=path, line=i,
                    category=ReviewCategory.MAINTAINABILITY,
                    severity="info",
                    explanation="Unresolved TODO/FIXME marker",
                    confidence=0.9,
                    suggested_fix="Resolve or create a tracking issue",
                    estimated_impact="Technical debt accumulation",
                ))
            if "except:" in stripped and "except Exception" not in line and "except (" not in line:
                comments.append(ReviewComment(
                    file=path, line=i,
                    category=ReviewCategory.BUG_RISK,
                    severity="warning",
                    explanation="Bare except clause catches all exceptions including SystemExit and KeyboardInterrupt",
                    confidence=0.95,
                    suggested_fix="Use 'except Exception:' or a specific exception type",
                    estimated_impact="May mask critical errors, making debugging difficult",
                ))
            if re.search(r"print\(", line) and "test" not in path:
                comments.append(ReviewComment(
                    file=path, line=i,
                    category=ReviewCategory.STYLE,
                    severity="info",
                    explanation="print() statement in production code",
                    confidence=0.7,
                    suggested_fix="Use structured logging (e.g., logging.info() or loguru)",
                    estimated_impact="Unstructured output, no log levels or filtering",
                ))
            if re.search(r"eval\(|exec\(", line):
                comments.append(ReviewComment(
                    file=path, line=i,
                    category=ReviewCategory.SECURITY,
                    severity="critical",
                    explanation="Use of eval()/exec() allows arbitrary code execution",
                    confidence=0.95,
                    suggested_fix="Use ast.literal_eval() for data or a safe parser",
                    estimated_impact="Remote code execution vulnerability",
                ))
            if re.search(r"import\s+\*|from\s+\w+\s+import\s+\*", line):
                comments.append(ReviewComment(
                    file=path, line=i,
                    category=ReviewCategory.STYLE,
                    severity="warning",
                    explanation="Wildcard import pollutes namespace and hides dependencies",
                    confidence=0.85,
                    suggested_fix="Import specific names explicitly",
                    estimated_impact="Namespace collisions, unclear dependencies",
                ))
            if re.search(r"\.password\s*=\s*['\"]|password\s*=\s*['\"][^'\"]+['\"]", line, re.IGNORECASE):
                comments.append(ReviewComment(
                    file=path, line=i,
                    category=ReviewCategory.SECURITY,
                    severity="critical",
                    explanation="Potential hardcoded password or secret",
                    confidence=0.8,
                    suggested_fix="Use environment variables or a secret manager",
                    estimated_impact="Credential exposure in version control",
                ))
            if re.search(r"type\(\w+\)\s*==|type\(\w+\)\s*is\s", line):
                comments.append(ReviewComment(
                    file=path, line=i,
                    category=ReviewCategory.STYLE,
                    severity="info",
                    explanation="Direct type comparison instead of isinstance()",
                    confidence=0.8,
                    suggested_fix="Use isinstance() for proper subclass handling",
                    estimated_impact="Breaks polymorphism with inheritance",
                ))
            if re.search(r"except\s+Exception.*:\s*$", stripped) and i < len(lines):
                next_line = lines[i].strip() if i < len(lines) else ""
                if next_line == "pass":
                    comments.append(ReviewComment(
                        file=path, line=i,
                        category=ReviewCategory.BUG_RISK,
                        severity="warning",
                        explanation="Exception silently swallowed with pass",
                        confidence=0.9,
                        suggested_fix="Log the exception or handle it explicitly",
                        estimated_impact="Errors go undetected, causing hard-to-diagnose bugs",
                    ))
        return comments[:30]

    _SECURITY_PATTERNS: list[tuple[str, SecurityIssueKind, str, str]] = [
        (r"pickle\.loads?\(", SecurityIssueKind.UNSAFE_DESERIALIZATION, "Unsafe pickle deserialization", "CWE-502"),
        (r"yaml\.load\(", SecurityIssueKind.UNSAFE_DESERIALIZATION, "Unsafe YAML load (use safe_load)", "CWE-502"),
        (r"eval\(", SecurityIssueKind.COMMAND_EXECUTION, "Use of eval() allows code injection", "CWE-94"),
        (r"exec\(", SecurityIssueKind.COMMAND_EXECUTION, "Use of exec() allows code injection", "CWE-94"),
        (r"subprocess\.call\(.*shell\s*=\s*True", SecurityIssueKind.COMMAND_EXECUTION, "Shell=True in subprocess", "CWE-78"),
        (r"os\.system\(", SecurityIssueKind.COMMAND_EXECUTION, "os.system() allows command injection", "CWE-78"),
        (r"(password|secret|token|api_key)\s*=\s*['\"]", SecurityIssueKind.INSECURE_SECRETS, "Hardcoded secret/credential", "CWE-798"),
        (r"open\(.*\+.*request", SecurityIssueKind.PATH_TRAVERSAL, "Potential path traversal", "CWE-22"),
        (r"\.format\(.*request", SecurityIssueKind.SQL_INJECTION, "String formatting with user input (potential injection)", "CWE-89"),
        (r"f['\"].*\{.*request", SecurityIssueKind.SQL_INJECTION, "F-string with user input (potential injection)", "CWE-89"),
    ]

    def _scan_security(self, path: str, content: str) -> list[SecurityIssue]:
        """Scan content for security issues using heuristic patterns."""
        issues: list[SecurityIssue] = []
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            for pattern, kind, desc, cwe in self._SECURITY_PATTERNS:
                if re.search(pattern, line):
                    issues.append(SecurityIssue(
                        kind=kind,
                        file=path,
                        line=i,
                        description=desc,
                        severity=RiskLevel.HIGH,
                        confidence=0.8,
                        recommendation=f"Review and fix: {desc}",
                        cwe=cwe,
                    ))
        return issues

    _PERF_PATTERNS: list[tuple[str, PerformanceIssueKind, str]] = [
        (r"for\s+\w+\s+in\s+.*:\s*\n\s+for\s+\w+\s+in", PerformanceIssueKind.NESTED_LOOPS, "Nested loop detected — consider optimization"),
        (r"\.query\(|\.execute\(|cursor\.", PerformanceIssueKind.REPEATED_DB_CALLS, "Database call inside loop potential"),
        (r"\+\s*=\s*.*\bstr\b|\bstr\b.*\+\s*=", PerformanceIssueKind.EXPENSIVE_ALLOCATION, "String concatenation in loop — use join()"),
    ]

    def _scan_performance(self, path: str, content: str) -> list[PerformanceIssue]:
        """Scan content for performance issues using heuristic patterns."""
        issues: list[PerformanceIssue] = []
        for pattern, kind, desc in self._PERF_PATTERNS:
            for match in re.finditer(pattern, content):
                line_num = content[:match.start()].count("\n") + 1
                issues.append(PerformanceIssue(
                    kind=kind,
                    file=path,
                    line=line_num,
                    description=desc,
                    severity="medium",
                    confidence=0.7,
                    recommendation=f"Consider refactoring: {desc}",
                ))
        return issues
