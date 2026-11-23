"""Strongly typed models for the Transformation Engine."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class TransformationType(str, Enum):
    RENAME_SYMBOL = "rename_symbol"
    RENAME_FUNCTION = "rename_function"
    RENAME_CLASS = "rename_class"
    RENAME_VARIABLE = "rename_variable"
    RENAME_MODULE = "rename_module"
    RENAME_FILE = "rename_file"
    EXTRACT_METHOD = "extract_method"
    EXTRACT_CLASS = "extract_class"
    MOVE_METHOD = "move_method"
    MOVE_CLASS = "move_class"
    MOVE_SYMBOL = "move_symbol"
    INLINE_METHOD = "inline_method"
    CHANGE_SIGNATURE = "change_signature"
    REMOVE_DEAD_CODE = "remove_dead_code"
    REPLACE_DEPRECATED_API = "replace_deprecated_api"
    UPDATE_IMPORTS = "update_imports"
    CREATE_FILE = "create_file"
    DELETE_FILE = "delete_file"
    CREATE_INTERFACE = "create_interface"
    SPLIT_LARGE_CLASS = "split_large_class"
    GENERATE_DOCSTRINGS = "generate_docstrings"
    GENERATE_TESTS = "generate_tests"
    FIX_RULE_VIOLATIONS = "fix_rule_violations"
    ARCHITECTURE_REFACTORING = "architecture_refactoring"
    AI_PLAN = "ai_plan"


class TransformationStatus(str, Enum):
    PLANNED = "planned"
    GENERATED = "generated"
    VALIDATED = "validated"
    APPLIED = "applied"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"
    CONFLICT = "conflict"


class ValidationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    WARNINGS = "warnings"
    SKIPPED = "skipped"


class ConflictType(str, Enum):
    OVERLAPPING_EDIT = "overlapping_edit"
    MODIFIED_FILE = "modified_file"
    DELETED_FILE = "deleted_file"
    MERGE_CONFLICT = "merge_conflict"
    INVALID_LINE_MAPPING = "invalid_line_mapping"


class TransformationRequest(BaseModel):
    """Request to generate a transformation from a recommendation."""

    recommendation_id: str = ""
    transformation_type: TransformationType = TransformationType.RENAME_SYMBOL
    target_file: str = ""
    target_symbol: str = ""
    parameters: dict = Field(default_factory=dict)
    ai_assisted: bool = False
    # Natural-language goal for the AI Refactoring Planner (Phase 2).
    natural_language: str = ""
    # file | repository — rename defaults to repository-wide via symbol index.
    scope: str = ""


class TransformationStep(BaseModel):
    """A single file-level change within a transformation plan."""

    file_path: str
    action: str = "modify"  # modify | create | delete | rename_file
    original_content: str = ""
    new_content: str = ""
    start_line: int = 0
    end_line: int = 0
    description: str = ""


class PlanOperation(BaseModel):
    """High-level operation inside an intelligent TransformationPlan."""

    op: str  # rename | extract | inline | move | create_file | delete_file | update_imports | update_references
    description: str = ""
    target: str = ""
    files: list[str] = Field(default_factory=list)


class TransformationPlan(BaseModel):
    """A complete plan for implementing a transformation."""

    id: str = Field(default_factory=lambda: f"TP-{uuid.uuid4().hex[:6].upper()}")
    transformation_type: TransformationType = TransformationType.RENAME_SYMBOL
    steps: list[TransformationStep] = Field(default_factory=list)
    description: str = ""
    goal: str = ""
    operations: list[PlanOperation] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    estimated_risk: str = "low"
    estimated_confidence: float = 0.0
    affected_files: list[str] = Field(default_factory=list)
    affected_symbols: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PatchHunk(BaseModel):
    """A single hunk in a unified diff patch."""

    file_path: str
    original_start: int = 1
    original_count: int = 0
    new_start: int = 1
    new_count: int = 0
    content: str = ""


class TransformationPatch(BaseModel):
    """A unified diff patch ready for `git apply`."""

    id: str = Field(default_factory=lambda: f"PA-{uuid.uuid4().hex[:6].upper()}")
    plan_id: str = ""
    diff_content: str = ""
    files_modified: list[str] = Field(default_factory=list)
    hunks: list[PatchHunk] = Field(default_factory=list)
    additions: int = 0
    deletions: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PatchStatistics(BaseModel):
    """Statistics for a generated patch."""

    files_modified: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    hunks_count: int = 0
    estimated_review_time: str = ""


class TransformationConflict(BaseModel):
    """Detected conflict preventing a patch from being applied."""

    conflict_type: ConflictType
    file_path: str = ""
    description: str = ""
    line_range: tuple[int, int] = (0, 0)


class ValidationCheck(BaseModel):
    """A single validation check result."""

    name: str
    status: ValidationStatus = ValidationStatus.PASSED
    message: str = ""


class TransformationValidation(BaseModel):
    """Complete validation result for a patch."""

    status: ValidationStatus = ValidationStatus.PASSED
    checks: list[ValidationCheck] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TransformationPreview(BaseModel):
    """Preview information for a transformation before apply."""

    plan_id: str = ""
    patch_id: str = ""
    description: str = ""
    goal: str = ""
    operations: list[PlanOperation] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    additions: int = 0
    deletions: int = 0
    modified_symbols: list[str] = Field(default_factory=list)
    risk: str = "low"
    affected_modules: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    estimated_review_time: str = ""
    diff_preview: str = ""
    rollback_available: bool = True
    validation: TransformationValidation = Field(default_factory=TransformationValidation)
    plan: TransformationPlan | None = None


class TransformationResult(BaseModel):
    """Final result after applying a transformation."""

    id: str = Field(default_factory=lambda: f"TR-{uuid.uuid4().hex[:6].upper()}")
    plan_id: str = ""
    patch_id: str = ""
    status: TransformationStatus = TransformationStatus.APPLIED
    files_modified: list[str] = Field(default_factory=list)
    validation: TransformationValidation = Field(default_factory=TransformationValidation)
    duration_ms: float = 0.0
    rollback_available: bool = True
    applied_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TransformationHistory(BaseModel):
    """Historical record of a transformation execution."""

    id: str = Field(default_factory=lambda: f"TH-{uuid.uuid4().hex[:6].upper()}")
    plan_id: str = ""
    patch_id: str = ""
    result_id: str = ""
    status: TransformationStatus = TransformationStatus.PLANNED
    transformation_type: TransformationType = TransformationType.RENAME_SYMBOL
    description: str = ""
    target_file: str = ""
    target_symbol: str = ""
    files_modified: list[str] = Field(default_factory=list)
    patch_content: str = ""
    rollback_patch: str = ""
    steps: list[TransformationStep] = Field(default_factory=list)
    validation_status: ValidationStatus = ValidationStatus.PASSED
    duration_ms: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    rolled_back_at: datetime | None = None

    @property
    def rolled_back(self) -> bool:
        return self.status == TransformationStatus.ROLLED_BACK

    @property
    def can_rollback(self) -> bool:
        return self.status == TransformationStatus.APPLIED


class TransformationError(Exception):
    """Raised when a transformation cannot be planned or applied safely."""

    def __init__(
        self,
        message: str,
        *,
        reason: str = "",
        errors: list[str] | None = None,
        meta: dict | None = None,
        status_code: int = 422,
    ) -> None:
        super().__init__(message)
        self.message = message or "Transformation failed"
        detail = reason or message or "Invalid transformation request."
        self.reason = detail
        self.errors = [e for e in (errors or [detail]) if e]
        if not self.errors:
            self.errors = ["Invalid transformation request."]
        self.meta = dict(meta or {})
        self.status_code = int(status_code)
