"""Tests for refactoring engine models — serialization, defaults, enums."""

from __future__ import annotations

import json

import pytest

from refactory.refactor.models import (
    RefactorAnalysis,
    RefactorCategory,
    RefactorIssue,
    RefactorKind,
    RefactorMetrics,
    RefactorPlan,
    RefactorPriority,
    RefactorRecommendation,
    RefactorSeverity,
)


class TestEnums:
    def test_severity_values(self):
        assert RefactorSeverity.LOW.value == "low"
        assert RefactorSeverity.MEDIUM.value == "medium"
        assert RefactorSeverity.HIGH.value == "high"
        assert RefactorSeverity.CRITICAL.value == "critical"

    def test_category_values(self):
        assert len(RefactorCategory) == 10
        assert RefactorCategory.LARGE_FILE.value == "large_file"
        assert RefactorCategory.DEAD_CODE.value == "dead_code"
        assert RefactorCategory.CIRCULAR_DEPENDENCY.value == "circular_dependency"

    def test_kind_values(self):
        assert RefactorKind.SPLIT_FILE.value == "split_file"
        assert RefactorKind.EXTRACT_FUNCTION.value == "extract_function"
        assert RefactorKind.REMOVE_DEAD_CODE.value == "remove_dead_code"

    def test_priority_values(self):
        assert RefactorPriority.P0.value == "p0"
        assert RefactorPriority.P3.value == "p3"

    def test_category_from_string(self):
        assert RefactorCategory("dead_code") == RefactorCategory.DEAD_CODE

    def test_severity_from_string(self):
        assert RefactorSeverity("high") == RefactorSeverity.HIGH

    def test_invalid_category_raises(self):
        with pytest.raises(ValueError):
            RefactorCategory("nonexistent")


class TestRefactorIssue:
    def test_minimal(self):
        issue = RefactorIssue(
            category=RefactorCategory.DEAD_CODE,
            severity=RefactorSeverity.LOW,
            title="Dead code: foo",
        )
        assert issue.file == ""
        assert issue.symbol == ""
        assert issue.line is None
        assert issue.metrics == {}
        assert issue.detail == ""

    def test_full(self):
        issue = RefactorIssue(
            category=RefactorCategory.LARGE_FILE,
            severity=RefactorSeverity.HIGH,
            title="Large file: auth.py",
            detail="500 lines",
            file="auth.py",
            symbol="",
            line=1,
            metrics={"lines": 500},
        )
        assert issue.metrics["lines"] == 500

    def test_json_round_trip(self):
        issue = RefactorIssue(
            category=RefactorCategory.UNUSED_IMPORT,
            severity=RefactorSeverity.LOW,
            title="Unused import: os",
            file="main.py",
            symbol="os",
            line=3,
        )
        data = json.loads(issue.model_dump_json())
        restored = RefactorIssue(**data)
        assert restored.category == RefactorCategory.UNUSED_IMPORT
        assert restored.symbol == "os"

    def test_issue_with_empty_metrics(self):
        issue = RefactorIssue(
            category=RefactorCategory.NAMING_CONSISTENCY,
            severity=RefactorSeverity.LOW,
            title="t",
        )
        assert issue.metrics == {}


class TestRefactorRecommendation:
    def test_minimal(self):
        rec = RefactorRecommendation(
            kind=RefactorKind.EXTRACT_FUNCTION,
            priority=RefactorPriority.P1,
            title="Extract long function",
        )
        assert rec.files == []
        assert rec.symbols == []
        assert rec.estimated_effort == ""

    def test_full(self):
        rec = RefactorRecommendation(
            kind=RefactorKind.SPLIT_FILE,
            priority=RefactorPriority.P0,
            title="Split auth.py",
            detail="File has 800 lines",
            files=["auth.py"],
            symbols=["AuthManager"],
            estimated_effort="medium",
        )
        assert rec.files == ["auth.py"]

    def test_json_round_trip(self):
        rec = RefactorRecommendation(
            kind=RefactorKind.REMOVE_DEAD_CODE,
            priority=RefactorPriority.P2,
            title="Remove _helper",
            files=["utils.py"],
        )
        data = json.loads(rec.model_dump_json())
        restored = RefactorRecommendation(**data)
        assert restored.kind == RefactorKind.REMOVE_DEAD_CODE


class TestRefactorMetrics:
    def test_defaults(self):
        m = RefactorMetrics()
        assert m.health_score == 100
        assert m.grade == "A"
        assert m.total_issues == 0
        assert m.files_analyzed == 0

    def test_custom_values(self):
        m = RefactorMetrics(
            files_analyzed=50,
            total_issues=15,
            critical_issues=2,
            health_score=60,
            grade="C",
        )
        assert m.critical_issues == 2
        assert m.grade == "C"


class TestRefactorPlan:
    def test_defaults(self):
        plan = RefactorPlan()
        assert plan.steps == []
        assert plan.confidence == 0.0
        assert plan.estimated_risk == "low"

    def test_with_steps(self):
        plan = RefactorPlan(
            steps=["1. Split auth.py", "2. Remove dead code"],
            estimated_effort="medium (1-4 hours)",
            estimated_risk="low",
            confidence=0.85,
        )
        assert len(plan.steps) == 2

    def test_json_round_trip(self):
        plan = RefactorPlan(steps=["1. Do X"], confidence=0.9)
        data = json.loads(plan.model_dump_json())
        restored = RefactorPlan(**data)
        assert restored.confidence == 0.9


class TestRefactorAnalysis:
    def test_defaults(self):
        analysis = RefactorAnalysis()
        assert analysis.scope == "repository"
        assert analysis.issues == []
        assert analysis.recommendations == []
        assert analysis.plan.steps == []
        assert analysis.notes == []

    def test_full_analysis_json(self):
        analysis = RefactorAnalysis(
            scope="file",
            target="auth.py",
            issues=[
                RefactorIssue(
                    category=RefactorCategory.DEAD_CODE,
                    severity=RefactorSeverity.LOW,
                    title="Dead code: _helper",
                )
            ],
            recommendations=[
                RefactorRecommendation(
                    kind=RefactorKind.REMOVE_DEAD_CODE,
                    priority=RefactorPriority.P3,
                    title="Remove _helper",
                )
            ],
            metrics=RefactorMetrics(total_issues=1, health_score=99),
            plan=RefactorPlan(steps=["1. Remove _helper"]),
            notes=["Scoped to auth.py"],
        )
        data = json.loads(analysis.model_dump_json())
        assert data["scope"] == "file"
        assert len(data["issues"]) == 1

    def test_empty_analysis_serializes(self):
        analysis = RefactorAnalysis()
        data = analysis.model_dump()
        assert data["scope"] == "repository"
        assert data["metrics"]["health_score"] == 100
