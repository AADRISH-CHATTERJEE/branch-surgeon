"""Local documentation intelligence — extract and organize docs (no LLM)."""

from refactory.documentation.models import (
    DocEntry,
    DocGap,
    DocQuality,
    DocTargetKind,
    DocumentationCoverage,
    FileDocsReport,
    ModuleSummary,
    PackageNode,
    RepositoryDocsReport,
    RepositoryStructure,
    StaleDoc,
    SymbolDocsReport,
)
from refactory.documentation.service import DocumentationService

__all__ = [
    "DocEntry",
    "DocGap",
    "DocQuality",
    "DocTargetKind",
    "DocumentationCoverage",
    "DocumentationService",
    "FileDocsReport",
    "ModuleSummary",
    "PackageNode",
    "RepositoryDocsReport",
    "RepositoryStructure",
    "StaleDoc",
    "SymbolDocsReport",
]
