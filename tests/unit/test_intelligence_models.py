"""Tests for AI intelligence models."""

from __future__ import annotations

from refactory.intelligence.models import (
    AIConfidence,
    AIRefactorResult,
    AISuggestion,
    AISuggestionKind,
    AntiPattern,
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
    PatternKind,
    PatternReport,
    SmartImpactPrediction,
    SmellKind,
    SmellReport,
    TestGenResult,
    ViolationKind,
)


class TestAISuggestion:
    def test_defaults(self):
        s = AISuggestion(kind=AISuggestionKind.RENAME, title="Rename variable")
        assert s.kind == AISuggestionKind.RENAME
        assert s.risk == "low"
        assert s.confidence.score == 0.0

    def test_with_confidence(self):
        s = AISuggestion(
            kind=AISuggestionKind.EXTRACT_METHOD,
            title="Extract helper",
            confidence=AIConfidence(score=0.9, evidence=["long method"]),
        )
        assert s.confidence.score == 0.9
        assert len(s.confidence.evidence) == 1


class TestAIRefactorResult:
    def test_empty(self):
        r = AIRefactorResult()
        assert r.suggestions == []
        assert r.summary == ""

    def test_with_suggestions(self):
        r = AIRefactorResult(
            suggestions=[
                AISuggestion(kind=AISuggestionKind.RENAME, title="Rename x to count"),
            ],
            model="test-model",
        )
        assert len(r.suggestions) == 1
        assert r.model == "test-model"


class TestArchitectureViolation:
    def test_creation(self):
        v = ArchitectureViolation(
            kind=ViolationKind.CIRCULAR_DEPENDENCY,
            title="Cycle: A -> B -> A",
            severity="high",
        )
        assert v.kind == ViolationKind.CIRCULAR_DEPENDENCY
        assert v.severity == "high"


class TestArchitectureReport:
    def test_empty(self):
        r = ArchitectureReport()
        assert r.violations == []
        assert r.health_score == 100

    def test_with_violations(self):
        r = ArchitectureReport(
            violations=[
                ArchitectureViolation(
                    kind=ViolationKind.HIGH_COUPLING,
                    title="Too many deps",
                ),
            ],
            health_score=80,
        )
        assert len(r.violations) == 1
        assert r.health_score == 80


class TestDetectedPattern:
    def test_creation(self):
        p = DetectedPattern(
            kind=PatternKind.SINGLETON,
            file="config.py",
            symbol="Settings",
            confidence=0.8,
        )
        assert p.kind == PatternKind.SINGLETON
        assert p.confidence == 0.8


class TestCodeSmell:
    def test_creation(self):
        s = CodeSmell(
            kind=SmellKind.LONG_METHOD,
            file="service.py",
            symbol="process",
            detail="100 lines",
        )
        assert s.kind == SmellKind.LONG_METHOD


class TestSmellReport:
    def test_empty(self):
        r = SmellReport()
        assert r.smells == []
        assert r.total_smells == 0


class TestPatchResult:
    def test_creation(self):
        r = PatchResult(
            patches=[PatchFile(file_path="a.py", unified_diff="--- a/a.py\n+++ b/a.py")],
            files_affected=1,
        )
        assert r.files_affected == 1


class TestTestGenResult:
    def test_creation(self):
        r = TestGenResult(
            tests=[GeneratedTest(file_path="test_a.py", test_code="def test_x(): pass")],
            model="gpt-4",
        )
        assert len(r.tests) == 1


class TestDocGenResult:
    def test_creation(self):
        r = DocGenResult(
            docs=[GeneratedDoc(target="module.py", content="Module docs")],
            model="gpt-4",
        )
        assert len(r.docs) == 1


class TestArchitectureSummary:
    def test_creation(self):
        s = ArchitectureSummary(
            components=[ComponentInfo(name="core", responsibility="Business logic")],
        )
        assert len(s.components) == 1


class TestSmartImpactPrediction:
    def test_defaults(self):
        p = SmartImpactPrediction()
        assert p.deployment_risk == "low"
        assert p.rollback_risk == "low"


class TestArchitectureAdvice:
    def test_defaults(self):
        a = ArchitectureAdvice()
        assert a.modularization == []


class TestFileExplanation:
    def test_creation(self):
        e = FileExplanation(
            file_path="auth.py",
            purpose="Authentication",
            business_role="Security",
        )
        assert e.file_path == "auth.py"


class TestAllSuggestionKinds:
    def test_all_kinds(self):
        kinds = list(AISuggestionKind)
        assert len(kinds) >= 6

    def test_all_violation_kinds(self):
        kinds = list(ViolationKind)
        assert len(kinds) >= 5

    def test_all_pattern_kinds(self):
        kinds = list(PatternKind)
        assert len(kinds) >= 9

    def test_all_smell_kinds(self):
        kinds = list(SmellKind)
        assert len(kinds) >= 8


class TestConfidence:
    def test_empty_confidence(self):
        c = AIConfidence()
        assert c.score == 0.0
        assert c.evidence == []
        assert c.reasoning == ""

    def test_full_confidence(self):
        c = AIConfidence(
            score=0.95,
            evidence=["test1", "test2"],
            related_files=["a.py"],
            reasoning="Strong evidence",
        )
        assert c.score == 0.95
        assert len(c.evidence) == 2
