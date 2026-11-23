"""Minimal JSON adapter — records file metadata and top-level keys as variables."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from refactory.parser.adapters.base import LanguageAdapter
from refactory.parser.models import (
    FileMetadata,
    ParsedFile,
    ParsedModule,
    ParsedVariable,
)


class JsonLanguageAdapter(LanguageAdapter):
    @property
    def language(self) -> str:
        return "json"

    @property
    def extensions(self) -> frozenset[str]:
        return frozenset({".json"})

    def parse(self, path: Path, content: str, *, relative_path: str) -> ParsedFile:
        lines = content.splitlines()
        variables: list[ParsedVariable] = []
        has_errors = False
        error_message: str | None = None

        try:
            data = json.loads(content)
            if isinstance(data, dict):
                for idx, key in enumerate(list(data.keys())[:200], start=1):
                    variables.append(
                        ParsedVariable(
                            name=str(key),
                            start_line=1,
                            end_line=1,
                            is_constant=True,
                        )
                    )
                    if idx >= 200:
                        break
        except json.JSONDecodeError as exc:
            has_errors = True
            error_message = str(exc)

        return ParsedFile(
            metadata=FileMetadata(
                path=relative_path,
                language="json",
                file_size=len(content.encode("utf-8")),
                line_count=len(lines),
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                last_modified=datetime.now(timezone.utc),
            ),
            module=ParsedModule(
                name=Path(relative_path).stem,
                variables=variables,
            ),
            has_syntax_errors=has_errors,
            error_message=error_message,
        )
