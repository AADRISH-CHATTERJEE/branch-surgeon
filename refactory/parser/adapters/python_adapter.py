"""Tree-sitter Python language adapter."""

from __future__ import annotations

import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

from refactory.parser.adapters.base import LanguageAdapter
from refactory.parser.models import (
    CommentTag,
    FileMetadata,
    ImportKind,
    ParsedClass,
    ParsedComment,
    ParsedFile,
    ParsedFunction,
    ParsedImport,
    ParsedModule,
    ParsedParameter,
    ParsedReference,
    ParsedVariable,
)

_COMMENT_TAG_RE = re.compile(r"\b(TODO|FIXME|HACK|NOTE)\b", re.IGNORECASE)
_STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {
    "__future__",
    "typing",
    "collections",
    "pathlib",
    "os",
    "sys",
    "re",
    "json",
    "asyncio",
    "functools",
    "itertools",
    "dataclasses",
    "enum",
    "abc",
    "logging",
    "unittest",
    "hashlib",
    "datetime",
}


class PythonLanguageAdapter(LanguageAdapter):
    @property
    def language(self) -> str:
        return "python"

    @property
    def extensions(self) -> frozenset[str]:
        return frozenset({".py", ".pyi"})

    def __init__(self) -> None:
        self._parser = Parser(Language(tspython.language()))

    def parse(self, path: Path, content: str, *, relative_path: str) -> ParsedFile:
        # Tree-sitter offsets are UTF-8 byte indexes — keep bytes for all node text.
        self._source = content.encode("utf-8")
        tree = self._parser.parse(self._source)
        root = tree.root_node
        has_errors = root.has_error

        module_name = path.stem
        module_doc = self._module_docstring(root, content)

        imports: list[ParsedImport] = []
        classes: list[ParsedClass] = []
        functions: list[ParsedFunction] = []
        comments: list[ParsedComment] = []
        variables: list[ParsedVariable] = []
        references: list[ParsedReference] = []

        self._collect_comments(root, content, comments)

        for child in root.children:
            if child.type in {"import_statement", "import_from_statement"}:
                parsed_import = self._parse_import(child, content)
                imports.append(parsed_import)
                references.extend(self._references_from_import(module_name, parsed_import))
            elif child.type == "class_definition":
                classes.append(self._parse_class(child, content))
            elif child.type == "function_definition":
                functions.append(self._parse_function(child, content, parent_class=None))
            elif child.type == "decorated_definition":
                target = self._decorated_target(child)
                decorators = self._decorators(child, content)
                if target is None:
                    continue
                if target.type == "class_definition":
                    parsed = self._parse_class(target, content)
                    parsed.decorators = decorators
                    classes.append(parsed)
                elif target.type == "function_definition":
                    parsed = self._parse_function(target, content, parent_class=None)
                    parsed.decorators = decorators
                    functions.append(parsed)
            elif child.type == "expression_statement":
                variables.extend(self._parse_assignments(child, content))
            elif child.type == "type_alias_statement":
                variables.extend(self._parse_assignments(child, content))

        references.extend(self._collect_call_references(root, module_name, content))

        metadata = self._metadata(path, relative_path, content)
        module = ParsedModule(
            name=module_name,
            docstring=module_doc,
            classes=classes,
            functions=functions,
            imports=imports,
            comments=comments,
            variables=variables,
            references=references,
        )
        return ParsedFile(
            metadata=metadata,
            module=module,
            has_syntax_errors=has_errors,
            error_message="Tree-sitter reported ERROR nodes in the syntax tree" if has_errors else None,
        )

    # ------------------------------------------------------------------
    # Node helpers
    # ------------------------------------------------------------------

    def _text(self, node: Node, _content: str | None = None) -> str:
        """Decode node text using UTF-8 byte offsets from the parsed source."""
        return self._source[node.start_byte : node.end_byte].decode("utf-8")

    def _child_by_type(self, node: Node, type_name: str) -> Node | None:
        for child in node.children:
            if child.type == type_name:
                return child
        return None

    def _children_by_type(self, node: Node, type_name: str) -> list[Node]:
        return [child for child in node.children if child.type == type_name]

    def _identifier(self, node: Node, content: str) -> str | None:
        ident = self._child_by_type(node, "identifier")
        return self._text(ident, content) if ident else None

    def _decorated_target(self, node: Node) -> Node | None:
        for child in node.children:
            if child.type in {"class_definition", "function_definition"}:
                return child
        return None

    def _decorators(self, decorated: Node, content: str) -> list[str]:
        result: list[str] = []
        for child in decorated.children:
            if child.type == "decorator":
                result.append(self._text(child, content).lstrip("@").strip())
        return result

    def _docstring(self, body: Node | None, content: str) -> str | None:
        if body is None:
            return None
        for stmt in body.children:
            if stmt.type != "expression_statement":
                continue
            for expr in stmt.children:
                if expr.type == "string":
                    return self._normalize_string(self._text(expr, content))
            break
        return None

    def _module_docstring(self, root: Node, content: str) -> str | None:
        for child in root.children:
            if child.type == "expression_statement":
                for expr in child.children:
                    if expr.type == "string":
                        return self._normalize_string(self._text(expr, content))
                return None
            if child.type not in {"comment", "newline"}:
                return None
        return None

    @staticmethod
    def _normalize_string(raw: str) -> str:
        text = raw.strip()
        if text.startswith(("'''", '"""')):
            text = text[3:]
        elif text.startswith(("'", '"')):
            text = text[1:]
        if text.endswith(("'''", '"""')):
            text = text[:-3]
        elif text.endswith(("'", '"')):
            text = text[:-1]
        return text.strip()

    # ------------------------------------------------------------------
    # Imports
    # ------------------------------------------------------------------

    def _parse_import(self, node: Node, content: str) -> ParsedImport:
        raw = self._text(node, content).strip()
        start = node.start_point[0] + 1
        end = node.end_point[0] + 1

        if node.type == "import_from_statement":
            module_node = None
            for child in node.children:
                if child.type in {"dotted_name", "relative_import", "identifier"}:
                    module_node = child
                    break
            module = self._text(module_node, content) if module_node else ""
            names = self._import_names(node, content)
            alias = names[0].split(" as ")[-1].strip() if len(names) == 1 and " as " in names[0] else None
            clean_names = [n.split(" as ")[0].strip() for n in names]
            kind = self._classify_import(module)
            return ParsedImport(
                module=module.lstrip("."),
                names=clean_names,
                alias=alias,
                kind=kind,
                is_from_import=True,
                start_line=start,
                end_line=end,
                raw=raw,
            )

        # import x / import x as y / import a, b
        names = self._import_names(node, content)
        primary = names[0] if names else ""
        module = primary.split(" as ")[0].strip()
        alias = primary.split(" as ")[1].strip() if " as " in primary else None
        return ParsedImport(
            module=module,
            names=[module],
            alias=alias,
            kind=self._classify_import(module),
            is_from_import=False,
            start_line=start,
            end_line=end,
            raw=raw,
        )

    def _import_names(self, node: Node, content: str) -> list[str]:
        names: list[str] = []
        for child in node.children:
            if child.type == "dotted_name":
                # for plain import statements the dotted_name is the module
                if node.type == "import_statement":
                    names.append(self._text(child, content))
            elif child.type == "aliased_import":
                names.append(self._text(child, content))
            elif child.type == "identifier" and node.type == "import_from_statement":
                # skip module identifier already handled
                continue
            elif child.type == "wildcard_import":
                names.append("*")
        # from-import: collect imported names after import keyword
        if node.type == "import_from_statement":
            names = []
            seen_import_kw = False
            for child in node.children:
                if child.type == "import":
                    seen_import_kw = True
                    continue
                if not seen_import_kw:
                    continue
                if child.type in {"dotted_name", "identifier"}:
                    names.append(self._text(child, content))
                elif child.type == "aliased_import":
                    names.append(self._text(child, content))
                elif child.type == "wildcard_import":
                    names.append("*")
        return names

    def _classify_import(self, module: str) -> ImportKind:
        root = module.lstrip(".").split(".", 1)[0]
        if module.startswith("."):
            return ImportKind.LOCAL
        if root in _STDLIB:
            return ImportKind.STDLIB
        if root:
            return ImportKind.THIRD_PARTY
        return ImportKind.UNKNOWN

    def _references_from_import(self, source_module: str, parsed: ParsedImport) -> list[ParsedReference]:
        refs: list[ParsedReference] = []
        if parsed.is_from_import:
            if parsed.names:
                for name in parsed.names:
                    refs.append(
                        ParsedReference(
                            source_module=source_module,
                            target_module=parsed.module,
                            symbol=name,
                            kind="import",
                            start_line=parsed.start_line,
                        )
                    )
            else:
                refs.append(
                    ParsedReference(
                        source_module=source_module,
                        target_module=parsed.module,
                        symbol=None,
                        kind="import",
                        start_line=parsed.start_line,
                    )
                )
        else:
            refs.append(
                ParsedReference(
                    source_module=source_module,
                    target_module=parsed.module,
                    symbol=parsed.alias or parsed.module,
                    kind="import",
                    start_line=parsed.start_line,
                )
            )
        return refs

    def _collect_call_references(
        self, root: Node, source_module: str, content: str
    ) -> list[ParsedReference]:
        """Extract function/method call names as kind=call references (deterministic)."""
        refs: list[ParsedReference] = []
        seen: set[tuple[str, int]] = set()

        def walk(node: Node) -> None:
            if node.type == "call":
                callee = self._call_callee_name(node, content)
                if callee:
                    line = node.start_point[0] + 1
                    key = (callee, line)
                    if key not in seen:
                        seen.add(key)
                        refs.append(
                            ParsedReference(
                                source_module=source_module,
                                target_module=source_module,
                                symbol=callee,
                                kind="call",
                                start_line=line,
                            )
                        )
            for child in node.children:
                walk(child)

        walk(root)
        return sorted(refs, key=lambda r: (r.start_line or 0, r.symbol or ""))

    def _call_callee_name(self, call_node: Node, content: str) -> str | None:
        """Return simple callee identifier for a call node (last attribute segment)."""
        if not call_node.children:
            return None
        func = call_node.children[0]
        if func.type == "identifier":
            return self._text(func, content)
        if func.type == "attribute":
            idents = self._children_by_type(func, "identifier")
            if idents:
                return self._text(idents[-1], content)
            text = self._text(func, content)
            return text.rsplit(".", 1)[-1] if text else None
        return None

    # ------------------------------------------------------------------
    # Classes / functions
    # ------------------------------------------------------------------

    def _parse_class(self, node: Node, content: str) -> ParsedClass:
        name = self._identifier(node, content) or "AnonymousClass"
        bases = self._base_classes(node, content)
        body = self._child_by_type(node, "block")
        docstring = self._docstring(body, content)
        methods: list[ParsedFunction] = []
        properties: list[str] = []

        if body:
            for child in body.children:
                target = child
                decorators: list[str] = []
                if child.type == "decorated_definition":
                    decorators = self._decorators(child, content)
                    target = self._decorated_target(child) or child
                if target.type == "function_definition":
                    method = self._parse_function(
                        target,
                        content,
                        parent_class=name,
                        parent_function=None,
                    )
                    method.decorators = decorators or method.decorators
                    method.is_method = True
                    methods.append(method)
                    if any(d.split("(")[0] in {"property", "cached_property"} for d in method.decorators):
                        properties.append(method.name)

        return ParsedClass(
            name=name,
            bases=bases,
            methods=methods,
            properties=properties,
            decorators=[],
            docstring=docstring,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

    def _base_classes(self, node: Node, content: str) -> list[str]:
        arg_list = self._child_by_type(node, "argument_list")
        if arg_list is None:
            return []
        bases: list[str] = []
        for child in arg_list.children:
            if child.type in {"identifier", "attribute", "subscript"}:
                bases.append(self._text(child, content))
        return bases

    def _parse_function(
        self,
        node: Node,
        content: str,
        *,
        parent_class: str | None,
        parent_function: str | None = None,
    ) -> ParsedFunction:
        name = self._identifier(node, content) or "anonymous"
        is_async = any(child.type == "async" for child in node.children)
        params = self._parameters(node, content)
        return_type = self._return_type(node, content)
        body = self._child_by_type(node, "block")
        docstring = self._docstring(body, content)
        is_generator = self._contains_yield(body) if body else False
        nested = (
            self._nested_functions(body, content, parent_function_name=name)
            if body
            else []
        )

        return ParsedFunction(
            name=name,
            parameters=params,
            return_type=return_type,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            docstring=docstring,
            decorators=[],
            is_async=is_async,
            is_generator=is_generator,
            is_method=parent_class is not None and parent_function is None,
            parent_class=parent_class,
            parent_function=parent_function,
            nested_functions=nested,
        )

    def _parameters(self, node: Node, content: str) -> list[ParsedParameter]:
        params_node = self._child_by_type(node, "parameters")
        if params_node is None:
            return []
        result: list[ParsedParameter] = []
        for child in params_node.children:
            if child.type == "identifier":
                result.append(ParsedParameter(name=self._text(child, content)))
            elif child.type == "typed_parameter":
                result.append(self._typed_parameter(child, content))
            elif child.type == "default_parameter":
                result.append(self._default_parameter(child, content, typed=False))
            elif child.type == "typed_default_parameter":
                result.append(self._default_parameter(child, content, typed=True))
            elif child.type in {"list_splat_pattern", "dictionary_splat_pattern"}:
                result.append(ParsedParameter(name=self._text(child, content)))
        return result

    def _typed_parameter(self, node: Node, content: str) -> ParsedParameter:
        name = "param"
        type_hint = None
        for child in node.children:
            if child.type == "identifier":
                name = self._text(child, content)
            elif child.type == "type":
                type_hint = self._text(child, content)
        return ParsedParameter(name=name, type_hint=type_hint)

    def _default_parameter(self, node: Node, content: str, *, typed: bool) -> ParsedParameter:
        name = "param"
        type_hint = None
        default = None
        children = [c for c in node.children if c.type not in {",", "=", ":"}]
        # Patterns vary; take first identifier as name, last non-type as default.
        identifiers = [c for c in node.children if c.type == "identifier"]
        if identifiers:
            name = self._text(identifiers[0], content)
        type_node = self._child_by_type(node, "type")
        if type_node:
            type_hint = self._text(type_node, content)
        # default is typically the last meaningful child
        for child in reversed(node.children):
            if child.type in {"identifier", "type", "=", ":", ",", "comment"}:
                continue
            default = self._text(child, content)
            break
        return ParsedParameter(name=name, type_hint=type_hint if typed or type_hint else None, default=default)

    def _return_type(self, node: Node, content: str) -> str | None:
        # function_definition: ... -> type
        type_node = None
        seen_arrow = False
        for child in node.children:
            if child.type == "->":
                seen_arrow = True
                continue
            if seen_arrow and child.type == "type":
                type_node = child
                break
        if type_node is None:
            # some grammars attach return type differently
            for child in node.children:
                if child.type == "type" and child.start_byte > (self._child_by_type(node, "parameters") or node).end_byte:
                    type_node = child
                    break
        return self._text(type_node, content) if type_node else None

    def _contains_yield(self, body: Node) -> bool:
        stack = list(body.children)
        while stack:
            node = stack.pop()
            if node.type in {"yield", "yield_expression"}:
                return True
            stack.extend(node.children)
        return False

    def _nested_functions(
        self,
        body: Node,
        content: str,
        *,
        parent_function_name: str,
    ) -> list[ParsedFunction]:
        """Find nested functions at any AST depth under ``body``.

        Walks statements such as ``if`` / ``for`` / ``with`` / ``try``. When a
        nested ``function_definition`` is found it is parsed (which recursively
        discovers deeper nesting) and its subtree is not re-walked here.
        """
        nested: list[ParsedFunction] = []
        stack: list[Node] = list(body.children)

        while stack:
            node = stack.pop(0)
            decorators: list[str] = []
            target: Node | None = None

            if node.type == "function_definition":
                target = node
            elif node.type == "decorated_definition":
                candidate = self._decorated_target(node)
                if candidate is not None and candidate.type == "function_definition":
                    decorators = self._decorators(node, content)
                    target = candidate

            if target is not None:
                parsed = self._parse_function(
                    target,
                    content,
                    parent_class=None,
                    parent_function=parent_function_name,
                )
                if decorators:
                    parsed.decorators = decorators
                nested.append(parsed)
                # Deeper nesting is handled inside _parse_function — do not
                # descend into this function's body from this walk.
                continue

            # Skip nested class bodies (their methods are not nested functions).
            if node.type == "class_definition":
                continue

            stack.extend(node.children)

        return nested

    # ------------------------------------------------------------------
    # Variables / comments / metadata
    # ------------------------------------------------------------------

    def _parse_assignments(self, node: Node, content: str) -> list[ParsedVariable]:
        results: list[ParsedVariable] = []
        for child in node.children:
            if child.type in {"assignment", "augmented_assignment"}:
                name_node = None
                type_hint = None
                value_preview = None
                for part in child.children:
                    if part.type in {"identifier", "pattern_list", "tuple_pattern"} and name_node is None:
                        name_node = part
                    elif part.type == "type":
                        type_hint = self._text(part, content)
                    elif part.type not in {"=", ":"}:
                        value_preview = self._text(part, content)[:80]
                if name_node is None:
                    continue
                name = self._text(name_node, content)
                if "," in name:
                    # multi-assign — record each simple name
                    for piece in [p.strip() for p in name.split(",") if p.strip()]:
                        results.append(
                            ParsedVariable(
                                name=piece,
                                value_preview=value_preview,
                                type_hint=type_hint,
                                is_constant=piece.isupper(),
                                start_line=child.start_point[0] + 1,
                                end_line=child.end_point[0] + 1,
                            )
                        )
                else:
                    results.append(
                        ParsedVariable(
                            name=name,
                            value_preview=value_preview,
                            type_hint=type_hint,
                            is_constant=name.isupper(),
                            start_line=child.start_point[0] + 1,
                            end_line=child.end_point[0] + 1,
                        )
                    )
        return results

    def _collect_comments(self, root: Node, content: str, out: list[ParsedComment]) -> None:
        stack = [root]
        while stack:
            node = stack.pop()
            if node.type == "comment":
                text = self._text(node, content).strip()
                tag = CommentTag.NONE
                match = _COMMENT_TAG_RE.search(text)
                if match:
                    tag = CommentTag[match.group(1).upper()]
                out.append(
                    ParsedComment(
                        text=text,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        tag=tag,
                        is_block=False,
                    )
                )
            stack.extend(node.children)

    def _metadata(self, path: Path, relative_path: str, content: str) -> FileMetadata:
        stat = path.stat() if path.exists() else None
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        mtime = (
            datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc) if stat is not None else None
        )
        return FileMetadata(
            path=relative_path.replace("\\", "/"),
            language=self.language,
            file_size=stat.st_size if stat is not None else len(content.encode("utf-8")),
            line_count=len(content.splitlines()) if content else 0,
            encoding="utf-8",
            content_hash=digest,
            last_modified=mtime,
        )
