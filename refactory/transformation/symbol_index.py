"""Repository-wide symbol index for multi-file refactoring.

Indexes definitions and references from Python sources using Tree-sitter
(with stdlib ``ast`` fallback) so rename / planner can resolve repository scope.
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from loguru import Logger


class SymbolType(str, Enum):
    FUNCTION = "function"
    CLASS = "class"
    VARIABLE = "variable"
    IMPORT = "import"
    EXPORT = "export"
    MODULE = "module"
    ALIAS = "alias"
    DECORATOR = "decorator"
    REFERENCE = "reference"
    CALL = "call"
    INHERITANCE = "inheritance"


@dataclass(frozen=True)
class SourceRange:
    start_line: int
    start_col: int
    end_line: int
    end_col: int


@dataclass
class SymbolOccurrence:
    """A definition or reference of a symbol in a file."""

    symbol_id: str
    name: str
    file_path: str
    range: SourceRange
    symbol_type: SymbolType
    is_definition: bool = False
    parent: str = ""
    detail: str = ""


@dataclass
class IndexedSymbolRecord:
    """Aggregated symbol with all known occurrences."""

    symbol_id: str
    name: str
    symbol_type: SymbolType
    definitions: list[SymbolOccurrence] = field(default_factory=list)
    references: list[SymbolOccurrence] = field(default_factory=list)

    @property
    def files(self) -> list[str]:
        paths = {o.file_path for o in self.definitions}
        paths.update(o.file_path for o in self.references)
        return sorted(paths)


class RepositorySymbolIndex:
    """In-memory repository symbol index for refactoring scope resolution."""

    def __init__(self, root: Path, *, logger: "Logger | None" = None) -> None:
        self.root = Path(root).resolve()
        self._logger = logger
        self._symbols: dict[str, IndexedSymbolRecord] = {}
        self._by_name: dict[str, list[str]] = {}
        self._built = False
        self._ts_parser = None
        self._ts_ready = False

    def build(self, *, max_files: int = 500) -> "RepositorySymbolIndex":
        """Scan Python files under the repository root and index symbols."""
        self._symbols.clear()
        self._by_name.clear()
        self._ensure_tree_sitter()
        count = 0
        for path in self._iter_python_files(max_files=max_files):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = str(path.relative_to(self.root)).replace("\\", "/")
            self._index_file(rel, text)
            count += 1
        self._built = True
        if self._logger is not None:
            self._logger.debug(
                "RepositorySymbolIndex built: {} files, {} symbols (tree-sitter={})",
                count,
                len(self._symbols),
                self._ts_ready,
            )
        return self

    def ensure_built(self) -> "RepositorySymbolIndex":
        if not self._built:
            self.build()
        return self

    def find_by_name(self, name: str) -> list[IndexedSymbolRecord]:
        self.ensure_built()
        ids = self._by_name.get(name, [])
        return [self._symbols[i] for i in ids if i in self._symbols]

    def files_referencing(
        self,
        name: str,
        *,
        prefer_definition_file: str = "",
        symbol_types: Iterable[SymbolType] | None = None,
    ) -> list[str]:
        """Return relative file paths that define or reference ``name``."""
        records = self.find_by_name(name)
        # Always keep reference aggregators so call/import sites are not dropped
        # when filtering to FUNCTION/CLASS/VARIABLE definition types.
        ref_records = [r for r in records if r.symbol_type == SymbolType.REFERENCE]
        if symbol_types is not None:
            allowed = set(symbol_types) | {SymbolType.REFERENCE, SymbolType.IMPORT, SymbolType.CALL}
            records = [r for r in records if r.symbol_type in allowed]
            if not records:
                records = ref_records
        if prefer_definition_file:
            preferred = prefer_definition_file.replace("\\", "/")
            narrowed = [
                r
                for r in records
                if any(d.file_path == preferred for d in r.definitions)
            ]
            if narrowed:
                # Keep reference-only records too (imports/calls in other files).
                records = narrowed + [
                    r for r in ref_records if r not in narrowed
                ]
        files: set[str] = set()
        for record in records:
            files.update(record.files)
        if prefer_definition_file:
            files.add(prefer_definition_file.replace("\\", "/"))
        return sorted(files)

    def affected_symbols(self, name: str) -> list[str]:
        records = self.find_by_name(name)
        out: list[str] = []
        for r in records:
            label = f"{r.symbol_type.value}:{r.name}"
            if label not in out:
                out.append(label)
        return out

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_tree_sitter(self) -> None:
        if self._ts_ready or self._ts_parser is not None:
            return
        try:
            import tree_sitter_python as tspython
            from tree_sitter import Language, Parser

            self._ts_parser = Parser(Language(tspython.language()))
            self._ts_ready = True
        except Exception:  # noqa: BLE001
            self._ts_parser = None
            self._ts_ready = False

    def _iter_python_files(self, *, max_files: int) -> list[Path]:
        skip = {"__pycache__", ".venv", "venv", ".git", ".refactory", "node_modules"}
        files: list[Path] = []
        for path in self.root.rglob("*.py"):
            try:
                parts = path.relative_to(self.root).parts
            except ValueError:
                continue
            if any(p in skip for p in parts):
                continue
            files.append(path)
            if len(files) >= max_files:
                break
        return files

    def _index_file(self, rel: str, source: str) -> None:
        if self._ts_ready and self._ts_parser is not None:
            try:
                self._index_file_tree_sitter(rel, source)
                return
            except Exception:  # noqa: BLE001
                if self._logger is not None:
                    self._logger.debug("Tree-sitter index failed for {}; using AST", rel)
        self._index_file_ast(rel, source)

    def _index_file_tree_sitter(self, rel: str, source: str) -> None:
        assert self._ts_parser is not None
        source_bytes = source.encode("utf-8")
        tree = self._ts_parser.parse(source_bytes)
        root = tree.root_node

        def text(node) -> str:
            return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

        def range_of(node) -> SourceRange:
            return SourceRange(
                start_line=node.start_point[0] + 1,
                start_col=node.start_point[1],
                end_line=node.end_point[0] + 1,
                end_col=node.end_point[1],
            )

        def child_by_type(node, typ: str):
            for c in node.children:
                if c.type == typ:
                    return c
            return None

        def walk(node, *, class_name: str = "") -> None:
            typ = node.type
            if typ in {"function_definition", "async_function_definition"}:
                name_node = child_by_type(node, "identifier")
                if name_node is not None:
                    name = text(name_node)
                    self._add_occurrence(
                        name,
                        SymbolType.FUNCTION,
                        rel,
                        range_of(name_node),
                        definition=True,
                        parent=class_name,
                    )
                    # EXPORT: top-level defs are exportable
                    if not class_name:
                        self._add_occurrence(
                            name,
                            SymbolType.EXPORT,
                            rel,
                            range_of(name_node),
                            definition=True,
                            detail="export",
                        )
                for dec in node.children:
                    if dec.type == "decorator":
                        ident = self._ts_first_identifier(dec, text)
                        if ident:
                            self._add_occurrence(
                                ident[0],
                                SymbolType.DECORATOR,
                                rel,
                                ident[1],
                                definition=False,
                                detail="decorator",
                            )
                for child in node.children:
                    walk(child, class_name=class_name)
                return

            if typ == "class_definition":
                name_node = child_by_type(node, "identifier")
                cls_name = text(name_node) if name_node is not None else ""
                if cls_name:
                    self._add_occurrence(
                        cls_name,
                        SymbolType.CLASS,
                        rel,
                        range_of(name_node),
                        definition=True,
                    )
                    self._add_occurrence(
                        cls_name,
                        SymbolType.EXPORT,
                        rel,
                        range_of(name_node),
                        definition=True,
                        detail="export",
                    )
                # inheritance argument list
                arg_list = child_by_type(node, "argument_list")
                if arg_list is not None:
                    for arg in arg_list.children:
                        ident = self._ts_first_identifier(arg, text)
                        if ident:
                            self._add_occurrence(
                                ident[0],
                                SymbolType.INHERITANCE,
                                rel,
                                ident[1],
                                definition=False,
                                detail="base",
                            )
                for child in node.children:
                    walk(child, class_name=cls_name or class_name)
                return

            if typ == "assignment":
                left = node.child_by_field_name("left")
                if left is not None and left.type == "identifier":
                    self._add_occurrence(
                        text(left),
                        SymbolType.VARIABLE,
                        rel,
                        range_of(left),
                        definition=True,
                    )
            elif typ == "augmented_assignment":
                left = node.child_by_field_name("left")
                if left is not None and left.type == "identifier":
                    self._add_occurrence(
                        text(left),
                        SymbolType.VARIABLE,
                        rel,
                        range_of(left),
                        definition=True,
                    )
            elif typ == "call":
                func = node.child_by_field_name("function")
                if func is not None:
                    ident = self._ts_first_identifier(func, text)
                    if ident:
                        self._add_occurrence(
                            ident[0],
                            SymbolType.CALL,
                            rel,
                            ident[1],
                            definition=False,
                        )
            elif typ in {"import_statement", "import_from_statement"}:
                for child in node.children:
                    if child.type == "dotted_name":
                        name = text(child).split(".")[-1]
                        self._add_occurrence(
                            name,
                            SymbolType.IMPORT,
                            rel,
                            range_of(child),
                            definition=False,
                        )
                    elif child.type == "identifier":
                        # `from mod import name` exposes imported identifiers directly.
                        self._add_occurrence(
                            text(child),
                            SymbolType.IMPORT,
                            rel,
                            range_of(child),
                            definition=False,
                        )
                    elif child.type == "aliased_import":
                        name_node = child_by_type(child, "dotted_name") or child_by_type(
                            child, "identifier"
                        )
                        as_node = None
                        ids = [c for c in child.children if c.type == "identifier"]
                        if len(ids) >= 2:
                            as_node = ids[-1]
                        if name_node is not None:
                            imported = text(name_node).split(".")[-1]
                            self._add_occurrence(
                                imported,
                                SymbolType.IMPORT,
                                rel,
                                range_of(name_node),
                                definition=False,
                            )
                        if as_node is not None:
                            self._add_occurrence(
                                text(as_node),
                                SymbolType.ALIAS,
                                rel,
                                range_of(as_node),
                                definition=True,
                                detail=text(name_node) if name_node else "",
                            )
            elif typ == "identifier" and node.parent is not None:
                # Generic load-style identifier references (skip definition sites).
                parent_type = node.parent.type
                if parent_type not in {
                    "function_definition",
                    "async_function_definition",
                    "class_definition",
                    "parameters",
                    "default_parameter",
                    "typed_parameter",
                    "typed_default_parameter",
                }:
                    # Avoid double-counting field names already handled.
                    field = None
                    try:
                        field = node.parent.child_by_field_name("name")
                    except Exception:  # noqa: BLE001
                        field = None
                    if field is not node:
                        self._add_occurrence(
                            text(node),
                            SymbolType.REFERENCE,
                            rel,
                            range_of(node),
                            definition=False,
                        )

            for child in node.children:
                walk(child, class_name=class_name)

        walk(root)
        # Module symbol for the file itself
        mod = Path(rel).with_suffix("").as_posix().replace("/", ".")
        self._add_occurrence(
            mod,
            SymbolType.MODULE,
            rel,
            SourceRange(1, 0, 1, 0),
            definition=True,
            detail="module",
        )

    @staticmethod
    def _ts_first_identifier(node, text_fn) -> tuple[str, SourceRange] | None:
        if node.type == "identifier":
            return text_fn(node), SourceRange(
                start_line=node.start_point[0] + 1,
                start_col=node.start_point[1],
                end_line=node.end_point[0] + 1,
                end_col=node.end_point[1],
            )
        if node.type == "attribute":
            # use attribute name (rightmost identifier)
            for child in reversed(node.children):
                found = RepositorySymbolIndex._ts_first_identifier(child, text_fn)
                if found:
                    return found
        for child in node.children:
            found = RepositorySymbolIndex._ts_first_identifier(child, text_fn)
            if found:
                return found
        return None

    def _index_file_ast(self, rel: str, source: str) -> None:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._add_definition(node.name, SymbolType.FUNCTION, rel, node)
                self._add_definition(node.name, SymbolType.EXPORT, rel, node, detail="export")
            elif isinstance(node, ast.ClassDef):
                self._add_definition(node.name, SymbolType.CLASS, rel, node)
                self._add_definition(node.name, SymbolType.EXPORT, rel, node, detail="export")
                for base in node.bases:
                    base_name = self._name_of(base)
                    if base_name:
                        self._add_reference(
                            base_name, SymbolType.INHERITANCE, rel, base, detail="base"
                        )
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self._add_definition(
                            item.name, SymbolType.FUNCTION, rel, item, parent=node.name
                        )
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    node.targets
                    if isinstance(node, ast.Assign)
                    else ([node.target] if node.target is not None else [])
                )
                for target in targets:
                    if isinstance(target, ast.Name):
                        self._add_definition(
                            target.id, SymbolType.VARIABLE, rel, target
                        )

        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                self._add_reference(node.id, SymbolType.REFERENCE, rel, node)
            elif isinstance(node, ast.Call):
                called = self._name_of(node.func)
                if called:
                    self._add_reference(called, SymbolType.CALL, rel, node.func)
            elif isinstance(node, ast.Attribute):
                self._add_reference(node.attr, SymbolType.REFERENCE, rel, node)
            elif isinstance(node, ast.alias):
                imported = node.name.split(".")[-1]
                self._add_reference(imported, SymbolType.IMPORT, rel, node)
                if node.asname:
                    self._add_definition(
                        node.asname, SymbolType.ALIAS, rel, node, detail=node.name
                    )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for dec in node.decorator_list:
                    dec_name = self._name_of(dec)
                    if dec_name:
                        self._add_reference(
                            dec_name, SymbolType.DECORATOR, rel, dec, detail="decorator"
                        )

        mod = Path(rel).with_suffix("").as_posix().replace("/", ".")
        self._add_occurrence(
            mod,
            SymbolType.MODULE,
            rel,
            SourceRange(1, 0, 1, 0),
            definition=True,
            detail="module",
        )

    def _add_occurrence(
        self,
        name: str,
        symbol_type: SymbolType,
        file_path: str,
        source_range: SourceRange,
        *,
        definition: bool,
        parent: str = "",
        detail: str = "",
    ) -> None:
        if not name:
            return
        if definition:
            sid = self._symbol_id(name, symbol_type, file_path, definition=True)
            occ = SymbolOccurrence(
                symbol_id=sid,
                name=name,
                file_path=file_path,
                range=source_range,
                symbol_type=symbol_type,
                is_definition=True,
                parent=parent,
                detail=detail,
            )
            record = self._ensure_record(sid, name, symbol_type)
            record.definitions.append(occ)
            self._by_name.setdefault(name, [])
            if sid not in self._by_name[name]:
                self._by_name[name].append(sid)
            # Absorb references that were indexed before this definition existed.
            self._merge_reference_placeholders(name, sid)
            return

        ids = list(self._by_name.get(name, []))
        # Prefer attaching to real definitions (not placeholder REFERENCE records).
        def_ids = [
            i
            for i in ids
            if self._symbols[i].symbol_type != SymbolType.REFERENCE
            or self._symbols[i].definitions
        ]
        if def_ids:
            ids = def_ids
        if not ids:
            sid = self._symbol_id(name, SymbolType.REFERENCE, file_path, definition=False)
            self._ensure_record(sid, name, SymbolType.REFERENCE)
            self._by_name.setdefault(name, []).append(sid)
            ids = [sid]
        for sid in ids:
            record = self._symbols[sid]
            occ = SymbolOccurrence(
                symbol_id=sid,
                name=name,
                file_path=file_path,
                range=source_range,
                symbol_type=symbol_type,
                is_definition=False,
                detail=detail,
            )
            record.references.append(occ)

    def _add_definition(
        self,
        name: str,
        symbol_type: SymbolType,
        file_path: str,
        node: ast.AST,
        *,
        parent: str = "",
        detail: str = "",
    ) -> None:
        self._add_occurrence(
            name,
            symbol_type,
            file_path,
            self._range_of(node),
            definition=True,
            parent=parent,
            detail=detail,
        )

    def _add_reference(
        self,
        name: str,
        symbol_type: SymbolType,
        file_path: str,
        node: ast.AST,
        *,
        detail: str = "",
    ) -> None:
        self._add_occurrence(
            name,
            symbol_type,
            file_path,
            self._range_of(node),
            definition=False,
            detail=detail,
        )

    def _ensure_record(
        self, symbol_id: str, name: str, symbol_type: SymbolType
    ) -> IndexedSymbolRecord:
        if symbol_id not in self._symbols:
            self._symbols[symbol_id] = IndexedSymbolRecord(
                symbol_id=symbol_id, name=name, symbol_type=symbol_type
            )
        return self._symbols[symbol_id]

    def _merge_reference_placeholders(self, name: str, target_sid: str) -> None:
        """Move refs from name-only placeholders onto a newly created definition."""
        target = self._symbols.get(target_sid)
        if target is None:
            return
        placeholders = [
            sid
            for sid in list(self._by_name.get(name, []))
            if sid != target_sid
            and self._symbols[sid].symbol_type == SymbolType.REFERENCE
            and not self._symbols[sid].definitions
        ]
        for sid in placeholders:
            target.references.extend(self._symbols[sid].references)
            self._symbols[sid].references.clear()
            self._by_name[name] = [i for i in self._by_name[name] if i != sid]
            self._symbols.pop(sid, None)

    @staticmethod
    def _symbol_id(
        name: str, symbol_type: SymbolType, file_path: str, *, definition: bool
    ) -> str:
        raw = f"{symbol_type.value}:{name}:{file_path if definition else '*'}"
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
        return f"SYM-{digest}"

    @staticmethod
    def _range_of(node: ast.AST) -> SourceRange:
        return SourceRange(
            start_line=int(getattr(node, "lineno", 1) or 1),
            start_col=int(getattr(node, "col_offset", 0) or 0),
            end_line=int(getattr(node, "end_lineno", getattr(node, "lineno", 1)) or 1),
            end_col=int(getattr(node, "end_col_offset", 0) or 0),
        )

    @staticmethod
    def _name_of(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Call):
            return RepositorySymbolIndex._name_of(node.func)
        if isinstance(node, ast.alias):
            return node.asname or node.name.split(".")[-1]
        return ""
