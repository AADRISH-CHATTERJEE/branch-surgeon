"""Canonical structured representation of source code (no Tree-sitter types)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ImportKind(str, Enum):
    STDLIB = "stdlib"
    THIRD_PARTY = "third_party"
    LOCAL = "local"
    UNKNOWN = "unknown"


class CommentTag(str, Enum):
    TODO = "TODO"
    FIXME = "FIXME"
    HACK = "HACK"
    NOTE = "NOTE"
    NONE = "NONE"


class ParsedParameter(BaseModel):
    name: str
    type_hint: str | None = None
    default: str | None = None


class ParsedFunction(BaseModel):
    name: str
    parameters: list[ParsedParameter] = Field(default_factory=list)
    return_type: str | None = None
    start_line: int
    end_line: int
    docstring: str | None = None
    decorators: list[str] = Field(default_factory=list)
    is_async: bool = False
    is_generator: bool = False
    is_method: bool = False
    parent_class: str | None = None
    parent_function: str | None = None
    nested_functions: list[ParsedFunction] = Field(default_factory=list)


class ParsedClass(BaseModel):
    name: str
    bases: list[str] = Field(default_factory=list)
    methods: list[ParsedFunction] = Field(default_factory=list)
    properties: list[str] = Field(default_factory=list)
    decorators: list[str] = Field(default_factory=list)
    docstring: str | None = None
    start_line: int
    end_line: int


class ParsedImport(BaseModel):
    module: str
    names: list[str] = Field(default_factory=list)
    alias: str | None = None
    kind: ImportKind = ImportKind.UNKNOWN
    is_from_import: bool = False
    start_line: int
    end_line: int
    raw: str = ""


class ParsedComment(BaseModel):
    text: str
    start_line: int
    end_line: int
    tag: CommentTag = CommentTag.NONE
    is_block: bool = False


class ParsedVariable(BaseModel):
    name: str
    value_preview: str | None = None
    type_hint: str | None = None
    is_constant: bool = False
    start_line: int
    end_line: int


class ParsedReference(BaseModel):
    """Cross-file / symbol relationship extracted from imports and calls."""

    source_module: str
    target_module: str
    symbol: str | None = None
    kind: str = "import"
    start_line: int | None = None


class ParsedModule(BaseModel):
    name: str
    docstring: str | None = None
    classes: list[ParsedClass] = Field(default_factory=list)
    functions: list[ParsedFunction] = Field(default_factory=list)
    imports: list[ParsedImport] = Field(default_factory=list)
    comments: list[ParsedComment] = Field(default_factory=list)
    variables: list[ParsedVariable] = Field(default_factory=list)
    references: list[ParsedReference] = Field(default_factory=list)


class FileMetadata(BaseModel):
    path: str
    language: str
    file_size: int = 0
    line_count: int = 0
    encoding: str = "utf-8"
    content_hash: str = ""
    last_modified: datetime | None = None


class ParsedFile(BaseModel):
    """Top-level parse result for a single source file."""

    metadata: FileMetadata
    module: ParsedModule
    has_syntax_errors: bool = False
    error_message: str | None = None
