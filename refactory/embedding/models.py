"""Typed models for repository embedding generation and JSON persistence."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class EmbeddingTarget(BaseModel):
    """A single entity prepared for embedding."""

    entity_key: str
    entity_kind: str  # file | module | class | function
    file_path: str
    text: str


class FileEmbeddingRecord(BaseModel):
    """Per-file embedding payload persisted under embeddings.json."""

    hash: str
    file: list[float] = Field(default_factory=list)
    module: list[float] = Field(default_factory=list)
    classes: dict[str, list[float]] = Field(default_factory=dict)
    functions: dict[str, list[float]] = Field(default_factory=dict)


class EmbeddingStore(BaseModel):
    """Temporary JSON store for repository embeddings (pre-VectorStore)."""

    model: str
    updated_at: datetime | None = None
    files: dict[str, FileEmbeddingRecord] = Field(default_factory=dict)


class EmbeddingRunResult(BaseModel):
    """Summary of one embedding pass over a RepositoryIndex.

    Repository fields describe store state after the run.
    This-run fields describe only what happened during the current operation.
    """

    model: str = ""
    # Repository totals (after this run)
    repository_symbols: int = 0
    total_stored_vectors: int = 0
    # This run
    files_processed: int = 0
    embedded: int = 0  # files newly embedded this run
    skipped: int = 0  # files reused via unchanged hash
    newly_embedded_symbols: int = 0
    reused_vectors: int = 0
    # Backward-compatible alias for newly_embedded_symbols (this run only)
    symbols_embedded: int = 0
    elapsed_seconds: float = 0.0
    storage_path: str = ""


class EmbeddingStatus(BaseModel):
    """Status view for `refactory embed status`."""

    model: str
    total_embedded_symbols: int = 0
    total_files: int = 0
    last_update: datetime | None = None
    storage_path: str
    store_exists: bool = False
