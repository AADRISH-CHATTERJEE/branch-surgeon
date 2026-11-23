"""Refactoring Engine service — orchestrates analyzers and planner.

Consumes existing services via dependency injection; never duplicates
graph traversal, parsing, or search logic.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

from refactory.documentation.service import DocumentationService
from refactory.graph.service import RepositoryGraphService
from refactory.indexer.models import RepositoryIndex
from refactory.indexer.service import IndexerService
from refactory.parser.models import ParsedFile
from refactory.parser.service import ParserService
from refactory.refactor.analyzer import RefactoringAnalyzer
from refactory.refactor.models import (
    RefactorAnalysis,
    RefactorCategory,
    RefactorMetrics,
    RefactorSeverity,
)
from refactory.refactor.planner import RefactoringPlanner

if TYPE_CHECKING:
    from loguru import Logger


class RefactoringService:
    """Top-level orchestrator for the Refactoring Engine."""

    def __init__(
        self,
        logger: "Logger",
        parser_service: ParserService,
        indexer_service: IndexerService,
        graph_service: RepositoryGraphService,
        documentation_service: DocumentationService,
    ) -> None:
        self._logger = logger
        self._parser = parser_service
        self._indexer = indexer_service
        self._graph = graph_service
        self._docs = documentation_service
        self._parse_cache: dict[str, ParsedFile] | None = None
        self._analyzer = RefactoringAnalyzer(
            logger=logger,
            parser_service=parser_service,
            indexer_service=indexer_service,
            graph_service=graph_service,
            documentation_service=documentation_service,
        )
        self._planner = RefactoringPlanner(logger=logger)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        repo_root: Path,
        *,
        target_file: str | None = None,
        category_filter: str | None = None,
        severity_filter: str | None = None,
    ) -> RefactorAnalysis:
        """Run the full refactoring analysis pipeline."""
        t0 = time.perf_counter()
        self._parse_cache = None

        index = self._build_index(repo_root)
        parsed_files = self._parse_all(repo_root, index)

        self._build_graph(index)

        issues = self._analyzer.analyze_all(
            index, parsed_files, target_file=target_file,
        )

        if category_filter:
            try:
                cat = RefactorCategory(category_filter)
                issues = [i for i in issues if i.category == cat]
            except ValueError:
                self._logger.warning("Unknown category filter: {}", category_filter)

        if severity_filter:
            try:
                sev = RefactorSeverity(severity_filter)
                issues = [i for i in issues if i.severity == sev]
            except ValueError:
                self._logger.warning("Unknown severity filter: {}", severity_filter)

        recommendations = self._planner.build_recommendations(issues)
        plan = self._planner.build_plan(issues)
        metrics = self._compute_metrics(index, issues)

        elapsed = time.perf_counter() - t0
        notes: list[str] = [f"Analysis completed in {elapsed:.2f}s"]
        if target_file:
            notes.append(f"Scope: {target_file}")
        if category_filter:
            notes.append(f"Filter: category={category_filter}")
        if severity_filter:
            notes.append(f"Filter: severity={severity_filter}")

        return RefactorAnalysis(
            scope="file" if target_file else "repository",
            target=target_file or str(repo_root),
            issues=issues,
            recommendations=recommendations,
            metrics=metrics,
            plan=plan,
            notes=notes,
        )

    def analyze_json(
        self,
        repo_root: Path,
        **kwargs: object,
    ) -> str:
        """Return analysis as a JSON string."""
        result = self.analyze(repo_root, **kwargs)  # type: ignore[arg-type]
        return json.dumps(result.model_dump(), indent=2, default=str)

    # ------------------------------------------------------------------
    # Internal pipeline steps
    # ------------------------------------------------------------------

    def _build_index(self, repo_root: Path) -> RepositoryIndex:
        index = self._indexer.load_index(repo_root)
        if index is None:
            self._logger.info("No persisted index — building fresh")
            index = self._indexer.build_index(repo_root)
        return index

    def _parse_all(
        self, repo_root: Path, index: RepositoryIndex,
    ) -> dict[str, ParsedFile]:
        """Parse all files, caching results to avoid parsing the same file twice."""
        if self._parse_cache is not None:
            return self._parse_cache

        parsed: dict[str, ParsedFile] = {}
        for f in index.files:
            full_path = repo_root / f.relative_path
            if not full_path.exists():
                continue
            try:
                pf = self._parser.parse_file(full_path)
                if pf:
                    parsed[f.relative_path] = pf
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("Parse failed for {}: {}", f.relative_path, exc)
        self._parse_cache = parsed
        return parsed

    def _build_graph(self, index: RepositoryIndex) -> None:
        try:
            self._graph.build_graph(index)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Graph build failed (cycle/dead-code detection limited): {}", exc)

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_metrics(
        index: RepositoryIndex,
        issues: list,
    ) -> RefactorMetrics:
        crit = sum(1 for i in issues if i.severity == RefactorSeverity.CRITICAL)
        high = sum(1 for i in issues if i.severity == RefactorSeverity.HIGH)
        med = sum(1 for i in issues if i.severity == RefactorSeverity.MEDIUM)
        low = sum(1 for i in issues if i.severity == RefactorSeverity.LOW)

        doc_count = sum(
            1 for i in issues
            if i.category == RefactorCategory.DOCUMENTATION_DRIFT
        )
        non_doc_low = low - doc_count

        deductions = (
            crit * 15
            + high * 8
            + med * 3
            + non_doc_low * 1
            + min(doc_count, 10) * 0.2
        )
        health = max(0, min(100, 100 - deductions))
        grade = (
            "A" if health >= 90 else
            "B" if health >= 75 else
            "C" if health >= 60 else
            "D" if health >= 40 else "F"
        )

        largest = 0
        longest_fn = 0
        for i in issues:
            if i.category == RefactorCategory.LARGE_FILE:
                lines = i.metrics.get("lines", 0)
                if isinstance(lines, int) and lines > largest:
                    largest = lines
            if i.category == RefactorCategory.LONG_FUNCTION:
                lines = i.metrics.get("lines", 0)
                if isinstance(lines, int) and lines > longest_fn:
                    longest_fn = lines

        return RefactorMetrics(
            files_analyzed=len(index.files),
            total_issues=len(issues),
            critical_issues=crit,
            high_issues=high,
            medium_issues=med,
            low_issues=low,
            health_score=health,
            grade=grade,
            largest_file_lines=largest,
            longest_function_lines=longest_fn,
            circular_dependency_count=sum(
                1 for i in issues if i.category == RefactorCategory.CIRCULAR_DEPENDENCY
            ),
            dead_code_count=sum(
                1 for i in issues if i.category == RefactorCategory.DEAD_CODE
            ),
            unused_import_count=sum(
                1 for i in issues if i.category == RefactorCategory.UNUSED_IMPORT
            ),
            duplicate_candidate_count=sum(
                1 for i in issues if i.category == RefactorCategory.DUPLICATE_LOGIC
            ),
        )
