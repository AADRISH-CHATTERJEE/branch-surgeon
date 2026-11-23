"""Typed models for local documentation intelligence (no LLM)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class DocTargetKind(str, Enum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    PACKAGE = "package"
    README = "readme"
    UNKNOWN = "unknown"


class DocQuality(str, Enum):
    MISSING = "missing"
    POOR = "poor"
    BASIC = "basic"
    GOOD = "good"


class DocGap(BaseModel):
    """A missing or weak documentation site."""

    path: str
    symbol: str | None = None
    kind: DocTargetKind = DocTargetKind.UNKNOWN
    reason: str = ""
    quality: DocQuality = DocQuality.MISSING
    line: int | None = None


class DocEntry(BaseModel):
    """Documentation present for a symbol or module."""

    path: str
    symbol: str | None = None
    kind: DocTargetKind = DocTargetKind.UNKNOWN
    docstring: str | None = None
    quality: DocQuality = DocQuality.MISSING
    line: int | None = None
    is_public: bool = True


class StaleDoc(BaseModel):
    """Documentation that appears older than related source."""

    path: str
    related_source: str | None = None
    doc_mtime: datetime | None = None
    source_mtime: datetime | None = None
    reason: str = ""
    confidence: float = 0.0


class ModuleSummary(BaseModel):
    """Deterministic module summary from parser/index/graph data."""

    path: str
    module_name: str
    docstring: str | None = None
    classes: list[str] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    public_api: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    dependents: list[str] = Field(default_factory=list)
    owners: list[str] = Field(default_factory=list)
    has_readme: bool = False
    docstring_coverage: float = 0.0
    todo_docs: list[str] = Field(default_factory=list)


class PackageNode(BaseModel):
    """One package / directory in the repository structure."""

    path: str
    modules: list[str] = Field(default_factory=list)
    packages: list[str] = Field(default_factory=list)
    has_readme: bool = False
    has_init: bool = False


class RepositoryStructure(BaseModel):
    """Deterministic repository package/module tree."""

    root: str
    packages: list[PackageNode] = Field(default_factory=list)
    top_level_modules: list[str] = Field(default_factory=list)
    readme_files: list[str] = Field(default_factory=list)


class DocumentationCoverage(BaseModel):
    """Aggregate documentation coverage metrics."""

    total_modules: int = 0
    documented_modules: int = 0
    total_classes: int = 0
    documented_classes: int = 0
    total_functions: int = 0
    documented_functions: int = 0
    total_public_api: int = 0
    documented_public_api: int = 0
    modules_with_readme: int = 0
    packages_missing_readme: int = 0
    module_coverage: float = 0.0
    class_coverage: float = 0.0
    function_coverage: float = 0.0
    public_api_coverage: float = 0.0
    overall_coverage: float = 0.0


class FileDocsReport(BaseModel):
    """Documentation analysis for a single file."""

    path: str
    module: ModuleSummary | None = None
    entries: list[DocEntry] = Field(default_factory=list)
    gaps: list[DocGap] = Field(default_factory=list)
    coverage: float = 0.0


class SymbolDocsReport(BaseModel):
    """Documentation analysis for a symbol."""

    symbol: str
    entries: list[DocEntry] = Field(default_factory=list)
    gaps: list[DocGap] = Field(default_factory=list)
    found: bool = False


class RepositoryDocsReport(BaseModel):
    """Full repository documentation intelligence snapshot."""

    root: str
    coverage: DocumentationCoverage = Field(default_factory=DocumentationCoverage)
    missing_docstrings: list[DocGap] = Field(default_factory=list)
    missing_readmes: list[DocGap] = Field(default_factory=list)
    stale_docs: list[StaleDoc] = Field(default_factory=list)
    public_api_without_docs: list[DocGap] = Field(default_factory=list)
    todo_documentation: list[DocGap] = Field(default_factory=list)
    structure: RepositoryStructure | None = None
    module_count: int = 0
    notes: list[str] = Field(default_factory=list)
