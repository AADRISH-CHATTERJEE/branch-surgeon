"""Typed models for deterministic semantic retrieval."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class EntityKind(str, Enum):
    FILE = "file"
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"


class SimilarityScore(BaseModel):
    """Numeric relevance score for a single candidate."""

    value: float
    metric: str = "cosine"


class SearchQuery(BaseModel):
    """Normalized search request."""

    text: str
    top_k: int = 8
    metric: str = "cosine"


class RetrievedSymbol(BaseModel):
    """A ranked symbol (or file/module entity) from the embedding store."""

    result: str
    score: float
    file_path: str
    module_name: str
    symbol: str
    kind: EntityKind
    metric: str = "cosine"


class RetrievedFile(BaseModel):
    """A file-level retrieval hit (aggregated or direct file vector)."""

    file_path: str
    module_name: str
    score: float
    metric: str = "cosine"
    best_symbol: str | None = None
    best_kind: EntityKind | None = None


class RetrievalStatistics(BaseModel):
    """Counters for a single retrieval operation."""

    candidates_scanned: int = 0
    candidates_skipped: int = 0
    results_returned: int = 0
    embedding_model: str = ""
    metric: str = "cosine"
    store_path: str = ""


class SearchResult(BaseModel):
    """Typed response for semantic search APIs."""

    query: SearchQuery
    hits: list[RetrievedSymbol] = Field(default_factory=list)
    statistics: RetrievalStatistics = Field(default_factory=RetrievalStatistics)


class RankedContextEntry(BaseModel):
    """One file in a hybrid-ranked review context pack."""

    file_path: str
    module_name: str = ""
    score: float = 0.0
    semantic_score: float = 0.0
    graph_score: float = 0.0
    reasons: list[str] = Field(default_factory=list)
    best_symbol: str | None = None
    kind: EntityKind | None = None


class RankedContext(BaseModel):
    """Hybrid retrieval result for prompt assembly."""

    query: str = ""
    entries: list[RankedContextEntry] = Field(default_factory=list)
    symbols: list[RetrievedSymbol] = Field(default_factory=list)
