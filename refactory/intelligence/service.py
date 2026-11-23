"""AIIntelligenceService — orchestrates AI-powered code analysis.

Uses AIGateway for LLM calls and existing deterministic services for
repository context. All AI features go through this single service.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from refactory.ai.gateway import AIGateway
from refactory.ai.models import AIRequest, AIResponse
from refactory.graph.service import RepositoryGraphService
from refactory.impact.service import ImpactAnalysisService
from refactory.indexer.service import IndexerService
from refactory.intelligence.models import (
    AIConfidence,
    AIRefactorResult,
    AISuggestion,
    AISuggestionKind,
    ArchitectureAdvice,
    ArchitectureReport,
    ArchitectureSummary,
    ArchitectureViolation,
    CodeSmell,
    ComponentInfo,
    DetectedPattern,
    DocGenResult,
    FileExplanation,
    GeneratedDoc,
    GeneratedTest,
    PatchFile,
    PatchResult,
    PatternReport,
    SmartImpactPrediction,
    SmellKind,
    SmellReport,
    TestGenResult,
    ViolationKind,
)
from refactory.parser.service import ParserService
from refactory.refactor.models import RefactorAnalysis

if TYPE_CHECKING:
    from loguru import Logger


class AIIntelligenceService:
    """Central AI intelligence service for all LLM-powered features."""

    def __init__(
        self,
        logger: "Logger",
        ai_gateway: AIGateway,
        parser_service: ParserService,
        indexer_service: IndexerService,
        graph_service: RepositoryGraphService,
        impact_service: ImpactAnalysisService,
    ) -> None:
        self._logger = logger
        self._ai = ai_gateway
        self._parser = parser_service
        self._indexer = indexer_service
        self._graph = graph_service
        self._impact = impact_service

    # ------------------------------------------------------------------
    # Task 1: AI Refactoring Suggestions
    # ------------------------------------------------------------------

    def ai_refactor(
        self,
        analysis: RefactorAnalysis,
        *,
        file_content: str = "",
        target_file: str = "",
    ) -> AIRefactorResult:
        """Generate AI-powered refactoring suggestions from deterministic analysis."""
        context = self._build_refactor_context(analysis, file_content, target_file)
        prompt = (
            "You are a senior software engineer. Analyze the following code analysis "
            "and generate specific refactoring suggestions.\n\n"
            "For each suggestion provide:\n"
            '- kind: one of "rename", "extract_method", "extract_class", '
            '"remove_duplication", "simplify_conditional", "reduce_complexity"\n'
            "- title: short description\n"
            "- description: detailed explanation\n"
            "- file: affected file path\n"
            "- symbol: affected symbol name\n"
            "- why: reason for the suggestion\n"
            "- benefits: expected improvements\n"
            '- risk: "low", "medium", or "high"\n'
            "- estimated_effort: time estimate\n"
            "- confidence_score: 0.0 to 1.0\n"
            "- evidence: list of supporting observations\n\n"
            "Return JSON array of suggestions.\n\n"
            f"Context:\n{context}"
        )
        response = self._generate(prompt)
        return self._parse_refactor_response(response)

    # ------------------------------------------------------------------
    # Task 2: Patch Generation
    # ------------------------------------------------------------------

    def generate_patch(
        self,
        file_path: str,
        file_content: str,
        suggestion: str,
    ) -> PatchResult:
        """Generate a unified diff patch for a suggested change."""
        prompt = (
            "Generate a unified git diff patch for the following change.\n"
            "Do NOT modify the file directly. Only output the unified diff.\n"
            "Use standard unified diff format (--- a/file, +++ b/file).\n\n"
            f"File: {file_path}\n"
            f"Suggestion: {suggestion}\n\n"
            f"Original content:\n```\n{file_content[:3000]}\n```\n\n"
            "Return only the unified diff, nothing else."
        )
        response = self._generate(prompt)
        diff_text = response.text.strip()
        if diff_text.startswith("```"):
            diff_text = re.sub(r"^```\w*\n?", "", diff_text)
            diff_text = re.sub(r"\n?```$", "", diff_text)

        return PatchResult(
            patches=[PatchFile(
                file_path=file_path,
                original_content=file_content,
                unified_diff=diff_text,
            )],
            summary=f"Generated patch for {file_path}",
            files_affected=1,
        )

    # ------------------------------------------------------------------
    # Task 3: Architecture Violations
    # ------------------------------------------------------------------

    def detect_architecture_violations(
        self, repo_root: Path,
    ) -> ArchitectureReport:
        """Detect architectural violations using graph + AI analysis."""
        violations: list[ArchitectureViolation] = []

        try:
            cycles = self._graph.find_cycles()
            for cycle in cycles[:20]:
                violations.append(ArchitectureViolation(
                    kind=ViolationKind.CIRCULAR_DEPENDENCY,
                    title=f"Circular dependency: {' → '.join(cycle.modules[:4])}",
                    detail=f"Full chain: {' → '.join(cycle.modules)}",
                    files=[m for m in cycle.modules],
                    severity="high",
                    fix_suggestion="Break the cycle by introducing an interface or moving shared code to a common module.",
                ))
        except Exception:  # noqa: BLE001
            pass

        try:
            stats = self._graph.repository_statistics()
            for node_id, node in self._graph.graph().nodes.items():
                from refactory.graph.models import FileNode, NodeKind
                if not isinstance(node, FileNode):
                    continue
                deps = self._graph.dependencies_of(node.file_path)
                if len(deps) > 15:
                    violations.append(ArchitectureViolation(
                        kind=ViolationKind.HIGH_COUPLING,
                        title=f"High coupling: {node.file_path} ({len(deps)} dependencies)",
                        files=[node.file_path],
                        severity="medium",
                        fix_suggestion="Consider splitting this module or introducing abstractions.",
                    ))
        except Exception:  # noqa: BLE001
            pass

        score = max(0, 100 - len(violations) * 5)
        return ArchitectureReport(
            violations=violations,
            summary=f"Found {len(violations)} architectural violation(s)",
            health_score=score,
        )

    # ------------------------------------------------------------------
    # Task 4: Design Pattern Detection
    # ------------------------------------------------------------------

    def detect_patterns(self, repo_root: Path) -> PatternReport:
        """Detect design patterns and anti-patterns in the codebase."""
        patterns: list[DetectedPattern] = []
        anti_patterns = []

        index = self._indexer.load_index(repo_root)
        if index is None:
            return PatternReport(summary="No index available")

        for f in index.files:
            full_path = repo_root / f.relative_path
            if not full_path.exists():
                continue
            try:
                parsed = self._parser.parse_file(full_path)
            except Exception:  # noqa: BLE001
                continue

            for cls in parsed.module.classes:
                self._detect_class_patterns(cls, f.relative_path, patterns)

        return PatternReport(
            patterns=patterns,
            anti_patterns=anti_patterns,
            summary=f"Detected {len(patterns)} pattern(s)",
        )

    # ------------------------------------------------------------------
    # Task 5: Code Smell Detection
    # ------------------------------------------------------------------

    def detect_code_smells(self, repo_root: Path) -> SmellReport:
        """Detect code smells across the repository."""
        smells: list[CodeSmell] = []

        index = self._indexer.load_index(repo_root)
        if index is None:
            return SmellReport(summary="No index available")

        for f in index.files:
            full_path = repo_root / f.relative_path
            if not full_path.exists():
                continue
            try:
                parsed = self._parser.parse_file(full_path)
            except Exception:  # noqa: BLE001
                continue

            for func in parsed.module.functions:
                lines = (func.end_line or 0) - (func.start_line or 0)
                if lines > 50:
                    smells.append(CodeSmell(
                        kind=SmellKind.LONG_METHOD,
                        file=f.relative_path,
                        symbol=func.name,
                        line=func.start_line,
                        detail=f"{func.name} is {lines} lines long",
                        severity="medium" if lines < 100 else "high",
                        why="Long methods are harder to understand and maintain",
                        benefits="Shorter methods improve readability and testability",
                        estimated_effort="30 minutes",
                    ))

            for cls in parsed.module.classes:
                method_count = len(cls.methods)
                if method_count > 10:
                    smells.append(CodeSmell(
                        kind=SmellKind.LARGE_CLASS,
                        file=f.relative_path,
                        symbol=cls.name,
                        line=cls.start_line,
                        detail=f"{cls.name} has {method_count} methods",
                        severity="medium" if method_count < 20 else "high",
                        why="Large classes violate Single Responsibility Principle",
                        benefits="Smaller, focused classes are easier to test and maintain",
                        estimated_effort="1-2 hours",
                    ))

                if method_count > 0 and all(
                    not m.docstring for m in cls.methods
                ) and len(cls.methods) <= 5:
                    has_init_only = (
                        len(cls.methods) == 1
                        and cls.methods[0].name == "__init__"
                    )
                    if has_init_only or all(
                        m.name.startswith("get_") or m.name.startswith("set_")
                        for m in cls.methods
                        if m.name != "__init__"
                    ):
                        smells.append(CodeSmell(
                            kind=SmellKind.DATA_CLASS,
                            file=f.relative_path,
                            symbol=cls.name,
                            line=cls.start_line,
                            detail=f"{cls.name} appears to be a data-only class",
                            severity="low",
                            why="Data classes with no behavior may indicate missing abstractions",
                            benefits="Consider using dataclass or named tuple",
                            estimated_effort="15 minutes",
                        ))

        return SmellReport(
            smells=smells,
            summary=f"Detected {len(smells)} code smell(s)",
            total_smells=len(smells),
        )

    # ------------------------------------------------------------------
    # Task 7: Test Generation
    # ------------------------------------------------------------------

    def generate_tests(
        self,
        file_path: str,
        file_content: str,
    ) -> TestGenResult:
        """Generate pytest test skeletons for a source file."""
        prompt = (
            "Generate comprehensive pytest test skeletons for the following Python file.\n"
            "Cover: happy path, edge cases, negative cases, boundary conditions.\n"
            "Use pytest style (no unittest.TestCase). Use descriptive test names.\n"
            "Include proper imports and fixtures where needed.\n\n"
            f"File: {file_path}\n\n"
            f"```python\n{file_content[:4000]}\n```\n\n"
            "Return only the test code, properly formatted as a Python file."
        )
        response = self._generate(prompt)
        test_code = response.text.strip()
        if test_code.startswith("```"):
            test_code = re.sub(r"^```\w*\n?", "", test_code)
            test_code = re.sub(r"\n?```$", "", test_code)

        stem = Path(file_path).stem
        test_file = f"tests/unit/test_{stem}.py"

        return TestGenResult(
            tests=[GeneratedTest(
                file_path=test_file,
                test_code=test_code,
                target_file=file_path,
                test_kind="unit",
            )],
            summary=f"Generated tests for {file_path}",
            model=response.model,
        )

    # ------------------------------------------------------------------
    # Task 8: Documentation Generator
    # ------------------------------------------------------------------

    def generate_docs(
        self,
        file_path: str,
        file_content: str,
        *,
        kind: str = "module",
    ) -> DocGenResult:
        """Generate documentation for a source file or symbol."""
        prompt = (
            f"Generate {kind} documentation for the following Python code.\n"
            "Include: purpose, parameters, return values, usage examples, notes.\n"
            "Use Google-style docstring format.\n\n"
            f"File: {file_path}\n\n"
            f"```python\n{file_content[:4000]}\n```\n\n"
            "Return the documentation content."
        )
        response = self._generate(prompt)

        return DocGenResult(
            docs=[GeneratedDoc(
                target=file_path,
                kind=kind,
                content=response.text.strip(),
                file_path=file_path,
            )],
            summary=f"Generated {kind} docs for {file_path}",
            model=response.model,
        )

    # ------------------------------------------------------------------
    # Task 9: Architectural Summary
    # ------------------------------------------------------------------

    def architecture_summary(self, repo_root: Path) -> ArchitectureSummary:
        """Generate an architectural summary of the repository."""
        components: list[ComponentInfo] = []
        module_responsibilities: dict[str, str] = {}

        index = self._indexer.load_index(repo_root)
        if index is None:
            return ArchitectureSummary(summary="No index available")

        packages: dict[str, list[str]] = {}
        for f in index.files:
            parts = f.relative_path.replace("\\", "/").split("/")
            pkg = parts[0] if len(parts) > 1 else "(root)"
            packages.setdefault(pkg, []).append(f.relative_path)

        for pkg, files in sorted(packages.items()):
            deps: list[str] = []
            for f_path in files[:5]:
                try:
                    d = self._graph.dependencies_of(f_path)
                    for dep in d:
                        dep_pkg = dep.split("/")[0] if "/" in dep else "(root)"
                        if dep_pkg != pkg and dep_pkg not in deps:
                            deps.append(dep_pkg)
                except Exception:  # noqa: BLE001
                    pass

            responsibility = self._infer_responsibility(pkg)
            module_responsibilities[pkg] = responsibility
            components.append(ComponentInfo(
                name=pkg,
                files=files[:10],
                responsibility=responsibility,
                dependencies=deps[:10],
            ))

        critical_paths: list[str] = []
        try:
            top = self._graph.most_connected_files(limit=5)
            critical_paths = [f"{path} ({count} connections)" for path, count in top]
        except Exception:  # noqa: BLE001
            pass

        return ArchitectureSummary(
            components=components,
            dependency_summary=f"{len(components)} components, {sum(len(c.dependencies) for c in components)} cross-component dependencies",
            critical_paths=critical_paths,
            module_responsibilities=module_responsibilities,
            summary=f"Repository has {len(components)} top-level components",
        )

    # ------------------------------------------------------------------
    # Task 13: Explain Command
    # ------------------------------------------------------------------

    def explain_file(self, file_path: str, repo_root: Path) -> FileExplanation:
        """Explain a file's purpose, dependencies, and role."""
        full_path = repo_root / file_path
        deps: list[str] = []
        callers: list[str] = []
        callees: list[str] = []

        try:
            deps = self._graph.dependencies_of(file_path)
        except Exception:  # noqa: BLE001
            pass

        try:
            callers = self._graph.who_imports_file(file_path)
        except Exception:  # noqa: BLE001
            pass

        try:
            callees = self._graph.callees_of(file_path)
        except Exception:  # noqa: BLE001
            pass

        purpose = ""
        business_role = ""
        if full_path.exists():
            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
                first_lines = content[:500]
                if '"""' in first_lines:
                    doc_match = re.search(r'"""(.+?)"""', first_lines, re.DOTALL)
                    if doc_match:
                        purpose = doc_match.group(1).strip().split("\n")[0]
            except Exception:  # noqa: BLE001
                pass

        if not purpose:
            purpose = self._infer_responsibility(file_path)
        business_role = self._infer_business_role(file_path)

        return FileExplanation(
            file_path=file_path,
            purpose=purpose,
            dependencies=deps[:20],
            callers=callers[:20],
            callees=callees[:20],
            business_role=business_role,
            summary=f"{file_path}: {purpose}",
        )

    # ------------------------------------------------------------------
    # Task 14: Smart Impact Analysis
    # ------------------------------------------------------------------

    def smart_impact(
        self, file_path: str, repo_root: Path,
    ) -> SmartImpactPrediction:
        """Predict impact of changes to a file."""
        affected_tests: list[str] = []
        affected_apis: list[str] = []
        likely_bugs: list[str] = []

        try:
            reverse_deps = self._graph.reverse_dependencies(file_path)
            for dep in reverse_deps:
                if "test" in dep.lower():
                    affected_tests.append(dep)
                elif "api" in dep.lower() or "route" in dep.lower():
                    affected_apis.append(dep)
        except Exception:  # noqa: BLE001
            pass

        dep_count = 0
        try:
            dep_count = len(self._graph.reverse_dependencies(file_path))
        except Exception:  # noqa: BLE001
            pass

        if dep_count > 10:
            deployment_risk = "high"
            likely_bugs.append(f"High fan-in ({dep_count} dependents) increases regression risk")
        elif dep_count > 5:
            deployment_risk = "medium"
        else:
            deployment_risk = "low"

        rollback_risk = "medium" if dep_count > 5 else "low"

        return SmartImpactPrediction(
            likely_bugs=likely_bugs,
            affected_apis=affected_apis[:10],
            affected_tests=affected_tests[:20],
            deployment_risk=deployment_risk,
            rollback_risk=rollback_risk,
            summary=f"{dep_count} dependents, {len(affected_tests)} tests affected",
            confidence=AIConfidence(
                score=0.8 if dep_count > 0 else 0.5,
                evidence=[f"{dep_count} reverse dependencies found"],
                related_files=affected_tests[:5] + affected_apis[:5],
            ),
        )

    # ------------------------------------------------------------------
    # Task 15: AI Architecture Advisor
    # ------------------------------------------------------------------

    def architecture_advice(self, repo_root: Path) -> ArchitectureAdvice:
        """Generate architectural improvement suggestions."""
        modularization: list[str] = []
        split_suggestions: list[str] = []
        dependency_cleanup: list[str] = []
        layer_improvements: list[str] = []

        index = self._indexer.load_index(repo_root)
        if index is None:
            return ArchitectureAdvice(summary="No index available")

        for f in index.files:
            func_count = len(f.functions) + len(f.nested_functions)
            class_count = len(f.classes)
            if func_count > 15 or class_count > 5:
                split_suggestions.append(
                    f"Split {f.relative_path} ({func_count} functions, {class_count} classes)"
                )

        try:
            cycles = self._graph.find_cycles()
            for cycle in cycles[:5]:
                dependency_cleanup.append(
                    f"Break cycle: {' → '.join(cycle.modules[:4])}"
                )
        except Exception:  # noqa: BLE001
            pass

        try:
            for path, count in self._graph.most_connected_files(limit=5):
                if count > 10:
                    modularization.append(
                        f"Consider extracting interfaces from {path} ({count} connections)"
                    )
        except Exception:  # noqa: BLE001
            pass

        return ArchitectureAdvice(
            modularization=modularization,
            split_suggestions=split_suggestions[:10],
            dependency_cleanup=dependency_cleanup,
            layer_improvements=layer_improvements,
            summary=f"{len(split_suggestions)} split suggestions, {len(dependency_cleanup)} cycle cleanups",
            confidence=AIConfidence(
                score=0.7,
                evidence=[f"Analyzed {len(index.files)} files"],
            ),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _generate(self, user_prompt: str) -> AIResponse:
        """Send a prompt to the AI gateway."""
        request = AIRequest(
            system_prompt=(
                "You are an expert software engineer analyzing a Python codebase. "
                "Provide precise, actionable analysis. Return structured data when requested."
            ),
            user_prompt=user_prompt,
        )
        return self._ai.generate(request)

    def _build_refactor_context(
        self,
        analysis: RefactorAnalysis,
        file_content: str,
        target_file: str,
    ) -> str:
        parts: list[str] = []
        parts.append(f"Health Score: {analysis.metrics.health_score}/100 ({analysis.metrics.grade})")
        parts.append(f"Issues: {analysis.metrics.total_issues}")

        for issue in analysis.issues[:15]:
            parts.append(f"- [{issue.severity.value}] {issue.title}")
            if issue.file:
                parts.append(f"  File: {issue.file}")

        if file_content:
            parts.append(f"\nFile: {target_file}")
            parts.append(f"```python\n{file_content[:3000]}\n```")

        return "\n".join(parts)

    def _parse_refactor_response(self, response: AIResponse) -> AIRefactorResult:
        """Parse AI response into structured suggestions."""
        suggestions: list[AISuggestion] = []
        try:
            text = response.text.strip()
            if text.startswith("```"):
                text = re.sub(r"^```\w*\n?", "", text)
                text = re.sub(r"\n?```$", "", text)

            items = json.loads(text)
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    kind_str = item.get("kind", "reduce_complexity")
                    try:
                        kind = AISuggestionKind(kind_str)
                    except ValueError:
                        kind = AISuggestionKind.REDUCE_COMPLEXITY

                    suggestions.append(AISuggestion(
                        kind=kind,
                        title=item.get("title", ""),
                        description=item.get("description", ""),
                        file=item.get("file", ""),
                        symbol=item.get("symbol", ""),
                        why=item.get("why", ""),
                        benefits=item.get("benefits", ""),
                        risk=item.get("risk", "low"),
                        estimated_effort=item.get("estimated_effort", ""),
                        confidence=AIConfidence(
                            score=float(item.get("confidence_score", 0.5)),
                            evidence=item.get("evidence", []),
                            reasoning=item.get("reasoning", ""),
                        ),
                    ))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self._logger.debug("Failed to parse AI refactor response: {}", exc)
            suggestions.append(AISuggestion(
                kind=AISuggestionKind.REDUCE_COMPLEXITY,
                title="AI Analysis",
                description=response.text[:500],
            ))

        return AIRefactorResult(
            suggestions=suggestions,
            summary=f"Generated {len(suggestions)} suggestion(s)",
            model=response.model,
            provider=response.provider,
        )

    def _detect_class_patterns(
        self,
        cls,
        file_path: str,
        patterns: list[DetectedPattern],
    ) -> None:
        from refactory.intelligence.models import PatternKind

        method_names = {m.name for m in cls.methods}

        if "__new__" in method_names and "_instance" in str(cls.name).lower():
            patterns.append(DetectedPattern(
                kind=PatternKind.SINGLETON,
                file=file_path,
                symbol=cls.name,
                confidence=0.7,
                evidence="__new__ override with instance tracking",
            ))

        if any("create" in m.lower() or "build" in m.lower() for m in method_names):
            if any("factory" in cls.name.lower() for _ in [1]):
                patterns.append(DetectedPattern(
                    kind=PatternKind.FACTORY,
                    file=file_path,
                    symbol=cls.name,
                    confidence=0.8,
                    evidence="Class name contains 'Factory' with create/build methods",
                ))

        if any("build" in m for m in method_names) and len(method_names) > 3:
            if "builder" in cls.name.lower():
                patterns.append(DetectedPattern(
                    kind=PatternKind.BUILDER,
                    file=file_path,
                    symbol=cls.name,
                    confidence=0.7,
                    evidence="Builder pattern: fluent interface with build method",
                ))

        if cls.bases and any("protocol" in b.lower() or "abc" in b.lower() for b in cls.bases):
            if any("adapter" in cls.name.lower() for _ in [1]):
                patterns.append(DetectedPattern(
                    kind=PatternKind.ADAPTER,
                    file=file_path,
                    symbol=cls.name,
                    confidence=0.6,
                    evidence="Implements protocol/ABC with 'Adapter' in name",
                ))

        if "service" in cls.name.lower() or "repository" in cls.name.lower():
            patterns.append(DetectedPattern(
                kind=PatternKind.REPOSITORY,
                file=file_path,
                symbol=cls.name,
                confidence=0.5,
                evidence="Service/Repository naming convention",
            ))

    @staticmethod
    def _infer_responsibility(path: str) -> str:
        lower = path.lower()
        if "auth" in lower:
            return "Authentication and authorization"
        if "api" in lower or "route" in lower:
            return "API endpoint handling"
        if "model" in lower:
            return "Data modeling and schema definition"
        if "service" in lower:
            return "Business logic orchestration"
        if "cli" in lower or "command" in lower:
            return "Command-line interface"
        if "test" in lower:
            return "Test coverage"
        if "config" in lower or "settings" in lower:
            return "Configuration management"
        if "util" in lower or "helper" in lower:
            return "Utility functions"
        if "graph" in lower:
            return "Repository graph and dependency analysis"
        if "parser" in lower:
            return "Source code parsing"
        if "embed" in lower:
            return "Embedding and vector operations"
        if "doc" in lower:
            return "Documentation management"
        return "General module"

    @staticmethod
    def _infer_business_role(path: str) -> str:
        lower = path.lower()
        if "auth" in lower:
            return "Security: manages user authentication and access control"
        if "payment" in lower or "billing" in lower:
            return "Revenue: handles payment processing"
        if "user" in lower:
            return "Core: user management and profiles"
        if "api" in lower:
            return "Integration: external API surface"
        if "core" in lower:
            return "Infrastructure: core framework services"
        if "test" in lower:
            return "Quality: test infrastructure"
        return "Support: internal infrastructure"
