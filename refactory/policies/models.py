"""Models for architecture policies."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ArchitectureLayer(BaseModel):
    """A single layer in the architecture stack."""

    name: str
    patterns: list[str] = Field(default_factory=list)
    allowed_dependencies: list[str] = Field(default_factory=list)
    description: str = ""


class ArchitecturePolicy(BaseModel):
    """Complete architecture policy definition."""

    name: str = "default"
    description: str = ""
    layers: list[ArchitectureLayer] = Field(default_factory=list)
    forbidden_cross_dependencies: list[tuple[str, str]] = Field(default_factory=list)


class ViolationType(str, Enum):
    LAYER_VIOLATION = "layer_violation"
    CIRCULAR_DEPENDENCY = "circular_dependency"
    FORBIDDEN_IMPORT = "forbidden_import"
    CROSS_DOMAIN = "cross_domain"


class PolicyViolation(BaseModel):
    """A detected architecture policy violation."""

    violation_type: ViolationType
    source_file: str = ""
    target_file: str = ""
    source_layer: str = ""
    target_layer: str = ""
    description: str = ""
    severity: str = "error"


class PolicyReport(BaseModel):
    """Architecture policy evaluation result."""

    violations: list[PolicyViolation] = Field(default_factory=list)
    layers_checked: int = 0
    files_checked: int = 0
    passed: bool = True
