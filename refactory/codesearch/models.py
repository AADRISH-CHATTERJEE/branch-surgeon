"""Typed models for local code search and semantic navigation."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class CodeHitKind(str, Enum):
    FILE = "file"
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    NESTED_FUNCTION = "nested_function"
    IMPORT = "import"
    COMMENT = "comment"
    TODO = "todo"
    DEFINITION = "definition"
    REFERENCE = "reference"
    CALLER = "caller"
    CALLEE = "callee"
    RELATED = "related"


class CodeSearchHit(BaseModel):
    """One ranked navigation / search hit."""

    file: str
    line: int | None = None
    symbol: str = ""
    type: str = CodeHitKind.FILE.value
    snippet: str = ""
    score: float = 0.0
    confidence: float = 0.0
    reasons: list[str] = Field(default_factory=list)


class CodeSearchResult(BaseModel):
    """Typed response for CodeSearchService queries."""

    query: str = ""
    hits: list[CodeSearchHit] = Field(default_factory=list)
    structural_hits: int = 0
    semantic_hits: int = 0
    notes: list[str] = Field(default_factory=list)
