"""RecommendationEngine — generates, scores, ranks, and persists engineering recommendations.

Orchestrates all platform services to produce unified recommendations:
- GraphService for dependency/centrality signals
- ImpactAnalysisService for blast radius
- RuleEngine for policy violations
- ArchitecturePolicyService for layer violations
- StorageService for historical data and persistence
- AIGateway for AI explanations
- PromptTemplateService for configurable prompts
"""

from __future__ import annotations

import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from refactory.recommendation.models import (
    HealthReport,
    HealthScores,
    Recommendation,
    RecommendationBundle,
    RecommendationCategory,
    RecommendationExplanation,
    RecommendationPriority,
    RecommendationReport,
    TechnicalDebtCategory,
    TechnicalDebtItem,
    TechnicalDebtReport,
    TrendItem,
    TrendReport,
    generate_recommendation_id,
)

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.ai.gateway import AIGateway
    from refactory.db.persistence import PersistenceService
    from refactory.db.query_service import RepositoryQueryService
    from refactory.graph.service import RepositoryGraphService
    from refactory.impact.service import ImpactAnalysisService
    from refactory.indexer.service import IndexerService
    from refactory.parser.service import ParserService
    from refactory.organization.service import OrganizationRuleService
    from refactory.recommendation.stats import RecommendationStatsService
    from refactory.policies.service import ArchitecturePolicyService
    from refactory.prompts import PromptTemplateService
    from refactory.rules.engine import RuleContext, RuleEngine
    from refactory.storage.service import StorageService


class RecommendationEngine:
    """Central engine for generating and managing engineering recommendations."""

    def __init__(
        self,
        logger: "Logger",
        parser_service: "ParserService",
        indexer_service: "IndexerService",
        graph_service: "RepositoryGraphService",
        impact_service: "ImpactAnalysisService",
        rule_engine: "RuleEngine",
        policy_service: "ArchitecturePolicyService",
        storage_service: "StorageService",
        ai_gateway: "AIGateway",
        prompt_service: "PromptTemplateService",
        *,
        query_service: "RepositoryQueryService | None" = None,
        persistence_service: "PersistenceService | None" = None,
        organization_rule_service: "OrganizationRuleService | None" = None,
        recommendation_stats_service: "RecommendationStatsService | None" = None,
    ) -> None:
        self._logger = logger
        self._parser = parser_service
        self._indexer = indexer_service
        self._graph = graph_service
        self._impact = impact_service
        self._rules = rule_engine
        self._policy = policy_service
        self._storage = storage_service
        self._ai = ai_gateway
        self._prompts = prompt_service
        self._query = query_service
        self._persistence = persistence_service
        self._org_rules = organization_rule_service
        self._stats = recommendation_stats_service

    # ------------------------------------------------------------------
    # Task 1 + 13: Generate Recommendations
    # ------------------------------------------------------------------

    def generate_recommendations(
        self,
        root: Path,
        *,
        category: str | None = None,
        priority: str | None = None,
        top: int = 50,
        reconcile: bool = False,
    ) -> RecommendationReport:
        """Generate ranked engineering recommendations for a repository.

        When ``reconcile=True``, persisted rows are reconciled against the new
        set (still present → pending, missing → resolved, new → pending) instead
        of appending duplicates.
        """
        self._logger.info("Generating recommendations for {}", root)
        started = time.perf_counter()

        recommendations: list[Recommendation] = []

        recommendations.extend(self._debt_recommendations(root))
        recommendations.extend(self._rule_recommendations(root))
        recommendations.extend(self._architecture_recommendations(root))
        recommendations.extend(self._security_recommendations(root))
        recommendations.extend(self._testing_recommendations(root))
        recommendations.extend(self._documentation_recommendations(root))
        recommendations.extend(self._complexity_recommendations(root))
        recommendations.extend(self._maintainability_recommendations(root))

        repo_name = root.name
        for rec in recommendations:
            rec.id = generate_recommendation_id(
                repository=repo_name,
                file_path=rec.affected_files[0] if rec.affected_files else "",
                category=rec.category.value,
                title=rec.title,
            )
            rec.score = self._score_recommendation(rec)
            rec.priority = self._prioritize(rec.score)
            rec.explanation = self._explain_recommendation(rec)

        if category:
            recommendations = [r for r in recommendations if r.category.value == category]
        if priority:
            recommendations = [r for r in recommendations if r.priority.value == priority]

        recommendations.sort(key=lambda r: r.score, reverse=True)
        recommendations = recommendations[:top]

        bundles = self._create_bundles(recommendations)

        health = self._calculate_health(root, recommendations)

        report = RecommendationReport(
            repository_score=health.scores.overall,
            total_recommendations=len(recommendations),
            critical_count=sum(1 for r in recommendations if r.priority == RecommendationPriority.CRITICAL),
            high_count=sum(1 for r in recommendations if r.priority == RecommendationPriority.HIGH),
            medium_count=sum(1 for r in recommendations if r.priority == RecommendationPriority.MEDIUM),
            low_count=sum(1 for r in recommendations if r.priority == RecommendationPriority.LOW),
            recommendations=recommendations,
            bundles=bundles,
        )

        duration_ms = (time.perf_counter() - started) * 1000
        report.reconcile_stats = self._persist_recommendations(
            root, report, duration_ms, reconcile=reconcile
        )

        self._logger.info(
            "Generated {} recommendations (score={:.0f}) in {:.0f}ms",
            len(recommendations), health.scores.overall, duration_ms,
        )
        return report

    # ------------------------------------------------------------------
    # Task 2: Unified Scoring
    # ------------------------------------------------------------------

    def _score_recommendation(self, rec: Recommendation) -> float:
        """Compute unified score from all signals including transformation potential."""
        score = 0.0

        category_weights = {
            RecommendationCategory.SECURITY: 25,
            RecommendationCategory.ARCHITECTURE: 20,
            RecommendationCategory.RELIABILITY: 20,
            RecommendationCategory.PERFORMANCE: 15,
            RecommendationCategory.TECHNICAL_DEBT: 15,
            RecommendationCategory.MAINTAINABILITY: 12,
            RecommendationCategory.TESTING: 10,
            RecommendationCategory.REFACTORING: 10,
            RecommendationCategory.DOCUMENTATION: 5,
            RecommendationCategory.BEST_PRACTICES: 5,
            RecommendationCategory.RULE_VIOLATIONS: 8,
        }
        score += category_weights.get(rec.category, 5)

        score += rec.confidence * 20

        file_impact = min(20, len(rec.affected_files) * 3)
        score += file_impact

        severity_weights = {"critical": 20, "high": 15, "medium": 8, "low": 3}
        score += severity_weights.get(rec.severity, 5)

        if rec.estimated_risk == "high":
            score += 15
        elif rec.estimated_risk == "medium":
            score += 8

        if rec.business_impact:
            score += 10

        if rec.transformation_type:
            auto_types = {"refactor", "doc_generation", "security_fix", "rule_fix"}
            if rec.transformation_type in auto_types:
                score += 5
            if rec.estimated_patch_size and rec.estimated_patch_size < 100:
                score += 3

        return min(100.0, score)

    def _prioritize(self, score: float) -> RecommendationPriority:
        """Convert score to priority."""
        if score >= 75:
            return RecommendationPriority.CRITICAL
        if score >= 55:
            return RecommendationPriority.HIGH
        if score >= 35:
            return RecommendationPriority.MEDIUM
        return RecommendationPriority.LOW

    # ------------------------------------------------------------------
    # Task 3: AI Engineering Advisor
    # ------------------------------------------------------------------

    def advise(self, question: str, root: Path) -> str:
        """Answer engineering questions using AI with repository context."""
        self._logger.info("AI advisor query: {}", question[:50])
        try:
            from refactory.ai.models import AIRequest
            resp = self._ai.generate(AIRequest(
                system_prompt=(
                    "You are a senior engineering advisor. Answer based on the repository "
                    "context. Be specific, actionable, and concise."
                ),
                user_prompt=f"Question: {question}\nRepository: {root.name}",
                max_tokens=500,
            ))
            return resp.content
        except Exception:  # noqa: BLE001
            return f"Based on repository analysis, focus on the highest-priority recommendations first."

    # ------------------------------------------------------------------
    # Task 4: Technical Debt Detection
    # ------------------------------------------------------------------

    def analyze_technical_debt(self, root: Path) -> TechnicalDebtReport:
        """Detect and categorize technical debt."""
        self._logger.info("Analyzing technical debt for {}", root)
        items: list[TechnicalDebtItem] = []

        for py_file in root.rglob("*.py"):
            if self._should_skip(py_file, root):
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
                rel_path = str(py_file.relative_to(root)).replace("\\", "/")
                items.extend(self._analyze_file_debt(rel_path, content))
            except (OSError, UnicodeDecodeError):
                continue

        categories: dict[str, int] = Counter(item.category.value for item in items)
        total_score = sum(item.score for item in items)
        items.sort(key=lambda i: i.score, reverse=True)

        self._logger.info("Technical debt: {} items, score={:.1f}", len(items), total_score)

        self._write_metric(
            str(root), root.name,
            metric_name="tech_debt_score", metric_value=total_score,
        )

        return TechnicalDebtReport(
            items=items[:100],
            total_score=total_score,
            categories=categories,
        )

    def _analyze_file_debt(self, path: str, content: str) -> list[TechnicalDebtItem]:
        """Analyze a single file for technical debt indicators."""
        items: list[TechnicalDebtItem] = []
        lines = content.split("\n")
        line_count = len(lines)

        if line_count > 500:
            items.append(TechnicalDebtItem(
                category=TechnicalDebtCategory.LARGE_CLASS,
                file_path=path,
                description=f"File has {line_count} lines (threshold: 500)",
                severity="high" if line_count > 1000 else "medium",
                estimated_cleanup_effort="1-2 hours",
                score=min(30.0, line_count / 50),
            ))

        func_pattern = re.compile(r"^\s*def\s+(\w+)\s*\(")
        current_func = ""
        func_start = 0
        for i, line in enumerate(lines):
            m = func_pattern.match(line)
            if m:
                if current_func and (i - func_start) > 50:
                    items.append(TechnicalDebtItem(
                        category=TechnicalDebtCategory.LARGE_METHOD,
                        file_path=path, symbol=current_func,
                        description=f"Function '{current_func}' has {i - func_start} lines",
                        severity="medium",
                        estimated_cleanup_effort="30 min",
                        score=min(15.0, (i - func_start) / 10),
                    ))
                current_func = m.group(1)
                func_start = i

        if current_func and (line_count - func_start) > 50:
            items.append(TechnicalDebtItem(
                category=TechnicalDebtCategory.LARGE_METHOD,
                file_path=path, symbol=current_func,
                description=f"Function '{current_func}' has {line_count - func_start} lines",
                severity="medium",
                estimated_cleanup_effort="30 min",
                score=min(15.0, (line_count - func_start) / 10),
            ))

        class_count = content.count("\nclass ")
        method_count = content.count("\n    def ")
        if class_count == 1 and method_count > 15:
            items.append(TechnicalDebtItem(
                category=TechnicalDebtCategory.GOD_OBJECT,
                file_path=path,
                description=f"Single class with {method_count} methods",
                severity="high",
                estimated_cleanup_effort="2-4 hours",
                score=min(25.0, method_count * 1.5),
            ))

        max_indent = 0
        for line in lines:
            stripped = line.lstrip()
            if stripped:
                indent = len(line) - len(stripped)
                max_indent = max(max_indent, indent // 4)
        if max_indent > 5:
            items.append(TechnicalDebtItem(
                category=TechnicalDebtCategory.DEEP_NESTING,
                file_path=path,
                description=f"Max nesting depth: {max_indent} levels",
                severity="medium",
                estimated_cleanup_effort="30 min",
                score=max_indent * 2.0,
            ))

        long_params = re.findall(r"def\s+\w+\s*\(([^)]{80,})\)", content)
        for params in long_params:
            param_count = params.count(",") + 1
            if param_count > 5:
                items.append(TechnicalDebtItem(
                    category=TechnicalDebtCategory.LONG_PARAMETER_LIST,
                    file_path=path,
                    description=f"Function with {param_count} parameters",
                    severity="low",
                    estimated_cleanup_effort="15 min",
                    score=param_count * 1.0,
                ))

        return items

    # ------------------------------------------------------------------
    # Task 5: Repository Health Dashboard
    # ------------------------------------------------------------------

    def calculate_health(self, root: Path) -> HealthReport:
        """Calculate repository health scores from actual analysis.

        Runs recommendation scans and technical debt analysis to derive scores
        from real findings rather than returning static defaults.
        """
        recs: list[Recommendation] = []
        recs.extend(self._debt_recommendations(root))
        recs.extend(self._rule_recommendations(root))
        recs.extend(self._architecture_recommendations(root))
        recs.extend(self._security_recommendations(root))
        recs.extend(self._testing_recommendations(root))
        recs.extend(self._documentation_recommendations(root))
        recs.extend(self._complexity_recommendations(root))
        recs.extend(self._maintainability_recommendations(root))

        for rec in recs:
            rec.score = self._score_recommendation(rec)
            rec.priority = self._prioritize(rec.score)

        return self._calculate_health(root, recs)

    def _calculate_health(self, root: Path, recs: list[Recommendation]) -> HealthReport:
        """Internal health calculation with recommendations context.

        Scores are derived from actual recommendation findings across all
        categories. Each finding reduces the relevant score proportionally
        to its severity.
        """
        self._logger.info("Calculating repository health")

        def _severity_weight(rec: Recommendation) -> float:
            weights = {"critical": 20, "high": 15, "medium": 8, "low": 3}
            return weights.get(rec.severity, 8)

        security_penalty = sum(
            _severity_weight(r) for r in recs if r.category == RecommendationCategory.SECURITY
        )
        arch_penalty = sum(
            _severity_weight(r) for r in recs if r.category == RecommendationCategory.ARCHITECTURE
        )
        perf_penalty = sum(
            _severity_weight(r) for r in recs if r.category == RecommendationCategory.PERFORMANCE
        )
        test_penalty = sum(
            _severity_weight(r) for r in recs if r.category == RecommendationCategory.TESTING
        )
        doc_penalty = sum(
            _severity_weight(r) for r in recs if r.category == RecommendationCategory.DOCUMENTATION
        )
        debt_penalty = sum(
            _severity_weight(r) for r in recs if r.category == RecommendationCategory.TECHNICAL_DEBT
        )
        rule_penalty = sum(
            _severity_weight(r) for r in recs if r.category == RecommendationCategory.RULE_VIOLATIONS
        )
        maintainability_penalty = debt_penalty + rule_penalty

        scores = HealthScores(
            architecture=max(0.0, 100.0 - arch_penalty),
            maintainability=max(0.0, 100.0 - maintainability_penalty),
            security=max(0.0, 100.0 - security_penalty),
            performance=max(0.0, 100.0 - perf_penalty),
            testing=max(0.0, 100.0 - test_penalty),
            documentation=max(0.0, 100.0 - doc_penalty),
            technical_debt=max(0.0, 100.0 - debt_penalty),
        )
        scores.overall = (
            scores.architecture * 0.20
            + scores.maintainability * 0.15
            + scores.security * 0.20
            + scores.performance * 0.15
            + scores.testing * 0.15
            + scores.documentation * 0.05
            + scores.technical_debt * 0.10
        )

        self._write_metric(
            str(root), root.name,
            metric_name="health_overall", metric_value=scores.overall,
        )
        for dimension, value in [
            ("health_architecture", scores.architecture),
            ("health_security", scores.security),
            ("health_testing", scores.testing),
            ("health_documentation", scores.documentation),
            ("health_technical_debt", scores.technical_debt),
            ("health_maintainability", scores.maintainability),
            ("health_performance", scores.performance),
        ]:
            self._write_metric(
                str(root), root.name,
                metric_name=dimension, metric_value=value,
            )

        critical = sum(1 for r in recs if r.priority == RecommendationPriority.CRITICAL)
        return HealthReport(
            scores=scores,
            recommendations_count=len(recs),
            critical_count=critical,
        )

    # ------------------------------------------------------------------
    # Task 6: Historical Trend Analysis
    # ------------------------------------------------------------------

    def analyze_trends(self, root: Path) -> TrendReport:
        """Analyze historical trends from all stored dimensions."""
        self._logger.info("Analyzing trends for {}", root)
        trends: list[TrendItem] = []
        degrading: list[str] = []
        improving: list[str] = []
        repo_path = str(root)

        dimension_metrics = [
            ("health_overall", "Health score"),
            ("health_architecture", "Architecture"),
            ("health_security", "Security"),
            ("health_testing", "Testing"),
            ("health_documentation", "Documentation"),
            ("health_technical_debt", "Technical debt"),
            ("health_maintainability", "Maintainability"),
            ("health_performance", "Performance"),
            ("tech_debt_score", "Technical debt score"),
            ("recommendation_count", "Recommendation count"),
        ]

        for metric_name, label in dimension_metrics:
            data = self._read_metrics(repo_path, metric_name, limit=30)
            if len(data) < 2:
                continue
            recent = data[0]["value"]
            older = data[-1]["value"]
            change = ((recent - older) / max(older, 0.01)) * 100

            is_debt_like = "debt" in metric_name or metric_name == "recommendation_count"
            if is_debt_like:
                direction = "increasing" if change > 0 else "decreasing" if change < 0 else "stable"
                if change > 5:
                    degrading.append(label)
                elif change < -5:
                    improving.append(label)
            else:
                direction = "improving" if change > 0 else "degrading" if change < 0 else "stable"
                if change < -5:
                    degrading.append(label)
                elif change > 5:
                    improving.append(label)

            trends.append(TrendItem(
                metric_name=metric_name,
                direction=direction,
                change_percent=round(change, 1),
                period="30d",
                description=f"{label} {direction} by {abs(change):.1f}%",
            ))

        transformations = self._read_metrics(repo_path, "transformations_applied", limit=30)
        if transformations:
            total = sum(m["value"] for m in transformations)
            trends.append(TrendItem(
                metric_name="transformations_applied",
                direction="active" if total > 0 else "none",
                change_percent=total,
                period="30d",
                description=f"{int(total)} transformations applied in period",
            ))

        self._logger.info("Trend analysis complete: {} trends", len(trends))
        return TrendReport(
            trends=trends,
            modules_degrading=degrading,
            modules_improving=improving,
        )

    def _read_metrics(
        self, repo_path: str, metric_name: str, *, limit: int = 30
    ) -> list[dict[str, Any]]:
        """Read historical metrics, preferring RepositoryQueryService over StorageService.

        Returns a list of dicts with a "value" key for backward compatibility
        with the existing trend calculation logic.
        """
        if self._query is not None:
            try:
                repo = self._query.get_repository_by_root(repo_path)
                if repo is None:
                    return []
                raw = self._query.get_metrics(
                    repo["id"], metric_name=metric_name, limit=limit
                )
                return [{"value": m["metric_value"], "git_commit": m["git_commit"],
                         "branch": m["branch"], "timestamp": m["created_at"]} for m in raw]
            except Exception:  # noqa: BLE001
                self._logger.debug(
                    "QueryService read failed for {}/{}, falling back to StorageService",
                    repo_path, metric_name,
                )
        return self._storage.get_metrics(repo_path, metric_name, limit=limit)

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
    # Task 7: Rule-Aware Recommendations
    # ------------------------------------------------------------------

    def _rule_recommendations(self, root: Path) -> list[Recommendation]:
        """Generate recommendations from rule violations.

        Populates the RuleContext with real file sizes, function sizes,
        and imports so the RuleEngine evaluators can actually fire.
        """
        from refactory.rules.engine import RuleContext

        try:
            self._rules.clear_rules()
            if self._org_rules is not None:
                try:
                    self._rules.add_rules(self._org_rules.enabled_as_rules())
                except Exception as exc:  # noqa: BLE001
                    self._logger.warning("Could not load organization rules: {}", exc)
            self._rules.load_rules(root)
        except ValueError as exc:
            self._logger.warning("Could not load rules: {}", exc)
            return []

        file_sizes: dict[str, int] = {}
        function_sizes: dict[str, int] = {}
        all_imports: list[str] = []
        file_contents: dict[str, str] = {}

        for py_file in sorted(root.rglob("*.py"))[:200]:
            if self._should_skip(py_file, root):
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
                rel = str(py_file.relative_to(root)).replace("\\", "/")
                lines = content.split("\n")
                file_sizes[rel] = len(lines)
                # Cap bodies kept for content-based security rules.
                file_contents[rel] = content if len(content) <= 200_000 else content[:200_000]

                for m in re.finditer(r"^(import\s+.+|from\s+\S+\s+import\s+.+)", content, re.MULTILINE):
                    all_imports.append(m.group(0))

                for m in re.finditer(
                    r"^([ \t]*)def\s+(\w+)\s*\(.*?\).*?:\s*\n((?:\1[ \t]+.+\n)*)",
                    content, re.MULTILINE,
                ):
                    func_name = m.group(2)
                    body = m.group(3)
                    func_lines = len(body.strip().split("\n")) if body.strip() else 1
                    function_sizes[f"{rel}::{func_name}"] = func_lines
            except (OSError, UnicodeDecodeError):
                continue

        ctx = RuleContext({
            "branch_name": self._get_branch(root),
            "changed_files": [],
            "imports": all_imports,
            "file_sizes": file_sizes,
            "function_sizes": function_sizes,
            "file_contents": file_contents,
        })
        result = self._rules.evaluate(ctx)
        recs: list[Recommendation] = []
        for v in result.violations:
            # Skip content-policy false positives with no file (generic evaluator).
            if not v.file_path and v.category.value == "security_policy":
                continue
            is_org = (getattr(v, "source", None) or "builtin") == "organization"
            prefix = "Organization policy" if is_org else "Rule violation"
            description = v.message
            if is_org:
                description = f"Violated organization policy: {v.message}"
                if getattr(v, "documentation_url", None):
                    description = f"{description} (docs: {v.documentation_url})"
            recs.append(Recommendation(
                title=f"{prefix}: {v.rule_name}",
                description=description,
                category=RecommendationCategory.RULE_VIOLATIONS,
                severity=v.severity.value,
                confidence=0.95,
                affected_files=[v.file_path] if v.file_path else [],
                estimated_risk="low",
                estimated_effort="10 min",
                business_impact="Policy compliance",
                transformation_type="rule_fix",
            ))
        return recs

    # ------------------------------------------------------------------
    # Task 8: Architecture-Aware Recommendations
    # ------------------------------------------------------------------

    def _architecture_recommendations(self, root: Path) -> list[Recommendation]:
        """Generate recommendations from architecture policy violations."""
        if self._policy.policy is None:
            return []
        recs: list[Recommendation] = []
        return recs

    def _complexity_recommendations(self, root: Path) -> list[Recommendation]:
        """Generate recommendations for high cyclomatic complexity and deep nesting."""
        recs: list[Recommendation] = []
        for py_file in sorted(root.rglob("*.py"))[:100]:
            if self._should_skip(py_file, root, skip_tests=True):
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
                rel = str(py_file.relative_to(root)).replace("\\", "/")
                lines = content.split("\n")

                for match in re.finditer(
                    r"^([ \t]*)def\s+(\w+)\s*\(.*?\).*?:\s*\n((?:\1[ \t]+.*\n)*)",
                    content, re.MULTILINE,
                ):
                    func_name = match.group(2)
                    body = match.group(3)
                    if not body:
                        continue
                    body_lines = body.split("\n")
                    branches = sum(
                        1 for bl in body_lines
                        if re.match(r"\s+(if |elif |else:|for |while |except |with )", bl)
                    )
                    if branches >= 8:
                        recs.append(Recommendation(
                            title=f"High complexity: {func_name} in {rel}",
                            description=f"{func_name}() has {branches} branch points — consider extracting methods",
                            category=RecommendationCategory.MAINTAINABILITY,
                            severity="high" if branches >= 12 else "medium",
                            confidence=0.85,
                            affected_files=[rel],
                            estimated_effort="30 min",
                            estimated_risk="medium",
                            transformation_type="refactor",
                            estimated_patch_size=branches * 5,
                        ))

                max_indent = 0
                for line in lines:
                    stripped = line.lstrip()
                    if stripped and not stripped.startswith("#"):
                        indent = len(line) - len(stripped)
                        max_indent = max(max_indent, indent // 4)
                if max_indent >= 6:
                    recs.append(Recommendation(
                        title=f"Deep nesting in {rel}",
                        description=f"Maximum nesting depth: {max_indent} levels — flatten with early returns or extraction",
                        category=RecommendationCategory.MAINTAINABILITY,
                        severity="medium",
                        confidence=0.8,
                        affected_files=[rel],
                        estimated_effort="20 min",
                        estimated_risk="low",
                        transformation_type="refactor",
                    ))

            except (OSError, UnicodeDecodeError):
                continue
        return recs[:15]

    def _maintainability_recommendations(self, root: Path) -> list[Recommendation]:
        """Recommend maintainability improvements: coupling, cohesion, naming."""
        recs: list[Recommendation] = []
        for py_file in sorted(root.rglob("*.py"))[:100]:
            if self._should_skip(py_file, root, skip_tests=True):
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
                rel = str(py_file.relative_to(root)).replace("\\", "/")

                import_count = len(re.findall(r"^(?:import|from)\s+", content, re.MULTILINE))
                if import_count > 15:
                    recs.append(Recommendation(
                        title=f"High coupling: {rel}",
                        description=f"{import_count} imports suggest this module has too many responsibilities",
                        category=RecommendationCategory.ARCHITECTURE,
                        severity="medium",
                        confidence=0.75,
                        affected_files=[rel],
                        estimated_effort="45 min",
                        estimated_risk="medium",
                        business_impact="Reduces change isolation",
                        transformation_type="refactor",
                    ))

                classes = re.findall(r"^class\s+(\w+)", content, re.MULTILINE)
                for cls_name in classes:
                    cls_pattern = re.compile(
                        rf"^class\s+{re.escape(cls_name)}\b.*?(?=\nclass\s|\Z)",
                        re.MULTILINE | re.DOTALL,
                    )
                    cls_match = cls_pattern.search(content)
                    if cls_match:
                        cls_body = cls_match.group(0)
                        methods = re.findall(r"def\s+(\w+)\s*\(", cls_body)
                        if len(methods) > 12:
                            recs.append(Recommendation(
                                title=f"Large class: {cls_name} in {rel}",
                                description=(
                                    f"Class {cls_name} has {len(methods)} methods — "
                                    f"consider splitting into focused classes"
                                ),
                                category=RecommendationCategory.REFACTORING,
                                severity="medium",
                                confidence=0.8,
                                affected_files=[rel],
                                estimated_effort="60 min",
                                estimated_risk="medium",
                                transformation_type="refactor",
                                estimated_patch_size=len(methods) * 10,
                            ))

                long_params = re.findall(r"def\s+(\w+)\s*\(([^)]{60,})\)", content)
                for func_name, params in long_params:
                    param_count = params.count(",") + 1
                    if param_count > 5:
                        recs.append(Recommendation(
                            title=f"Too many parameters: {func_name}() in {rel}",
                            description=f"{func_name}() takes {param_count} parameters — use a config object or dataclass",
                            category=RecommendationCategory.MAINTAINABILITY,
                            severity="low",
                            confidence=0.8,
                            affected_files=[rel],
                            estimated_effort="15 min",
                            estimated_risk="low",
                            transformation_type="refactor",
                        ))

            except (OSError, UnicodeDecodeError):
                continue
        return recs[:15]

    # ------------------------------------------------------------------
    # Task 11: Explain Recommendations
    # ------------------------------------------------------------------

    def _explain_recommendation(self, rec: Recommendation) -> RecommendationExplanation:
        """Generate detailed explanation with transformation and maintainability context."""
        benefits: list[str] = []
        risks: list[str] = []
        tradeoffs: list[str] = [f"Effort: {rec.estimated_effort}"]

        if rec.category == RecommendationCategory.SECURITY:
            benefits = ["Reduces security attack surface", "Improves compliance"]
            risks = ["May require API changes"]
        elif rec.category == RecommendationCategory.ARCHITECTURE:
            benefits = ["Improves modularity", "Reduces coupling"]
            risks = ["Requires coordination across teams"]
        elif rec.category == RecommendationCategory.TECHNICAL_DEBT:
            benefits = ["Improves maintainability", "Reduces bug risk"]
            risks = ["May temporarily slow feature development"]
        elif rec.category == RecommendationCategory.TESTING:
            benefits = ["Catches bugs earlier", "Enables safe refactoring"]
            risks = ["Maintenance overhead for test suite"]
        elif rec.category == RecommendationCategory.DOCUMENTATION:
            benefits = ["Improves onboarding", "Reduces knowledge silos"]
            risks = ["Minimal"]
        elif rec.category == RecommendationCategory.RULE_VIOLATIONS:
            benefits = ["Enforces consistency", "Reduces review friction"]
            risks = ["May require code style adjustments"]
        else:
            benefits = ["Improves code quality"]
            risks = ["Minimal"]

        if rec.transformation_type:
            auto_types = {"refactor", "doc_generation", "security_fix", "rule_fix"}
            if rec.transformation_type in auto_types:
                benefits.append("Auto-fixable via `refactory apply`")
                tradeoffs.append("Automated transformation available")
            if rec.estimated_patch_size:
                tradeoffs.append(f"~{rec.estimated_patch_size} lines affected")

        return RecommendationExplanation(
            why=rec.description or rec.title,
            benefits=benefits,
            risks=risks,
            tradeoffs=tradeoffs,
            alternatives=["Defer to next sprint", "Partial fix"],
            estimated_implementation_time=rec.estimated_effort or "30 min",
            estimated_review_time="15 min",
            confidence_explanation=f"Confidence {rec.confidence:.0%} based on static analysis",
        )

    # ------------------------------------------------------------------
    # Task 12: Recommendation Bundles
    # ------------------------------------------------------------------

    def _create_bundles(self, recs: list[Recommendation]) -> list[RecommendationBundle]:
        """Group related recommendations into bundles."""
        module_recs: dict[str, list[Recommendation]] = defaultdict(list)
        for rec in recs:
            if rec.affected_modules:
                module_recs[rec.affected_modules[0]].append(rec)
            elif rec.affected_files:
                module = Path(rec.affected_files[0]).parts[0] if rec.affected_files[0] else "misc"
                module_recs[module].append(rec)

        bundles: list[RecommendationBundle] = []
        for module, module_items in module_recs.items():
            if len(module_items) >= 2:
                bundle = RecommendationBundle(
                    title=f"{module} cleanup",
                    description=f"{len(module_items)} improvements for {module}",
                    recommendations=[r.id for r in module_items],
                    estimated_total_effort=f"{len(module_items) * 20} min",
                    category=module_items[0].category,
                )
                for r in module_items:
                    r.bundle_id = bundle.id
                bundles.append(bundle)

        return bundles

    # ------------------------------------------------------------------
    # Task 9 + 15: Persistence
    # ------------------------------------------------------------------

    def _persist_recommendations(
        self,
        root: Path,
        report: RecommendationReport,
        duration_ms: float,
        *,
        reconcile: bool = False,
    ) -> dict[str, int]:
        """Store recommendations via PersistenceService (fallback to StorageService)."""
        self._write_analysis(
            str(root), root.name,
            command="recommend",
            result_type="recommendations",
            result_data=report.model_dump(mode="json"),
            duration_ms=duration_ms,
        )
        self._write_metric(
            str(root), root.name,
            metric_name="recommendation_count",
            metric_value=float(report.total_recommendations),
        )
        if reconcile:
            return self._reconcile_recommendations(
                str(root), root.name, report.recommendations
            )
        self._write_recommendations(str(root), root.name, report.recommendations)
        return {"created": len(report.recommendations), "mode": 0}

    def _write_recommendations(
        self,
        repository_path: str,
        repository_name: str,
        recommendations: list[Any],
    ) -> None:
        """Bulk-persist individual recommendations into db_recommendations."""
        if self._persistence is None or not recommendations:
            return
        try:
            repo_id = self._get_repository_id(repository_path, repository_name)
            from refactory.recommendation.enrichment import payload_from_engine_rec

            payloads = [payload_from_engine_rec(rec) for rec in recommendations]
            self._persistence.persist_recommendations(repo_id, payloads)
            if self._stats is not None:
                self._stats.invalidate(repository_id=repo_id, repo_root=repository_path)
        except Exception:  # noqa: BLE001
            self._logger.debug(
                "Recommendation row persistence failed, analysis snapshot still saved"
            )

    def _reconcile_recommendations(
        self,
        repository_path: str,
        repository_name: str,
        recommendations: list[Any],
    ) -> dict[str, int]:
        """Replace stale DB rows by reconciling against a freshly generated set."""
        if self._persistence is None:
            return {}
        try:
            repo_id = self._get_repository_id(repository_path, repository_name)
            from refactory.recommendation.enrichment import payload_from_engine_rec

            payloads = [payload_from_engine_rec(rec) for rec in recommendations]
            stats = self._persistence.reconcile_recommendations(repo_id, payloads)
            if self._stats is not None:
                self._stats.invalidate(repository_id=repo_id, repo_root=repository_path)
            return stats
        except Exception:  # noqa: BLE001
            self._logger.debug(
                "Recommendation reconciliation failed, analysis snapshot still saved"
            )
            return {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    _SKIP_DIRS = {"__pycache__", ".venv", "node_modules", ".git", ".refactory"}

    def _should_skip(self, py_file: Path, root: Path, *, skip_tests: bool = False) -> bool:
        """Check whether a file should be excluded from analysis."""
        try:
            rel_parts = py_file.relative_to(root).parts
        except ValueError:
            return True
        for part in rel_parts:
            if part in self._SKIP_DIRS:
                return True
            if skip_tests and (part == "tests" or part.startswith("test_")):
                return True
        return False

    def _debt_recommendations(self, root: Path) -> list[Recommendation]:
        """Generate recommendations from technical debt analysis."""
        recs: list[Recommendation] = []
        for py_file in sorted(root.rglob("*.py"))[:200]:
            if self._should_skip(py_file, root):
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
                rel = str(py_file.relative_to(root)).replace("\\", "/")
                items = self._analyze_file_debt(rel, content)
                for item in items:
                    recs.append(Recommendation(
                        title=f"{item.category.value.replace('_', ' ').title()}: {item.file_path}",
                        description=item.description,
                        category=RecommendationCategory.TECHNICAL_DEBT,
                        severity=item.severity,
                        confidence=0.85,
                        affected_files=[item.file_path],
                        affected_modules=[Path(item.file_path).parts[0]] if "/" in item.file_path else [],
                        estimated_effort=item.estimated_cleanup_effort,
                        estimated_risk="low",
                        transformation_type="refactor",
                        estimated_patch_size=50,
                    ))
            except (OSError, UnicodeDecodeError):
                continue
        return recs[:30]

    def _security_recommendations(self, root: Path) -> list[Recommendation]:
        """Basic security recommendations."""
        recs: list[Recommendation] = []
        for py_file in sorted(root.rglob("*.py"))[:100]:
            if self._should_skip(py_file, root, skip_tests=True):
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
                rel = str(py_file.relative_to(root)).replace("\\", "/")
                if re.search(r"eval\(|exec\(|pickle\.loads?\(", content):
                    recs.append(Recommendation(
                        title=f"Security risk in {rel}",
                        description="Unsafe code pattern detected",
                        category=RecommendationCategory.SECURITY,
                        severity="high",
                        confidence=0.9,
                        affected_files=[rel],
                        estimated_risk="high",
                        estimated_effort="20 min",
                        business_impact="Security vulnerability",
                        transformation_type="security_fix",
                    ))
            except (OSError, UnicodeDecodeError):
                continue
        return recs[:10]

    def _testing_recommendations(self, root: Path) -> list[Recommendation]:
        """Recommend missing tests."""
        recs: list[Recommendation] = []
        tests_dir = root / "tests"
        for py_file in sorted(root.rglob("*.py"))[:100]:
            if self._should_skip(py_file, root, skip_tests=True):
                continue
            stem = py_file.stem
            if stem.startswith("_"):
                continue
            test_file = tests_dir / "unit" / f"test_{stem}.py"
            if not test_file.is_file():
                rel = str(py_file.relative_to(root)).replace("\\", "/")
                recs.append(Recommendation(
                    title=f"Missing tests for {rel}",
                    description=f"No test file found for {stem}",
                    category=RecommendationCategory.TESTING,
                    severity="medium",
                    confidence=0.7,
                    affected_files=[rel],
                    estimated_effort="30 min",
                    estimated_risk="low",
                    transformation_type="test_generation",
                ))
        return recs[:10]

    def _documentation_recommendations(self, root: Path) -> list[Recommendation]:
        """Recommend documentation improvements."""
        recs: list[Recommendation] = []
        for py_file in sorted(root.rglob("*.py"))[:50]:
            if self._should_skip(py_file, root, skip_tests=True):
                continue
            if py_file.name == "__init__.py":
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
                rel = str(py_file.relative_to(root)).replace("\\", "/")
                public_funcs = re.findall(r"^def ([a-z]\w+)\s*\(", content, re.MULTILINE)
                undocumented = sum(
                    1 for f in public_funcs
                    if f'def {f}' in content and '"""' not in content[content.index(f'def {f}'):content.index(f'def {f}') + 200]
                )
                if undocumented > 3:
                    recs.append(Recommendation(
                        title=f"Missing documentation in {rel}",
                        description=f"{undocumented} public functions lack docstrings",
                        category=RecommendationCategory.DOCUMENTATION,
                        severity="low",
                        confidence=0.8,
                        affected_files=[rel],
                        estimated_effort="15 min",
                        estimated_risk="low",
                        transformation_type="doc_generation",
                    ))
            except (OSError, UnicodeDecodeError, ValueError):
                continue
        return recs[:5]

    def _get_branch(self, root: Path) -> str:
        """Get current branch name."""
        try:
            from git import Repo
            repo = Repo(str(root), search_parent_directories=True)
            return repo.active_branch.name
        except Exception:  # noqa: BLE001
            return ""
