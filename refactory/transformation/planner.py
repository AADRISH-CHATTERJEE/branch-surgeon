"""Transformation planner — converts recommendations into actionable plans."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import TYPE_CHECKING

from refactory.transformation.models import (
    PlanOperation,
    TransformationPlan,
    TransformationRequest,
    TransformationStep,
    TransformationType,
)
from refactory.transformation.symbol_index import RepositorySymbolIndex, SymbolType

if TYPE_CHECKING:
    from loguru import Logger


class _SymbolRenamer(ast.NodeTransformer):
    """AST transformer that renames a symbol across all references."""

    def __init__(self, old_name: str, new_name: str) -> None:
        self.old = old_name
        self.new = new_name
        self.changed = False

    def visit_Name(self, node: ast.Name) -> ast.Name:
        if node.id == self.old:
            node.id = self.new
            self.changed = True
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        if node.name == self.old:
            node.name = self.new
            self.changed = True
        self.generic_visit(node)
        return node

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        if node.name == self.old:
            node.name = self.new
            self.changed = True
        self.generic_visit(node)
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:
        if node.attr == self.old:
            node.attr = self.new
            self.changed = True
        self.generic_visit(node)
        return node

    def visit_keyword(self, node: ast.keyword) -> ast.keyword:
        if node.arg == self.old:
            node.arg = self.new
            self.changed = True
        self.generic_visit(node)
        return node

    def visit_alias(self, node: ast.alias) -> ast.alias:
        if node.asname and node.asname == self.old:
            node.asname = self.new
            self.changed = True
        parts = node.name.split(".")
        if self.old in parts:
            parts = [self.new if p == self.old else p for p in parts]
            node.name = ".".join(parts)
            self.changed = True
        return node

    def visit_arg(self, node: ast.arg) -> ast.arg:
        if node.arg == self.old:
            node.arg = self.new
            self.changed = True
        return node


class TransformationPlanner:
    """Creates transformation plans from recommendations and requests."""

    def __init__(self, logger: "Logger") -> None:
        self._logger = logger

    def create_plan(self, request: TransformationRequest, root: Path) -> TransformationPlan:
        """Create a transformation plan for the given request."""
        self._logger.debug("Planning transformation: {}", request.transformation_type.value)

        handler = self._get_handler(request.transformation_type)
        plan = handler(request, root)
        plan.transformation_type = request.transformation_type
        plan.affected_files = [s.file_path for s in plan.steps if s.file_path]
        return plan

    def _get_handler(self, t_type: TransformationType):
        handlers = {
            TransformationType.RENAME_SYMBOL: self._plan_rename,
            TransformationType.RENAME_FUNCTION: self._plan_rename,
            TransformationType.RENAME_CLASS: self._plan_rename,
            TransformationType.RENAME_VARIABLE: self._plan_rename,
            TransformationType.RENAME_MODULE: self._plan_rename_module,
            TransformationType.RENAME_FILE: self._plan_rename_file,
            TransformationType.EXTRACT_METHOD: self._plan_extract_method,
            TransformationType.EXTRACT_CLASS: self._plan_extract_class,
            TransformationType.MOVE_METHOD: self._plan_move,
            TransformationType.MOVE_CLASS: self._plan_move,
            TransformationType.MOVE_SYMBOL: self._plan_move,
            TransformationType.INLINE_METHOD: self._plan_inline,
            TransformationType.CHANGE_SIGNATURE: self._plan_change_signature,
            TransformationType.REMOVE_DEAD_CODE: self._plan_remove_dead_code,
            TransformationType.REPLACE_DEPRECATED_API: self._plan_replace_api,
            TransformationType.UPDATE_IMPORTS: self._plan_update_imports,
            TransformationType.GENERATE_DOCSTRINGS: self._plan_generate_docstrings,
            TransformationType.GENERATE_TESTS: self._plan_generate_tests,
            TransformationType.FIX_RULE_VIOLATIONS: self._plan_fix_rules,
            TransformationType.SPLIT_LARGE_CLASS: self._plan_extract_class,
            TransformationType.CREATE_INTERFACE: self._plan_create_interface,
            TransformationType.ARCHITECTURE_REFACTORING: self._plan_architecture,
        }
        return handlers.get(t_type, self._plan_generic)

    def _plan_rename(self, req: TransformationRequest, root: Path) -> TransformationPlan:
        """Plan a repository-wide rename using the symbol index + AST edits.

        Scope:
        - ``repository`` (default for rename_*): update definition + all references
        - ``file``: limit edits to ``target_file`` (legacy / explicit single-file)
        """
        old_name = req.parameters.get("old_name") or req.target_symbol
        new_name = req.parameters.get("new_name") or ""
        if not old_name or not new_name:
            return TransformationPlan(
                description="Invalid transformation request. Rename requires old and new name.",
                steps=[],
            )
        if old_name == new_name:
            return TransformationPlan(
                description=f"Rename: '{old_name}' is already named '{new_name}'.",
                steps=[],
            )

        scope = (
            (req.scope or req.parameters.get("scope") or "repository")
            .strip()
            .lower()
        )
        # Backward-compatible escape hatch used by some unit fixtures.
        if req.parameters.get("single_file") is True:
            scope = "file"

        steps: list[TransformationStep] = []
        affected_symbols: list[str] = []

        # If the caller named a concrete file, it must exist (legacy + UX clarity).
        if req.target_file:
            hinted = root / req.target_file
            if not hinted.is_file():
                return TransformationPlan(
                    description=f"File '{req.target_file}' not found.",
                    steps=[],
                )

        if scope == "file":
            if not req.target_file:
                return TransformationPlan(
                    description="File-scoped rename requires target_file.",
                    steps=[],
                )
            files_to_scan = [root / req.target_file]
        else:
            index = RepositorySymbolIndex(root, logger=self._logger).build()
            type_filter = None
            if req.transformation_type == TransformationType.RENAME_FUNCTION:
                type_filter = {SymbolType.FUNCTION, SymbolType.REFERENCE, SymbolType.CALL}
            elif req.transformation_type == TransformationType.RENAME_CLASS:
                type_filter = {
                    SymbolType.CLASS,
                    SymbolType.REFERENCE,
                    SymbolType.INHERITANCE,
                }
            elif req.transformation_type == TransformationType.RENAME_VARIABLE:
                type_filter = {SymbolType.VARIABLE, SymbolType.REFERENCE}
            rel_files = index.files_referencing(
                old_name,
                prefer_definition_file=req.target_file,
                symbol_types=type_filter,
            )
            affected_symbols = index.affected_symbols(old_name)
            if not rel_files and req.target_file:
                rel_files = [req.target_file.replace("\\", "/")]
            files_to_scan = [root / rel for rel in rel_files]
            # Deduplicate while preserving order
            seen_paths: set[str] = set()
            unique: list[Path] = []
            for f in files_to_scan:
                key = str(f)
                if key in seen_paths:
                    continue
                seen_paths.add(key)
                unique.append(f)
            files_to_scan = unique[:200]

        symbol_seen = False
        for f in files_to_scan:
            if not f or not f.is_file():
                continue
            try:
                rel_parts = f.relative_to(root).parts
            except ValueError:
                continue
            if any(p in {"__pycache__", ".venv", ".git", ".refactory"} for p in rel_parts):
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                if old_name not in content:
                    continue
                symbol_seen = True
                new_content = self._ast_rename(content, old_name, new_name)
                if new_content != content:
                    rel = str(f.relative_to(root)).replace("\\", "/")
                    steps.append(
                        TransformationStep(
                            file_path=rel,
                            action="modify",
                            original_content=content,
                            new_content=new_content,
                            description=f"Rename '{old_name}' to '{new_name}'",
                        )
                    )
            except (OSError, UnicodeDecodeError):
                continue

        if not steps:
            if req.target_file and not symbol_seen:
                desc = f"Symbol '{old_name}' not found in {req.target_file}."
            elif not symbol_seen:
                desc = f"Symbol '{old_name}' not found in repository."
            else:
                desc = "Rename planner produced no edits."
            return TransformationPlan(description=desc, steps=[])

        # Deduplicate steps by file (last write wins — content already final).
        by_file: dict[str, TransformationStep] = {}
        for step in steps:
            by_file[step.file_path] = step
        steps = list(by_file.values())

        goal = f"Rename '{old_name}' → '{new_name}' across the repository"
        if scope == "file":
            goal = f"Rename '{old_name}' → '{new_name}' in {req.target_file}"

        return TransformationPlan(
            description=f"Rename '{old_name}' → '{new_name}'",
            goal=goal,
            steps=steps,
            estimated_risk="low" if len(steps) <= 3 else "medium",
            estimated_confidence=0.92 if len(steps) <= 5 else 0.8,
            affected_symbols=affected_symbols or [f"symbol:{old_name}"],
            operations=[
                PlanOperation(
                    op="rename",
                    description=f"Rename {old_name} → {new_name}",
                    target=old_name,
                    files=[s.file_path for s in steps],
                ),
                PlanOperation(
                    op="update_references",
                    description="Update imports, calls, aliases, and type hints",
                    target=old_name,
                    files=[s.file_path for s in steps],
                ),
            ],
            dependencies=[req.target_file] if req.target_file else [],
        )

    def _plan_rename_file(self, req: TransformationRequest, root: Path) -> TransformationPlan:
        """Rename a file path and rewrite imports that reference the old module."""
        source = req.target_file or req.parameters.get("source_file") or ""
        dest = req.parameters.get("new_name") or req.parameters.get("destination_file") or ""
        if not source or not dest:
            return TransformationPlan(
                description="Rename file requires target_file and new_name (destination path).",
                steps=[],
            )
        src_path = root / source
        if not src_path.is_file():
            return TransformationPlan(description=f"File '{source}' not found.", steps=[])
        content = src_path.read_text(encoding="utf-8", errors="replace")
        old_mod = Path(source).with_suffix("").as_posix().replace("/", ".")
        new_mod = Path(dest).with_suffix("").as_posix().replace("/", ".")
        steps: list[TransformationStep] = [
            TransformationStep(
                file_path=source.replace("\\", "/"),
                action="delete",
                original_content=content,
                new_content="",
                description=f"Delete old path {source}",
            ),
            TransformationStep(
                file_path=dest.replace("\\", "/"),
                action="create",
                original_content="",
                new_content=content,
                description=f"Create {dest}",
            ),
        ]
        # Update imports of the old module across the repo.
        for f in list(root.rglob("*.py"))[:200]:
            try:
                rel = str(f.relative_to(root)).replace("\\", "/")
            except ValueError:
                continue
            if rel in {source.replace("\\", "/"), dest.replace("\\", "/")}:
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            if old_mod not in text:
                continue
            updated = text.replace(f"import {old_mod}", f"import {new_mod}")
            updated = updated.replace(f"from {old_mod} ", f"from {new_mod} ")
            updated = updated.replace(f"from {old_mod}.", f"from {new_mod}.")
            if updated != text:
                steps.append(
                    TransformationStep(
                        file_path=rel,
                        action="modify",
                        original_content=text,
                        new_content=updated,
                        description=f"Update imports {old_mod} → {new_mod}",
                    )
                )
        return TransformationPlan(
            description=f"Rename file {source} → {dest}",
            goal=f"Rename file {source} to {dest} and update imports",
            steps=steps,
            estimated_risk="medium",
            estimated_confidence=0.75,
            operations=[
                PlanOperation(op="rename", description="Rename file", target=source, files=[source, dest]),
                PlanOperation(
                    op="update_imports",
                    description=f"Rewrite imports {old_mod} → {new_mod}",
                    target=old_mod,
                    files=[s.file_path for s in steps if s.action == "modify"],
                ),
            ],
        )

    def _plan_rename_module(self, req: TransformationRequest, root: Path) -> TransformationPlan:
        """Alias of rename_file for module-style destinations."""
        return self._plan_rename_file(req, root)

    def _ast_rename(self, source: str, old_name: str, new_name: str) -> str:
        """Rename a symbol using AST to find precise positions of all references."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return source.replace(old_name, new_name)

        lines = source.splitlines(keepends=True)
        positions: list[tuple[int, int]] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == old_name:
                positions.append((node.lineno - 1, node.col_offset))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == old_name:
                line = lines[node.lineno - 1] if node.lineno - 1 < len(lines) else ""
                col = line.find(f" {old_name}(")
                if col >= 0:
                    col += 1
                else:
                    col = line.find(f" {old_name}")
                    if col >= 0:
                        col += 1
                if col >= 0:
                    positions.append((node.lineno - 1, col))
            elif isinstance(node, ast.ClassDef) and node.name == old_name:
                line = lines[node.lineno - 1] if node.lineno - 1 < len(lines) else ""
                col = line.find(f"class {old_name}")
                if col >= 0:
                    col += 6
                    positions.append((node.lineno - 1, col))
            elif isinstance(node, ast.Attribute) and node.attr == old_name:
                line = lines[node.end_lineno - 1] if hasattr(node, "end_lineno") and node.end_lineno else ""
                if line:
                    ln = (node.end_lineno or node.lineno) - 1
                    col = (node.end_col_offset or 0) - len(old_name)
                    if col >= 0 and line[col:col + len(old_name)] == old_name:
                        positions.append((ln, col))
            elif isinstance(node, ast.arg) and node.arg == old_name:
                positions.append((node.lineno - 1, node.col_offset))
            elif isinstance(node, ast.alias):
                # `from mod import old` / `import old` / `import pkg.old`
                if not hasattr(node, "lineno"):
                    continue
                line = lines[node.lineno - 1] if node.lineno - 1 < len(lines) else ""
                if node.asname == old_name:
                    # Prefer end of alias span for `as old_name`
                    if hasattr(node, "end_col_offset") and node.end_col_offset:
                        col = node.end_col_offset - len(old_name)
                        if col >= 0 and line[col : col + len(old_name)] == old_name:
                            positions.append((node.lineno - 1, col))
                    else:
                        col = line.rfind(old_name)
                        if col >= 0:
                            positions.append((node.lineno - 1, col))
                else:
                    parts = node.name.split(".")
                    if old_name in parts:
                        # Rename the matching segment; usually the imported leaf name.
                        leaf = parts[-1]
                        if leaf == old_name and hasattr(node, "col_offset"):
                            # For dotted imports, leaf starts near end_col - len(leaf)
                            if "." in node.name and hasattr(node, "end_col_offset"):
                                col = node.end_col_offset - len(old_name)
                            else:
                                col = node.col_offset
                            if col >= 0 and line[col : col + len(old_name)] == old_name:
                                positions.append((node.lineno - 1, col))

        if not positions:
            return source

        positions.sort()
        seen: set[tuple[int, int]] = set()
        unique_positions: list[tuple[int, int]] = []
        for pos in positions:
            if pos not in seen:
                seen.add(pos)
                unique_positions.append(pos)

        result_lines = list(lines)
        for line_no, edits in self._group_by_line(unique_positions):
            if line_no >= len(result_lines):
                continue
            line = result_lines[line_no]
            for col in reversed(edits):
                end = col + len(old_name)
                if line[col:end] == old_name:
                    line = line[:col] + new_name + line[end:]
            result_lines[line_no] = line

        return "".join(result_lines)

    @staticmethod
    def _group_by_line(positions: list[tuple[int, int]]) -> list[tuple[int, list[int]]]:
        groups: dict[int, list[int]] = {}
        for ln, col in positions:
            groups.setdefault(ln, []).append(col)
        return sorted(groups.items())

    def _plan_extract_method(self, req: TransformationRequest, root: Path) -> TransformationPlan:
        """Plan method extraction using AST analysis."""
        target = root / req.target_file if req.target_file else None
        if not target or not target.is_file():
            return TransformationPlan(
                description=f"File '{req.target_file}' not found.",
                steps=[],
            )

        content = target.read_text(encoding="utf-8", errors="replace")
        start = int(req.parameters.get("start_line") or 0)
        end = int(req.parameters.get("end_line") or 0)
        method_name = (
            req.parameters.get("method_name")
            or req.parameters.get("new_name")
            or "extracted_method"
        )

        if (not start or not end or start > end) and req.target_symbol:
            resolved = self._function_body_range(content, req.target_symbol)
            if resolved:
                start, end = resolved

        if not start or not end or start > end:
            return TransformationPlan(
                description=(
                    "Extract method: start_line and end_line required "
                    "(or provide target_symbol of a function to extract its body)"
                ),
                steps=[],
            )

        lines = content.split("\n")
        if start < 1 or end > len(lines):
            return TransformationPlan(
                description=f"Extract method: line range {start}-{end} out of bounds",
                steps=[],
            )

        extracted_lines = lines[start - 1:end]
        if not extracted_lines:
            return TransformationPlan(description="Extract method: empty selection", steps=[])

        enclosing_indent = self._detect_enclosing_indent(lines, start)
        body_indent = enclosing_indent + "    "
        call_indent = self._detect_line_indent(extracted_lines[0])

        used_names = self._find_used_names(extracted_lines, content, start, end)
        params = ", ".join(sorted(used_names))
        args = ", ".join(sorted(used_names))

        new_func_lines = [f"{enclosing_indent}def {method_name}({params}):"]
        for el in extracted_lines:
            stripped = el.rstrip()
            if stripped:
                relative = stripped[len(call_indent):] if stripped.startswith(call_indent) else stripped
                new_func_lines.append(f"{body_indent}{relative}")
            else:
                new_func_lines.append("")

        call_line = f"{call_indent}{method_name}({args})"

        new_lines = lines[:start - 1] + [call_line] + lines[end:]
        insert_pos = self._find_insert_position(new_lines, start - 1, enclosing_indent)
        new_lines = new_lines[:insert_pos] + [""] + new_func_lines + [""] + new_lines[insert_pos:]

        new_content = "\n".join(new_lines)

        try:
            ast.parse(new_content)
        except SyntaxError:
            pass

        rel = str(target.relative_to(root)).replace("\\", "/")
        return TransformationPlan(
            description=f"Extract method '{method_name}' from {rel}",
            steps=[TransformationStep(
                file_path=rel,
                original_content=content,
                new_content=new_content,
                start_line=start,
                end_line=end,
                description=f"Extract lines {start}-{end} into {method_name}()",
            )],
            estimated_risk="medium",
        )

    def _detect_enclosing_indent(self, lines: list[str], start_line: int) -> str:
        """Find the indentation of the enclosing scope."""
        target_indent = self._detect_line_indent(lines[start_line - 1])
        for i in range(start_line - 2, -1, -1):
            line = lines[i]
            if not line.strip():
                continue
            line_indent = self._detect_line_indent(line)
            if len(line_indent) < len(target_indent):
                return line_indent
        return ""

    @staticmethod
    def _detect_line_indent(line: str) -> str:
        return line[: len(line) - len(line.lstrip())]

    def _find_used_names(
        self, extracted_lines: list[str], full_content: str, start: int, end: int
    ) -> set[str]:
        """Find variable names used in extracted code that are defined outside."""
        extracted_src = "\n".join(extracted_lines)
        try:
            extracted_tree = ast.parse(extracted_src)
        except SyntaxError:
            return set()

        used: set[str] = set()
        assigned: set[str] = set()
        for node in ast.walk(extracted_tree):
            if isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Load):
                    used.add(node.id)
                elif isinstance(node.ctx, ast.Store):
                    assigned.add(node.id)

        try:
            full_tree = ast.parse(full_content)
        except SyntaxError:
            return set()

        outer_assigned: set[str] = set()
        for node in ast.walk(full_tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                if hasattr(node, "lineno") and (node.lineno < start or node.lineno > end):
                    outer_assigned.add(node.id)
            if isinstance(node, ast.arg):
                if hasattr(node, "lineno") and (node.lineno < start or node.lineno > end):
                    outer_assigned.add(node.arg)

        import builtins
        builtin_names = set(dir(builtins))
        return (used - assigned) & outer_assigned - builtin_names

    @staticmethod
    def _find_insert_position(lines: list[str], call_pos: int, enclosing_indent: str) -> int:
        """Find where to insert the new method definition."""
        for i in range(call_pos + 1, len(lines)):
            line = lines[i]
            if not line.strip():
                continue
            current_indent = line[:len(line) - len(line.lstrip())]
            if len(current_indent) <= len(enclosing_indent):
                return i
        return len(lines)

    def _plan_extract_class(self, req: TransformationRequest, root: Path) -> TransformationPlan:
        """Plan a class extraction."""
        return TransformationPlan(
            description=f"Extract class from {req.target_file}",
            steps=[],
            estimated_risk="high",
        )

    def _plan_move(self, req: TransformationRequest, root: Path) -> TransformationPlan:
        """Plan moving a function/class between files (AST-based)."""
        source_rel = req.parameters.get("source_file") or req.target_file
        dest_rel = req.parameters.get("destination_file") or ""
        symbol = req.target_symbol or req.parameters.get("symbol") or ""
        if not source_rel or not dest_rel:
            return TransformationPlan(
                description="Move symbol: destination_file required",
                steps=[],
                estimated_risk="medium",
            )
        if not symbol:
            return TransformationPlan(
                description="Move symbol: target_symbol required",
                steps=[],
                estimated_risk="medium",
            )

        source = root / source_rel
        dest = root / dest_rel
        if not source.is_file():
            return TransformationPlan(
                description=f"File '{source_rel}' not found.",
                steps=[],
            )

        source_content = source.read_text(encoding="utf-8", errors="replace")
        dest_content = (
            dest.read_text(encoding="utf-8", errors="replace") if dest.is_file() else ""
        )

        block, new_source = self._extract_symbol_block(source_content, symbol)
        if not block or new_source is None:
            return TransformationPlan(
                description=f"Symbol '{symbol}' not found in {source_rel}.",
                steps=[],
            )

        # Append moved definition to destination; add import stub in source.
        dest_module = dest_rel.replace("\\", "/").removesuffix(".py").replace("/", ".")
        import_line = f"from {dest_module} import {symbol}\n"
        if import_line.strip() not in new_source and f"import {symbol}" not in new_source:
            new_source = import_line + new_source if new_source else import_line

        sep = "\n\n" if dest_content.strip() else ""
        new_dest = dest_content.rstrip() + sep + block.strip() + "\n"

        try:
            ast.parse(new_source)
            ast.parse(new_dest)
        except SyntaxError as exc:
            return TransformationPlan(
                description=f"Move symbol: resulting syntax invalid ({exc})",
                steps=[],
            )

        source_norm = source_rel.replace("\\", "/")
        dest_norm = dest_rel.replace("\\", "/")
        steps = [
            TransformationStep(
                file_path=source_norm,
                original_content=source_content,
                new_content=new_source,
                description=f"Remove '{symbol}' and add import",
            ),
            TransformationStep(
                file_path=dest_norm,
                action="create" if not dest.is_file() else "modify",
                original_content=dest_content,
                new_content=new_dest,
                description=f"Add '{symbol}' definition",
            ),
        ]
        # Repository-wide: rewrite imports that previously imported from the source module.
        old_mod = Path(source_norm).with_suffix("").as_posix().replace("/", ".")
        new_mod = Path(dest_norm).with_suffix("").as_posix().replace("/", ".")
        index = RepositorySymbolIndex(root, logger=self._logger).build()
        for rel in index.files_referencing(symbol, prefer_definition_file=source_norm):
            if rel in {source_norm, dest_norm}:
                continue
            path = root / rel
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            updated = text
            updated = updated.replace(f"from {old_mod} import {symbol}", f"from {new_mod} import {symbol}")
            updated = updated.replace(f"from {old_mod} import", f"from {new_mod} import")
            if updated != text:
                steps.append(
                    TransformationStep(
                        file_path=rel,
                        action="modify",
                        original_content=text,
                        new_content=updated,
                        description=f"Update imports for moved '{symbol}'",
                    )
                )
        by_file: dict[str, TransformationStep] = {s.file_path: s for s in steps}
        steps = list(by_file.values())
        return TransformationPlan(
            description=f"Move '{symbol}' from {source_norm} → {dest_norm}",
            goal=f"Move '{symbol}' and update repository imports",
            steps=steps,
            estimated_risk="medium",
            estimated_confidence=0.8,
            operations=[
                PlanOperation(
                    op="move",
                    description=f"Move {symbol}",
                    target=symbol,
                    files=[source_norm, dest_norm],
                ),
                PlanOperation(
                    op="update_imports",
                    description="Update imports across referencing files",
                    target=symbol,
                    files=[s.file_path for s in steps],
                ),
            ],
            affected_symbols=[f"function:{symbol}", f"class:{symbol}"],
        )

    def _plan_inline(self, req: TransformationRequest, root: Path) -> TransformationPlan:
        """Plan inlining a simple function into its call sites (repository-wide)."""
        symbol = req.target_symbol or req.parameters.get("symbol") or ""
        if not symbol:
            return TransformationPlan(
                description="Inline method: target_symbol required",
                steps=[],
                estimated_risk="medium",
            )

        index = RepositorySymbolIndex(root, logger=self._logger).build()
        rel_files = index.files_referencing(
            symbol,
            prefer_definition_file=req.target_file,
            symbol_types={SymbolType.FUNCTION, SymbolType.REFERENCE, SymbolType.CALL},
        )
        if req.target_file and req.target_file.replace("\\", "/") not in rel_files:
            rel_files = [req.target_file.replace("\\", "/")] + rel_files
        if not rel_files and req.target_file:
            rel_files = [req.target_file.replace("\\", "/")]

        # Locate definition file + expression body.
        def_rel = ""
        content = ""
        func_node: ast.FunctionDef | ast.AsyncFunctionDef | None = None
        candidates = [req.target_file.replace("\\", "/")] if req.target_file else []
        candidates.extend(rel_files)
        seen: set[str] = set()
        for rel in candidates:
            if not rel or rel in seen:
                continue
            seen.add(rel)
            path = root / rel
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol:
                    def_rel = rel
                    content = text
                    func_node = node
                    break
            if func_node is not None:
                break

        if func_node is None or not def_rel:
            return TransformationPlan(
                description=f"Symbol '{symbol}' not found in repository.",
                steps=[],
            )

        body = list(func_node.body)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]  # skip docstring
        if len(body) != 1 or not isinstance(body[0], ast.Return) or body[0].value is None:
            return TransformationPlan(
                description=(
                    f"Inline method: '{symbol}' body is not a single return expression "
                    "(only simple return functions are supported)"
                ),
                steps=[],
            )

        expr_src = ast.get_source_segment(content, body[0].value) or ""
        if not expr_src:
            return TransformationPlan(
                description=f"Inline method: unable to read body of '{symbol}'",
                steps=[],
            )

        param_names = [a.arg for a in func_node.args.args]
        call_pattern = re.compile(rf"\b{re.escape(symbol)}\s*\(([^)]*)\)")

        def _replace_call(match: re.Match[str]) -> str:
            args_raw = [a.strip() for a in match.group(1).split(",") if a.strip()]
            replaced = expr_src
            for pname, arg in zip(param_names, args_raw):
                replaced = re.sub(rf"\b{re.escape(pname)}\b", arg, replaced)
            return f"({replaced})"

        steps: list[TransformationStep] = []
        files_to_edit = sorted(set(rel_files) | {def_rel})
        for rel in files_to_edit:
            path = root / rel
            if not path.is_file():
                continue
            original = path.read_text(encoding="utf-8", errors="replace")
            updated = original
            if rel == def_rel:
                lines = original.splitlines(keepends=True)
                start = func_node.lineno - 1
                end = func_node.end_lineno or func_node.lineno
                updated = "".join(lines[:start] + lines[end:])
            updated = call_pattern.sub(_replace_call, updated)
            # Drop now-unused import of the inlined symbol from other files.
            if rel != def_rel:
                updated = re.sub(
                    rf"^from\s+[\w.]+\s+import\s+{re.escape(symbol)}\s*$",
                    "",
                    updated,
                    flags=re.MULTILINE,
                )
            if updated == original:
                continue
            try:
                ast.parse(updated)
            except SyntaxError:
                continue
            steps.append(
                TransformationStep(
                    file_path=rel,
                    action="modify",
                    original_content=original,
                    new_content=updated,
                    description=f"Inline '{symbol}'",
                )
            )

        if not steps:
            return TransformationPlan(
                description=f"Inline method: no call sites found for '{symbol}'",
                steps=[],
            )

        by_file: dict[str, TransformationStep] = {s.file_path: s for s in steps}
        steps = list(by_file.values())
        return TransformationPlan(
            description=f"Inline method '{symbol}' across repository",
            goal=f"Inline '{symbol}' at all call sites and remove definition",
            steps=steps,
            estimated_risk="medium",
            estimated_confidence=0.75,
            operations=[
                PlanOperation(
                    op="inline",
                    description=f"Inline {symbol}",
                    target=symbol,
                    files=[s.file_path for s in steps],
                ),
                PlanOperation(
                    op="update_references",
                    description="Replace call sites and clean imports",
                    target=symbol,
                    files=[s.file_path for s in steps],
                ),
            ],
            affected_symbols=[f"function:{symbol}"],
        )

    def _plan_change_signature(
        self, req: TransformationRequest, root: Path
    ) -> TransformationPlan:
        """Rename/reorder parameters of a function and update call sites in-file."""
        target = root / req.target_file if req.target_file else None
        symbol = req.target_symbol or ""
        if not target or not target.is_file():
            return TransformationPlan(
                description=f"File '{req.target_file}' not found.",
                steps=[],
            )
        if not symbol:
            return TransformationPlan(
                description="Change signature: target_symbol required",
                steps=[],
            )

        content = target.read_text(encoding="utf-8", errors="replace")
        rename_params = req.parameters.get("rename_params") or {}
        param_order = req.parameters.get("param_order") or []
        new_func_name = req.parameters.get("new_name") or ""

        if not rename_params and not param_order and not new_func_name:
            return TransformationPlan(
                description=(
                    "Change signature: provide new_name, rename_params, and/or param_order"
                ),
                steps=[],
            )

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return TransformationPlan(
                description="Change signature: source has syntax errors",
                steps=[],
            )

        func_node: ast.FunctionDef | ast.AsyncFunctionDef | None = None
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol:
                func_node = node
                break
        if func_node is None:
            return TransformationPlan(
                description=f"Symbol '{symbol}' not found in {req.target_file}.",
                steps=[],
            )

        old_params = [a.arg for a in func_node.args.args]
        new_params = list(old_params)
        if param_order:
            missing = [p for p in param_order if p not in old_params]
            if missing or set(param_order) != set(old_params):
                return TransformationPlan(
                    description=(
                        "Change signature: param_order must be a permutation of "
                        f"existing parameters {old_params}"
                    ),
                    steps=[],
                )
            new_params = list(param_order)
        if rename_params:
            new_params = [rename_params.get(p, p) for p in new_params]

        # Rewrite definition line via AST unparse of args is brittle; do positional rewrite.
        lines = content.splitlines(keepends=True)
        def_line_idx = func_node.lineno - 1
        def_line = lines[def_line_idx]
        # Build new parameter list text.
        new_params_text = ", ".join(new_params)
        def_re = re.compile(
            rf"^(\s*(?:async\s+)?def\s+){re.escape(symbol)}(\s*\()([^)]*)(\).*)"
        )
        m = def_re.match(def_line.rstrip("\n"))
        if not m:
            return TransformationPlan(
                description="Change signature: unable to parse function definition line",
                steps=[],
            )
        name_out = new_func_name or symbol
        newline = "\n" if def_line.endswith("\n") else ""
        lines[def_line_idx] = f"{m.group(1)}{name_out}{m.group(2)}{new_params_text}{m.group(4)}{newline}"

        updated = "".join(lines)
        # Rename body parameter references.
        for old, new in rename_params.items():
            if old != new:
                updated = self._ast_rename(updated, old, new)
        if new_func_name and new_func_name != symbol:
            updated = self._ast_rename(updated, symbol, new_func_name)

        # Reorder positional call-site arguments for same-file calls.
        if param_order and param_order != old_params:
            updated = self._reorder_call_args(updated, name_out, old_params, param_order)

        try:
            ast.parse(updated)
        except SyntaxError as exc:
            return TransformationPlan(
                description=f"Change signature: resulting syntax invalid ({exc})",
                steps=[],
            )
        if updated == content:
            return TransformationPlan(
                description="Change signature: no changes produced",
                steps=[],
            )

        rel = str(target.relative_to(root)).replace("\\", "/")
        desc_bits = []
        if new_func_name:
            desc_bits.append(f"rename → {new_func_name}")
        if rename_params:
            desc_bits.append(f"params {rename_params}")
        if param_order:
            desc_bits.append(f"order {param_order}")
        return TransformationPlan(
            description=f"Change signature of '{symbol}' ({', '.join(desc_bits)})",
            steps=[TransformationStep(
                file_path=rel,
                original_content=content,
                new_content=updated,
                description=f"Change signature of {symbol}",
            )],
            estimated_risk="medium",
        )

    def _plan_remove_dead_code(self, req: TransformationRequest, root: Path) -> TransformationPlan:
        """Plan dead code removal."""
        target = root / req.target_file if req.target_file else None
        if not target or not target.is_file():
            return TransformationPlan(
                description=f"File '{req.target_file}' not found.",
                steps=[],
            )

        content = target.read_text(encoding="utf-8", errors="replace")
        symbol = req.target_symbol or req.parameters.get("symbol", "")
        if not symbol:
            return TransformationPlan(description="Remove dead code: no symbol specified", steps=[])

        pattern = re.compile(rf"^(def|class)\s+{re.escape(symbol)}\b.*?(?=\n(?:def|class)\s|\Z)", re.MULTILINE | re.DOTALL)
        new_content = pattern.sub("", content)
        rel = str(target.relative_to(root)).replace("\\", "/")

        if new_content == content:
            return TransformationPlan(
                description=f"Symbol '{symbol}' not found in {req.target_file}.",
                steps=[],
            )

        return TransformationPlan(
            description=f"Remove dead code: {symbol}",
            steps=[TransformationStep(
                file_path=rel,
                original_content=content,
                new_content=new_content,
                description=f"Remove unused '{symbol}'",
            )],
            estimated_risk="low",
        )

    def _plan_replace_api(self, req: TransformationRequest, root: Path) -> TransformationPlan:
        """Plan deprecated API replacement."""
        old_api = req.parameters.get("old_api", "")
        new_api = req.parameters.get("new_api", "")
        if not old_api or not new_api:
            return TransformationPlan(description="Replace API: missing parameters", steps=[])

        req_copy = TransformationRequest(
            target_file=req.target_file,
            parameters={"old_name": old_api, "new_name": new_api},
        )
        return self._plan_rename(req_copy, root)

    def _plan_update_imports(self, req: TransformationRequest, root: Path) -> TransformationPlan:
        """Plan import updates."""
        return TransformationPlan(
            description=f"Update imports in {req.target_file}",
            steps=[],
            estimated_risk="low",
        )

    def _plan_generate_docstrings(self, req: TransformationRequest, root: Path) -> TransformationPlan:
        """Plan docstring generation — produces syntactically valid Python."""
        target = root / req.target_file if req.target_file else None
        if not target or not target.is_file():
            return TransformationPlan(
                description=f"File '{req.target_file}' not found.",
                steps=[],
            )

        content = target.read_text(encoding="utf-8", errors="replace")
        rel = str(target.relative_to(root)).replace("\\", "/")
        lines = content.split("\n")
        new_lines: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            new_lines.append(line)
            match = re.match(r"^(\s*)def\s+(\w+)", line)
            if match and not line.strip().startswith("#"):
                leading_ws = match.group(1)
                func_name = match.group(2)
                body_indent = leading_ws + "    "
                next_idx = i + 1
                while next_idx < len(lines) and lines[next_idx].strip() == "":
                    next_idx += 1
                has_docstring = (
                    next_idx < len(lines)
                    and ('"""' in lines[next_idx] or "'''" in lines[next_idx])
                )
                if not has_docstring:
                    new_lines.append(f'{body_indent}"""TODO: Document {func_name}."""')
            i += 1

        new_content = "\n".join(new_lines)
        if new_content == content:
            return TransformationPlan(description="No missing docstrings", steps=[])

        return TransformationPlan(
            description=f"Generate docstrings for {rel}",
            steps=[TransformationStep(
                file_path=rel,
                original_content=content,
                new_content=new_content,
                description="Add placeholder docstrings",
            )],
            estimated_risk="low",
        )

    def _plan_generate_tests(self, req: TransformationRequest, root: Path) -> TransformationPlan:
        """Plan test generation (AI-assisted)."""
        return TransformationPlan(
            description=f"Generate tests for {req.target_file}",
            steps=[],
            estimated_risk="low",
        )

    def _plan_fix_rules(self, req: TransformationRequest, root: Path) -> TransformationPlan:
        """Plan rule violation fixes."""
        return TransformationPlan(
            description="Fix rule violations",
            steps=[],
            estimated_risk="low",
        )

    def _plan_create_interface(self, req: TransformationRequest, root: Path) -> TransformationPlan:
        """Plan interface creation."""
        return TransformationPlan(
            description=f"Create interface for {req.target_symbol}",
            steps=[],
            estimated_risk="medium",
        )

    def _plan_architecture(self, req: TransformationRequest, root: Path) -> TransformationPlan:
        """Plan architectural refactoring."""
        return TransformationPlan(
            description="Architecture refactoring",
            steps=[],
            estimated_risk="high",
        )

    @staticmethod
    def _function_body_range(source: str, name: str) -> tuple[int, int] | None:
        """Return 1-based inclusive line range of a function body (no docstring)."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name != name:
                continue
            body = list(node.body)
            if not body:
                return None
            if (
                isinstance(body[0], ast.Expr)
                and isinstance(getattr(body[0], "value", None), ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body = body[1:]
            if not body:
                return None
            start = body[0].lineno
            end = max(getattr(b, "end_lineno", b.lineno) or b.lineno for b in body)
            return start, end
        return None

    @staticmethod
    def _extract_symbol_block(
        source: str, symbol: str
    ) -> tuple[str | None, str | None]:
        """Remove a top-level function/class from source; return (block, remainder)."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None, None
        lines = source.splitlines(keepends=True)
        for node in tree.body:
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                continue
            if node.name != symbol:
                continue
            start = node.lineno - 1
            end = node.end_lineno or node.lineno
            block = "".join(lines[start:end])
            remainder = "".join(lines[:start] + lines[end:])
            return block, remainder
        return None, None

    @staticmethod
    def _reorder_call_args(
        source: str,
        func_name: str,
        old_order: list[str],
        new_order: list[str],
    ) -> str:
        """Reorder positional arguments at same-file call sites (best-effort AST)."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return source
        index_map = [old_order.index(p) for p in new_order]
        edits: list[tuple[int, int, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = node.func
            name = None
            if isinstance(called, ast.Name):
                name = called.id
            if name != func_name:
                continue
            if node.keywords:
                continue
            if len(node.args) != len(old_order):
                continue
            segs = [ast.get_source_segment(source, a) for a in node.args]
            if any(s is None for s in segs):
                continue
            reordered = [segs[i] for i in index_map]
            start = node.args[0].lineno
            # Replace full arg list text between parentheses — use segment of Call.
            call_src = ast.get_source_segment(source, node)
            if not call_src or "(" not in call_src:
                continue
            open_paren = call_src.find("(")
            close_paren = call_src.rfind(")")
            if open_paren < 0 or close_paren < 0:
                continue
            new_call = (
                call_src[: open_paren + 1]
                + ", ".join(reordered)  # type: ignore[arg-type]
                + call_src[close_paren:]
            )
            if call_src in source:
                idx = source.index(call_src)
                edits.append((idx, idx + len(call_src), new_call))

        if not edits:
            return source
        out = source
        for start_i, end_i, repl in sorted(edits, key=lambda e: e[0], reverse=True):
            out = out[:start_i] + repl + out[end_i:]
        return out

    def _plan_generic(self, req: TransformationRequest, root: Path) -> TransformationPlan:
        """Fallback for unsupported transformation types."""
        return TransformationPlan(
            description=f"Transformation: {req.transformation_type.value}",
            steps=[],
            estimated_risk="medium",
        )
