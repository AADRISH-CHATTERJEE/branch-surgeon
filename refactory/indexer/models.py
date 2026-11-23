"""Typed models for deterministic repository indexing (no embeddings)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SymbolKind(str, Enum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    NESTED_FUNCTION = "nested_function"


class IndexedSymbol(BaseModel):
    """A discoverable symbol for later lookup / retrieval."""

    name: str
    kind: SymbolKind
    file_path: str
    start_line: int
    end_line: int
    parent: str | None = None
    decorators: list[str] = Field(default_factory=list)
    is_async: bool = False
    is_generator: bool = False
    # Class inheritance bases (empty for non-class symbols).
    bases: list[str] = Field(default_factory=list)


class ImportReference(BaseModel):
    """Cross-file import edge (supports 'who imports auth?' queries later)."""

    source_file: str
    source_module: str
    target_module: str
    symbol: str | None = None
    kind: str = "import"
    start_line: int | None = None


class IndexedFile(BaseModel):
    """Per-file index entry with content hash for future incremental indexing."""

    relative_path: str
    language: str
    file_size: int = 0
    content_hash: str
    modified_at: datetime | None = None
    module_name: str
    classes: list[str] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list)
    nested_functions: list[str] = Field(default_factory=list)
    decorators: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    comments: list[str] = Field(default_factory=list)
    todo_tags: list[str] = Field(default_factory=list)
    symbols: list[IndexedSymbol] = Field(default_factory=list)
    import_references: list[ImportReference] = Field(default_factory=list)
    has_syntax_errors: bool = False
    parse_error: str | None = None


class RepositoryStatistics(BaseModel):
    """What happened during the current indexing operation (this run)."""

    files_parsed: int = 0
    reused_unchanged_files: int = 0
    newly_added_files: int = 0
    modified_files: int = 0
    deleted_files: int = 0
    ignored_files: int = 0
    unsupported_file_count: int = 0
    parse_failures: int = 0
    indexing_duration_seconds: float = 0.0


class RepositorySummary(BaseModel):
    """Repository state after indexing (totals across the index)."""

    repository_root: str
    repository_name: str
    total_indexed_files: int = 0
    ignored_file_count: int = 0
    total_functions: int = 0
    total_classes: int = 0
    total_imports: int = 0
    todo_count: int = 0
    languages: dict[str, int] = Field(default_factory=dict)
    timestamp: datetime


class RepositoryIndex(BaseModel):
    """Full repository index — persisted under `.refactory/` for reuse."""

    summary: RepositorySummary
    statistics: RepositoryStatistics
    files: list[IndexedFile] = Field(default_factory=list)
    symbols: list[IndexedSymbol] = Field(default_factory=list)
    import_references: list[ImportReference] = Field(default_factory=list)
    # path -> content_hash for incremental reindex decisions
    file_hashes: dict[str, str] = Field(default_factory=dict)
