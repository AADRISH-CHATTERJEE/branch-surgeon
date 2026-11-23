"""Models for AI-powered intelligence features."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# AI Refactoring Suggestions (Task 1)
# ---------------------------------------------------------------------------

class AISuggestionKind(str, Enum):
    RENAME = "rename"
    EXTRACT_METHOD = "extract_method"
    EXTRACT_CLASS = "extract_class"
    REMOVE_DUPLICATION = "remove_duplication"
    SIMPLIFY_CONDITIONAL = "simplify_conditional"
    REDUCE_COMPLEXITY = "reduce_complexity"
    INLINE_VARIABLE = "inline_variable"
    INTRODUCE_PARAMETER_OBJECT = "introduce_parameter_object"


class AIConfidence(BaseModel):
    """Confidence metadata for an AI recommendation (Task 10)."""

    score: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    related_files: list[str] = Field(default_factory=list)
    reasoning: str = ""


class AISuggestion(BaseModel):
    """A single AI-generated refactoring suggestion."""

    kind: AISuggestionKind
    title: str
    description: str = ""
    file: str = ""
    symbol: str = ""
    line: int | None = None
    why: str = ""
    benefits: str = ""
    risk: str = "low"
    estimated_effort: str = ""
    confidence: AIConfidence = Field(default_factory=AIConfidence)


class AIRefactorResult(BaseModel):
    """Complete AI refactoring analysis."""

    suggestions: list[AISuggestion] = Field(default_factory=list)
    summary: str = ""
    model: str = ""
    provider: str = ""


# ---------------------------------------------------------------------------
# Architecture Violations (Task 3)
# ---------------------------------------------------------------------------

class ViolationKind(str, Enum):
    CIRCULAR_DEPENDENCY = "circular_dependency"
    LAYER_VIOLATION = "layer_violation"
    DEPENDENCY_INVERSION = "dependency_inversion"
    HIGH_COUPLING = "high_coupling"
    GOD_CLASS = "god_class"
    SERVICE_UI_IMPORT = "service_ui_import"


class ArchitectureViolation(BaseModel):
    kind: ViolationKind
    title: str
    detail: str = ""
    files: list[str] = Field(default_factory=list)
    severity: str = "medium"
    fix_suggestion: str = ""


class ArchitectureReport(BaseModel):
    violations: list[ArchitectureViolation] = Field(default_factory=list)
    summary: str = ""
    health_score: int = 100


# ---------------------------------------------------------------------------
# Design Pattern Detection (Task 4)
# ---------------------------------------------------------------------------

class PatternKind(str, Enum):
    SINGLETON = "singleton"
    FACTORY = "factory"
    BUILDER = "builder"
    STRATEGY = "strategy"
    REPOSITORY = "repository"
    ADAPTER = "adapter"
    DECORATOR = "decorator"
    OBSERVER = "observer"
    VISITOR = "visitor"


class DetectedPattern(BaseModel):
    kind: PatternKind
    file: str
    symbol: str = ""
    confidence: float = 0.0
    evidence: str = ""


class AntiPattern(BaseModel):
    name: str
    file: str
    detail: str = ""
    fix_suggestion: str = ""


class PatternReport(BaseModel):
    patterns: list[DetectedPattern] = Field(default_factory=list)
    anti_patterns: list[AntiPattern] = Field(default_factory=list)
    summary: str = ""


# ---------------------------------------------------------------------------
# Code Smell Detection (Task 5)
# ---------------------------------------------------------------------------

class SmellKind(str, Enum):
    LONG_METHOD = "long_method"
    LARGE_CLASS = "large_class"
    FEATURE_ENVY = "feature_envy"
    SHOTGUN_SURGERY = "shotgun_surgery"
    DATA_CLASS = "data_class"
    PRIMITIVE_OBSESSION = "primitive_obsession"
    DUPLICATED_CODE = "duplicated_code"
    MESSAGE_CHAINS = "message_chains"


class CodeSmell(BaseModel):
    kind: SmellKind
    file: str
    symbol: str = ""
    line: int | None = None
    detail: str = ""
    severity: str = "medium"
    why: str = ""
    benefits: str = ""
    risk: str = "low"
    estimated_effort: str = ""


class SmellReport(BaseModel):
    smells: list[CodeSmell] = Field(default_factory=list)
    summary: str = ""
    total_smells: int = 0


# ---------------------------------------------------------------------------
# Patch Generation (Task 2)
# ---------------------------------------------------------------------------

class PatchFile(BaseModel):
    file_path: str
    original_content: str = ""
    patched_content: str = ""
    unified_diff: str = ""


class PatchResult(BaseModel):
    patches: list[PatchFile] = Field(default_factory=list)
    summary: str = ""
    files_affected: int = 0


# ---------------------------------------------------------------------------
# Test Generation (Task 7)
# ---------------------------------------------------------------------------

class GeneratedTest(BaseModel):
    file_path: str
    test_code: str
    target_file: str = ""
    target_symbol: str = ""
    test_kind: str = "unit"
    covers: list[str] = Field(default_factory=list)


class TestGenResult(BaseModel):
    tests: list[GeneratedTest] = Field(default_factory=list)
    summary: str = ""
    model: str = ""


# ---------------------------------------------------------------------------
# Documentation Generator (Task 8)
# ---------------------------------------------------------------------------

class GeneratedDoc(BaseModel):
    target: str
    kind: str = "module"
    content: str = ""
    file_path: str = ""


class DocGenResult(BaseModel):
    docs: list[GeneratedDoc] = Field(default_factory=list)
    summary: str = ""
    model: str = ""


# ---------------------------------------------------------------------------
# Architectural Summary (Task 9)
# ---------------------------------------------------------------------------

class ComponentInfo(BaseModel):
    name: str
    files: list[str] = Field(default_factory=list)
    responsibility: str = ""
    dependencies: list[str] = Field(default_factory=list)


class ArchitectureSummary(BaseModel):
    components: list[ComponentInfo] = Field(default_factory=list)
    dependency_summary: str = ""
    critical_paths: list[str] = Field(default_factory=list)
    module_responsibilities: dict[str, str] = Field(default_factory=dict)
    summary: str = ""


# ---------------------------------------------------------------------------
# Smart Impact Analysis (Task 14)
# ---------------------------------------------------------------------------

class SmartImpactPrediction(BaseModel):
    likely_bugs: list[str] = Field(default_factory=list)
    affected_apis: list[str] = Field(default_factory=list)
    affected_tests: list[str] = Field(default_factory=list)
    deployment_risk: str = "low"
    rollback_risk: str = "low"
    summary: str = ""
    confidence: AIConfidence = Field(default_factory=AIConfidence)


# ---------------------------------------------------------------------------
# AI Architecture Advisor (Task 15)
# ---------------------------------------------------------------------------

class ArchitectureAdvice(BaseModel):
    modularization: list[str] = Field(default_factory=list)
    split_suggestions: list[str] = Field(default_factory=list)
    dependency_cleanup: list[str] = Field(default_factory=list)
    layer_improvements: list[str] = Field(default_factory=list)
    summary: str = ""
    confidence: AIConfidence = Field(default_factory=AIConfidence)


# ---------------------------------------------------------------------------
# Explain Command (Task 13)
# ---------------------------------------------------------------------------

class FileExplanation(BaseModel):
    file_path: str
    purpose: str = ""
    dependencies: list[str] = Field(default_factory=list)
    callers: list[str] = Field(default_factory=list)
    callees: list[str] = Field(default_factory=list)
    business_role: str = ""
    summary: str = ""
