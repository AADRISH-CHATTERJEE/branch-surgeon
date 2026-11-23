"""Lightweight JavaScript / TypeScript adapter (regex-based, no Tree-sitter).

Indexes imports and top-level declarations without crashing on mixed-language
repos. Does not attempt full AST fidelity — unsupported constructs are skipped.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from refactory.parser.adapters.base import LanguageAdapter
from refactory.parser.models import (
    FileMetadata,
    ImportKind,
    ParsedFile,
    ParsedFunction,
    ParsedImport,
    ParsedModule,
)

_IMPORT_FROM = re.compile(
    r"""^\s*import\s+(?:type\s+)?(?:[\w*{}\s,]+)\s+from\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_IMPORT_SIDE = re.compile(
    r"""^\s*import\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_REQUIRE = re.compile(
    r"""require\(\s*['"]([^'"]+)['"]\s*\)""",
)
_EXPORT_FN = re.compile(
    r"""^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+(\w+)""",
    re.MULTILINE,
)
_EXPORT_CLASS = re.compile(
    r"""^\s*(?:export\s+(?:default\s+)?)?class\s+(\w+)""",
    re.MULTILINE,
)
_EXPORT_CONST = re.compile(
    r"""^\s*export\s+(?:const|let|var)\s+(\w+)""",
    re.MULTILINE,
)


class EcmaScriptAdapter(LanguageAdapter):
    """Shared JS/TS surface — language id depends on file extension."""

    def __init__(self, *, language: str, extensions: frozenset[str]) -> None:
        self._language = language
        self._extensions = extensions

    @property
    def language(self) -> str:
        return self._language

    @property
    def extensions(self) -> frozenset[str]:
        return self._extensions

    def parse(self, path: Path, content: str, *, relative_path: str) -> ParsedFile:
        lines = content.splitlines()
        imports = self._extract_imports(content)
        functions = self._extract_functions(content)
        module_name = Path(relative_path).stem

        return ParsedFile(
            metadata=FileMetadata(
                path=relative_path,
                language=self._language,
                file_size=len(content.encode("utf-8")),
                line_count=len(lines),
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                last_modified=datetime.now(timezone.utc),
            ),
            module=ParsedModule(
                name=module_name,
                functions=functions,
                imports=imports,
            ),
            has_syntax_errors=False,
        )

    def _extract_imports(self, content: str) -> list[ParsedImport]:
        found: list[ParsedImport] = []
        seen: set[tuple[str, int]] = set()

        def add(module: str, line: int, *, is_from: bool, raw: str) -> None:
            key = (module, line)
            if key in seen:
                return
            seen.add(key)
            kind = (
                ImportKind.LOCAL
                if module.startswith((".", "/"))
                else ImportKind.THIRD_PARTY
            )
            found.append(
                ParsedImport(
                    module=module,
                    kind=kind,
                    is_from_import=is_from,
                    start_line=line,
                    end_line=line,
                    raw=raw[:200],
                )
            )

        for pattern, is_from in (
            (_IMPORT_FROM, True),
            (_IMPORT_SIDE, False),
        ):
            for match in pattern.finditer(content):
                line = content[: match.start()].count("\n") + 1
                add(match.group(1), line, is_from=is_from, raw=match.group(0).strip())

        for match in _REQUIRE.finditer(content):
            line = content[: match.start()].count("\n") + 1
            add(match.group(1), line, is_from=False, raw=match.group(0).strip())

        return found

    def _extract_functions(self, content: str) -> list[ParsedFunction]:
        functions: list[ParsedFunction] = []
        for pattern in (_EXPORT_FN, _EXPORT_CLASS, _EXPORT_CONST):
            for match in pattern.finditer(content):
                line = content[: match.start()].count("\n") + 1
                functions.append(
                    ParsedFunction(
                        name=match.group(1),
                        start_line=line,
                        end_line=line,
                    )
                )
        return functions


def javascript_adapter() -> EcmaScriptAdapter:
    return EcmaScriptAdapter(
        language="javascript",
        extensions=frozenset({".js", ".jsx", ".mjs", ".cjs"}),
    )


def typescript_adapter() -> EcmaScriptAdapter:
    return EcmaScriptAdapter(
        language="typescript",
        extensions=frozenset({".ts", ".tsx", ".mts", ".cts"}),
    )
