"""Tests for RefactoringPlanner — plan ordering, recommendations, edge cases."""

from __future__ import annotations

import pytest

from refactory.core.logger import get_service_logger
from refactory.refactor.models import (
    RefactorCategory,
    RefactorIssue,
    RefactorKind,
    RefactorPlan,
    RefactorPriority,
    RefactorRecommendation,
    RefactorSeverity,
)
from refactory.refactor.planner import RefactoringPlanner


def _logger():
    return get_service_logger("test.planner")


def _issue(
    category: RefactorCategory = RefactorCategory.DEAD_CODE,
    severity: RefactorSeverity = RefactorSeverity.LOW,
    title: str = "test issue",
    file: str = "",
    symbol: str = "",
) -> RefactorIssue:
    return RefactorIssue(
        category=category,
        severity=severity,
        title=title,
        file=file,
        symbol=symbol,
    )


class TestBuildPlan:
    def test_empty_issues(self):
        planner = RefactoringPlanner(logger=_logger())
        plan = planner.build_plan([])
        assert plan.confidence == 1.0
        assert plan.estimated_risk == "minimal"
        assert "No refactoring" in plan.steps[0]

    def test_single_issue(self):
        planner = RefactoringPlanner(logger=_logger())
        issues = [_issue(file="auth.py", symbol="_helper")]
        plan = planner.build_plan(issues)
        assert len(plan.steps) >= 1
        assert plan.confidence > 0

    def test_multiple_issues_ordered(self):
        planner = RefactoringPlanner(logger=_logger())
        issues = [
            _issue(RefactorCategory.DEAD_CODE, RefactorSeverity.LOW, file="a.py"),
            _issue(RefactorCategory.CIRCULAR_DEPENDENCY, RefactorSeverity.HIGH, file="b.py"),
            _issue(RefactorCategory.LARGE_FILE, RefactorSeverity.MEDIUM, file="c.py"),
        ]
        plan = planner.build_plan(issues)
        step_texts = " ".join(plan.steps)
        cycle_pos = next(i for i, s in enumerate(plan.steps) if "cycle" in s.lower() or "Break" in s)
        dead_pos = next(i for i, s in enumerate(plan.steps) if "dead" in s.lower() or "Remove dead" in s)
        assert cycle_pos < dead_pos

    def test_plan_includes_test_and_doc_steps(self):
        planner = RefactoringPlanner(logger=_logger())
        issues = [_issue(file="auth.py")]
        plan = planner.build_plan(issues)
        combined = " ".join(plan.steps)
        assert "test" in combined.lower()
        assert "documentation" in combined.lower()

    def test_effort_small_for_few_issues(self):
        planner = RefactoringPlanner(logger=_logger())
        issues = [_issue(file="a.py")]
        plan = planner.build_plan(issues)
        assert "small" in plan.estimated_effort

    def test_effort_medium(self):
        planner = RefactoringPlanner(logger=_logger())
        issues = [_issue(file=f"f{i}.py") for i in range(7)]
        plan = planner.build_plan(issues)
        assert "medium" in plan.estimated_effort

    def test_effort_large(self):
        planner = RefactoringPlanner(logger=_logger())
        issues = [_issue(file=f"f{i}.py") for i in range(20)]
        plan = planner.build_plan(issues)
        assert "large" in plan.estimated_effort

    def test_effort_very_large(self):
        planner = RefactoringPlanner(logger=_logger())
        issues = [_issue(file=f"f{i}.py") for i in range(30)]
        plan = planner.build_plan(issues)
        assert "very large" in plan.estimated_effort

    def test_risk_high_with_critical(self):
        planner = RefactoringPlanner(logger=_logger())
        issues = [_issue(severity=RefactorSeverity.CRITICAL)]
        plan = planner.build_plan(issues)
        assert plan.estimated_risk == "high"

    def test_risk_medium_with_many_high(self):
        planner = RefactoringPlanner(logger=_logger())
        issues = [_issue(severity=RefactorSeverity.HIGH) for _ in range(3)]
        plan = planner.build_plan(issues)
        assert plan.estimated_risk == "medium"

    def test_risk_minimal_all_low(self):
        planner = RefactoringPlanner(logger=_logger())
        issues = [_issue(severity=RefactorSeverity.LOW)]
        plan = planner.build_plan(issues)
        assert plan.estimated_risk == "minimal"

    def test_confidence_decreases_with_issues(self):
        planner = RefactoringPlanner(logger=_logger())
        plan_few = planner.build_plan([_issue() for _ in range(3)])
        plan_many = planner.build_plan([_issue() for _ in range(30)])
        assert plan_few.confidence > plan_many.confidence

    def test_confidence_bounded(self):
        planner = RefactoringPlanner(logger=_logger())
        plan = planner.build_plan([_issue() for _ in range(100)])
        assert plan.confidence >= 0.3


class TestBuildRecommendations:
    def test_empty_list(self):
        planner = RefactoringPlanner(logger=_logger())
        recs = planner.build_recommendations([])
        assert recs == []

    def test_one_issue_one_rec(self):
        planner = RefactoringPlanner(logger=_logger())
        issues = [_issue(RefactorCategory.DEAD_CODE, RefactorSeverity.LOW, symbol="_helper")]
        recs = planner.build_recommendations(issues)
        assert len(recs) == 1
        assert recs[0].kind == RefactorKind.REMOVE_DEAD_CODE

    def test_kind_mapping(self):
        planner = RefactoringPlanner(logger=_logger())
        mappings = {
            RefactorCategory.LARGE_FILE: RefactorKind.SPLIT_FILE,
            RefactorCategory.LONG_FUNCTION: RefactorKind.EXTRACT_FUNCTION,
            RefactorCategory.DUPLICATE_LOGIC: RefactorKind.CONSOLIDATE_DUPLICATES,
            RefactorCategory.CIRCULAR_DEPENDENCY: RefactorKind.BREAK_CYCLE,
            RefactorCategory.GOD_CLASS: RefactorKind.DECOMPOSE_CLASS,
            RefactorCategory.LAYER_VIOLATION: RefactorKind.MOVE_TO_LAYER,
            RefactorCategory.NAMING_CONSISTENCY: RefactorKind.RENAME,
            RefactorCategory.DOCUMENTATION_DRIFT: RefactorKind.ADD_DOCUMENTATION,
            RefactorCategory.UNUSED_IMPORT: RefactorKind.REMOVE_UNUSED_IMPORT,
        }
        for cat, expected_kind in mappings.items():
            issues = [_issue(cat)]
            recs = planner.build_recommendations(issues)
            assert recs[0].kind == expected_kind, f"Category {cat} -> expected {expected_kind}"

    def test_priority_critical_p0(self):
        planner = RefactoringPlanner(logger=_logger())
        issues = [_issue(severity=RefactorSeverity.CRITICAL)]
        recs = planner.build_recommendations(issues)
        assert recs[0].priority == RefactorPriority.P0

    def test_priority_high_p1(self):
        planner = RefactoringPlanner(logger=_logger())
        issues = [_issue(severity=RefactorSeverity.HIGH)]
        recs = planner.build_recommendations(issues)
        assert recs[0].priority == RefactorPriority.P1

    def test_priority_medium_p2(self):
        planner = RefactoringPlanner(logger=_logger())
        issues = [_issue(severity=RefactorSeverity.MEDIUM)]
        recs = planner.build_recommendations(issues)
        assert recs[0].priority == RefactorPriority.P2

    def test_priority_low_p3(self):
        planner = RefactoringPlanner(logger=_logger())
        issues = [_issue(severity=RefactorSeverity.LOW)]
        recs = planner.build_recommendations(issues)
        assert recs[0].priority == RefactorPriority.P3

    def test_rec_includes_file(self):
        planner = RefactoringPlanner(logger=_logger())
        issues = [_issue(file="auth.py")]
        recs = planner.build_recommendations(issues)
        assert "auth.py" in recs[0].files

    def test_rec_includes_symbol(self):
        planner = RefactoringPlanner(logger=_logger())
        issues = [_issue(symbol="do_work")]
        recs = planner.build_recommendations(issues)
        assert "do_work" in recs[0].symbols

    def test_effort_trivial_for_import(self):
        planner = RefactoringPlanner(logger=_logger())
        issues = [_issue(RefactorCategory.UNUSED_IMPORT, RefactorSeverity.LOW)]
        recs = planner.build_recommendations(issues)
        assert recs[0].estimated_effort == "trivial"

    def test_effort_medium_for_high_severity(self):
        planner = RefactoringPlanner(logger=_logger())
        issues = [_issue(RefactorCategory.LARGE_FILE, RefactorSeverity.HIGH)]
        recs = planner.build_recommendations(issues)
        assert recs[0].estimated_effort == "medium"
