"""Dependency-aware refactoring planner.

Takes the list of issues from the analyzer and builds an ordered execution
plan that respects inter-step dependencies (e.g. split file before extracting
functions, remove dead code after splitting).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from refactory.refactor.models import (
    RefactorCategory,
    RefactorIssue,
    RefactorKind,
    RefactorPlan,
    RefactorPriority,
    RefactorRecommendation,
    RefactorSeverity,
)

if TYPE_CHECKING:
    from loguru import Logger


# Execution phases — lower runs first.
_PHASE_ORDER: dict[RefactorCategory, int] = {
    RefactorCategory.CIRCULAR_DEPENDENCY: 0,
    RefactorCategory.LAYER_VIOLATION: 1,
    RefactorCategory.LARGE_FILE: 2,
    RefactorCategory.GOD_CLASS: 3,
    RefactorCategory.LONG_FUNCTION: 4,
    RefactorCategory.DUPLICATE_LOGIC: 5,
    RefactorCategory.DEAD_CODE: 6,
    RefactorCategory.UNUSED_IMPORT: 7,
    RefactorCategory.NAMING_CONSISTENCY: 8,
    RefactorCategory.DOCUMENTATION_DRIFT: 9,
}

_KIND_MAP: dict[RefactorCategory, RefactorKind] = {
    RefactorCategory.LARGE_FILE: RefactorKind.SPLIT_FILE,
    RefactorCategory.LONG_FUNCTION: RefactorKind.EXTRACT_FUNCTION,
    RefactorCategory.DUPLICATE_LOGIC: RefactorKind.CONSOLIDATE_DUPLICATES,
    RefactorCategory.DEAD_CODE: RefactorKind.REMOVE_DEAD_CODE,
    RefactorCategory.UNUSED_IMPORT: RefactorKind.REMOVE_UNUSED_IMPORT,
    RefactorCategory.CIRCULAR_DEPENDENCY: RefactorKind.BREAK_CYCLE,
    RefactorCategory.GOD_CLASS: RefactorKind.DECOMPOSE_CLASS,
    RefactorCategory.LAYER_VIOLATION: RefactorKind.MOVE_TO_LAYER,
    RefactorCategory.NAMING_CONSISTENCY: RefactorKind.RENAME,
    RefactorCategory.DOCUMENTATION_DRIFT: RefactorKind.ADD_DOCUMENTATION,
}


def _priority_for(issue: RefactorIssue) -> RefactorPriority:
    if issue.severity == RefactorSeverity.CRITICAL:
        return RefactorPriority.P0
    if issue.severity == RefactorSeverity.HIGH:
        return RefactorPriority.P1
    if issue.severity == RefactorSeverity.MEDIUM:
        return RefactorPriority.P2
    return RefactorPriority.P3


def _effort_label(count: int) -> str:
    if count <= 3:
        return "small (< 1 hour)"
    if count <= 10:
        return "medium (1-4 hours)"
    if count <= 25:
        return "large (4-8 hours)"
    return "very large (> 1 day)"


def _risk_label(issues: list[RefactorIssue]) -> str:
    crit = sum(1 for i in issues if i.severity == RefactorSeverity.CRITICAL)
    high = sum(1 for i in issues if i.severity == RefactorSeverity.HIGH)
    if crit:
        return "high"
    if high >= 3:
        return "medium"
    if high >= 1:
        return "low"
    return "minimal"


class RefactoringPlanner:
    """Build dependency-ordered refactoring plan from issues."""

    def __init__(self, logger: "Logger") -> None:
        self._logger = logger

    def build_plan(self, issues: list[RefactorIssue]) -> RefactorPlan:
        if not issues:
            return RefactorPlan(
                steps=["No refactoring issues detected."],
                estimated_effort="none",
                estimated_risk="minimal",
                confidence=1.0,
            )

        sorted_issues = sorted(
            issues,
            key=lambda i: (
                _PHASE_ORDER.get(i.category, 99),
                {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(i.severity.value, 4),
            ),
        )

        steps: list[str] = []
        seen_files: set[str] = set()
        for idx, issue in enumerate(sorted_issues, 1):
            label = self._step_label(issue)
            steps.append(f"{idx}. {label}")
            if issue.file:
                seen_files.add(issue.file)

        if seen_files:
            steps.append(f"{len(steps) + 1}. Update affected tests")
            steps.append(f"{len(steps) + 1}. Update documentation")

        confidence = max(0.3, min(1.0, 1.0 - len(issues) * 0.02))

        return RefactorPlan(
            steps=steps,
            estimated_effort=_effort_label(len(issues)),
            estimated_risk=_risk_label(issues),
            confidence=round(confidence, 2),
        )

    def build_recommendations(
        self, issues: list[RefactorIssue]
    ) -> list[RefactorRecommendation]:
        recs: list[RefactorRecommendation] = []
        for issue in issues:
            kind = _KIND_MAP.get(issue.category, RefactorKind.EXTRACT_FUNCTION)
            priority = _priority_for(issue)
            recs.append(RefactorRecommendation(
                kind=kind,
                priority=priority,
                title=self._recommendation_title(issue),
                detail=issue.detail,
                files=[issue.file] if issue.file else [],
                symbols=[issue.symbol] if issue.symbol else [],
                estimated_effort=self._single_effort(issue),
            ))
        return recs

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _step_label(issue: RefactorIssue) -> str:
        verb_map: dict[RefactorCategory, str] = {
            RefactorCategory.LARGE_FILE: "Split",
            RefactorCategory.LONG_FUNCTION: "Extract from",
            RefactorCategory.DUPLICATE_LOGIC: "Consolidate",
            RefactorCategory.DEAD_CODE: "Remove dead code in",
            RefactorCategory.UNUSED_IMPORT: "Remove unused import in",
            RefactorCategory.CIRCULAR_DEPENDENCY: "Break cycle involving",
            RefactorCategory.GOD_CLASS: "Decompose",
            RefactorCategory.LAYER_VIOLATION: "Fix layer violation in",
            RefactorCategory.NAMING_CONSISTENCY: "Rename",
            RefactorCategory.DOCUMENTATION_DRIFT: "Add docs for",
        }
        verb = verb_map.get(issue.category, "Fix")
        target = issue.symbol or issue.file or "?"
        return f"{verb} {target}"

    @staticmethod
    def _recommendation_title(issue: RefactorIssue) -> str:
        return issue.title

    @staticmethod
    def _single_effort(issue: RefactorIssue) -> str:
        if issue.severity in (RefactorSeverity.CRITICAL, RefactorSeverity.HIGH):
            return "medium"
        if issue.category in (RefactorCategory.UNUSED_IMPORT, RefactorCategory.NAMING_CONSISTENCY):
            return "trivial"
        return "small"
