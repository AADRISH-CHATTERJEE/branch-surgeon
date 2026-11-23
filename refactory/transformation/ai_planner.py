"""AI Refactoring Planner — natural language → structured TransformationPlan."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from refactory.transformation.models import (
    PlanOperation,
    TransformationPlan,
    TransformationRequest,
    TransformationStep,
    TransformationType,
)
from refactory.transformation.planner import TransformationPlanner
from refactory.transformation.symbol_index import RepositorySymbolIndex

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.ai.gateway import AIGateway
    from refactory.graph.service import RepositoryGraphService


class AIRefactoringPlanner:
    """Understand NL intent, inspect the repo, and produce a TransformationPlan."""

    def __init__(
        self,
        logger: "Logger",
        deterministic: TransformationPlanner,
        *,
        ai_gateway: "AIGateway | None" = None,
        graph_service: "RepositoryGraphService | None" = None,
    ) -> None:
        self._logger = logger
        self._deterministic = deterministic
        self._ai = ai_gateway
        self._graph = graph_service

    def plan_from_natural_language(
        self, text: str, root: Path, *, seed: TransformationRequest | None = None
    ) -> TransformationPlan:
        """Build a TransformationPlan from a natural-language request."""
        goal = (text or "").strip()
        if not goal:
            return TransformationPlan(
                description="Empty natural-language request.",
                goal="",
                steps=[],
                estimated_confidence=0.0,
            )

        intent = self._infer_intent(goal, seed=seed)
        self._logger.info("AI planner intent: {} ({})", intent.get("op"), intent.get("type"))

        # Prefer deterministic planners when we can map cleanly to a known op.
        if intent.get("type") in {
            TransformationType.RENAME_SYMBOL,
            TransformationType.RENAME_FUNCTION,
            TransformationType.RENAME_CLASS,
            TransformationType.RENAME_VARIABLE,
            TransformationType.RENAME_FILE,
            TransformationType.MOVE_SYMBOL,
            TransformationType.EXTRACT_METHOD,
            TransformationType.INLINE_METHOD,
        }:
            req = TransformationRequest(
                transformation_type=intent["type"],
                target_file=intent.get("target_file") or (seed.target_file if seed else ""),
                target_symbol=intent.get("target_symbol") or (seed.target_symbol if seed else ""),
                parameters=intent.get("parameters") or {},
                scope=intent.get("scope") or "repository",
                natural_language=goal,
                ai_assisted=True,
            )
            plan = self._deterministic.create_plan(req, root)
            plan.goal = goal
            plan.transformation_type = req.transformation_type
            if not plan.operations:
                plan.operations = [
                    PlanOperation(
                        op=str(intent.get("op") or "rename"),
                        description=plan.description or goal,
                        target=req.target_symbol,
                        files=list(plan.affected_files or [s.file_path for s in plan.steps]),
                    )
                ]
            if not plan.estimated_confidence:
                plan.estimated_confidence = 0.85
            self._enrich_from_graph(plan, root)
            return plan

        # Heuristic multi-step plans (e.g. split file) without requiring AI JSON.
        if intent.get("op") == "split_file":
            return self._plan_split_file(goal, intent, root)

        # Optional AI structured plan when gateway is available.
        ai_plan = self._try_ai_structured_plan(goal, root, seed=seed)
        if ai_plan is not None and ai_plan.steps:
            ai_plan.goal = goal
            self._enrich_from_graph(ai_plan, root)
            return ai_plan

        return TransformationPlan(
            description=(
                "Could not map the request to a supported refactoring operation. "
                "Try a clearer instruction such as "
                "\"Rename login() to authenticate()\"."
            ),
            goal=goal,
            steps=[],
            estimated_confidence=0.2,
            estimated_risk="high",
            operations=[
                PlanOperation(op="unknown", description=goal, target="", files=[])
            ],
        )

    # ------------------------------------------------------------------
    # Intent parsing
    # ------------------------------------------------------------------

    def _infer_intent(
        self, goal: str, *, seed: TransformationRequest | None
    ) -> dict[str, Any]:
        lower = goal.lower()

        # Rename login() to authenticate() / Rename X to Y
        m = re.search(
            r"rename\s+[`'\"]?([A-Za-z_][\w]*)[`'\"]?\s*(?:\(\))?\s+to\s+[`'\"]?([A-Za-z_][\w]*)[`'\"]?",
            goal,
            flags=re.IGNORECASE,
        )
        if m:
            old, new = m.group(1), m.group(2)
            ttype = TransformationType.RENAME_SYMBOL
            if "class" in lower:
                ttype = TransformationType.RENAME_CLASS
            elif "function" in lower or "()" in goal:
                ttype = TransformationType.RENAME_FUNCTION
            elif "variable" in lower:
                ttype = TransformationType.RENAME_VARIABLE
            return {
                "op": "rename",
                "type": ttype,
                "target_symbol": old,
                "parameters": {"old_name": old, "new_name": new},
                "scope": "repository",
                "target_file": seed.target_file if seed else "",
            }

        # Move … into services / Move X to Y
        m = re.search(
            r"move\s+[`'\"]?([A-Za-z_][\w]*)[`'\"]?\s+(?:into|to)\s+[`'\"]?([\w./\\]+)[`'\"]?",
            goal,
            flags=re.IGNORECASE,
        )
        if m:
            return {
                "op": "move",
                "type": TransformationType.MOVE_SYMBOL,
                "target_symbol": m.group(1),
                "parameters": {"destination_file": m.group(2)},
                "target_file": seed.target_file if seed else "",
            }

        # Extract validation / Extract method
        if "extract" in lower:
            return {
                "op": "extract",
                "type": TransformationType.EXTRACT_METHOD,
                "target_symbol": (seed.target_symbol if seed else "")
                or self._first_word_after(lower, "extract"),
                "parameters": {
                    "method_name": self._first_word_after(lower, "extract") or "extracted",
                },
                "target_file": seed.target_file if seed else "",
            }

        # Inline
        if "inline" in lower:
            return {
                "op": "inline",
                "type": TransformationType.INLINE_METHOD,
                "target_symbol": (seed.target_symbol if seed else "")
                or self._first_word_after(lower, "inline"),
                "target_file": seed.target_file if seed else "",
            }

        # Split auth.py into auth.py and security.py
        m = re.search(
            r"split\s+([A-Za-z0-9_./\\-]+\.py)\s+into\s+([A-Za-z0-9_./\\-]+\.py)\s+and\s+([A-Za-z0-9_./\\-]+\.py)",
            goal,
            flags=re.IGNORECASE,
        )
        if m:
            return {
                "op": "split_file",
                "type": TransformationType.ARCHITECTURE_REFACTORING,
                "source": m.group(1).replace("\\", "/"),
                "keep": m.group(2).replace("\\", "/"),
                "other": m.group(3).replace("\\", "/"),
            }

        return {"op": "unknown", "type": TransformationType.AI_PLAN}

    @staticmethod
    def _first_word_after(text: str, marker: str) -> str:
        parts = text.split(marker, 1)
        if len(parts) < 2:
            return ""
        for token in re.findall(r"[A-Za-z_][\w]*", parts[1]):
            if token.lower() not in {"method", "function", "class", "the", "a", "an"}:
                return token
        return ""

    def _plan_split_file(
        self, goal: str, intent: dict[str, Any], root: Path
    ) -> TransformationPlan:
        source = str(intent.get("source") or "")
        other = str(intent.get("other") or "")
        src_path = root / source
        if not source or not src_path.is_file() or not other:
            return TransformationPlan(
                description="Split file: source file not found or destination missing.",
                goal=goal,
                steps=[],
                estimated_confidence=0.3,
            )
        content = src_path.read_text(encoding="utf-8", errors="replace")
        # Heuristic: move class/functions whose names mention security/auth into other file.
        try:
            tree = __import__("ast").parse(content)
        except SyntaxError:
            return TransformationPlan(
                description="Split file: source has syntax errors.",
                goal=goal,
                steps=[],
                estimated_confidence=0.2,
            )

        lines = content.splitlines(keepends=True)
        move_ranges: list[tuple[int, int, str]] = []
        keep_hint = Path(other).stem.lower()
        for node in tree.body:
            if not isinstance(
                node, (__import__("ast").FunctionDef, __import__("ast").AsyncFunctionDef, __import__("ast").ClassDef)
            ):
                continue
            name = node.name.lower()
            if keep_hint in name or "security" in name or "auth" in name and "login" not in name:
                start = node.lineno - 1
                end = (node.end_lineno or node.lineno) - 1
                move_ranges.append((start, end, node.name))

        if not move_ranges:
            # Fallback: move the second half of the file.
            mid = max(1, len(lines) // 2)
            move_ranges = [(mid, len(lines) - 1, "block")]

        move_set = set()
        for start, end, _ in move_ranges:
            move_set.update(range(start, end + 1))

        kept = [ln for i, ln in enumerate(lines) if i not in move_set]
        moved = [ln for i, ln in enumerate(lines) if i in move_set]
        if not moved:
            return TransformationPlan(
                description="Split file produced no movable block.",
                goal=goal,
                steps=[],
                estimated_confidence=0.3,
            )

        new_source = "".join(kept).rstrip() + "\n"
        new_other = (
            f'"""Extracted from {source} by Refactory AI planner."""\n\n'
            + "".join(moved).rstrip()
            + "\n"
        )
        steps = [
            TransformationStep(
                file_path=source,
                action="modify",
                original_content=content,
                new_content=new_source,
                description=f"Trim {source} after split",
            ),
            TransformationStep(
                file_path=other,
                action="create",
                original_content="",
                new_content=new_other,
                description=f"Create {other} with extracted symbols",
            ),
        ]
        return TransformationPlan(
            description=f"Split {source} → {source} + {other}",
            goal=goal,
            steps=steps,
            estimated_risk="high",
            estimated_confidence=0.55,
            operations=[
                PlanOperation(
                    op="create_file",
                    description=f"Create {other}",
                    target=other,
                    files=[other],
                ),
                PlanOperation(
                    op="move",
                    description="Move selected symbols into the new file",
                    target=",".join(n for *_, n in move_ranges),
                    files=[source, other],
                ),
                PlanOperation(
                    op="update_imports",
                    description="Callers may need import updates (review carefully)",
                    target=other,
                    files=[source, other],
                ),
            ],
            dependencies=[source],
            affected_symbols=[n for *_, n in move_ranges],
        )

    def _try_ai_structured_plan(
        self,
        goal: str,
        root: Path,
        *,
        seed: TransformationRequest | None,
    ) -> TransformationPlan | None:
        if self._ai is None:
            return None
        try:
            from refactory.ai.models import AIRequest

            index = RepositorySymbolIndex(root, logger=self._logger).build(max_files=80)
            sample_symbols = []
            for name, ids in list(index._by_name.items())[:40]:
                sample_symbols.append(name)
            prompt = (
                "You are a refactoring planner. Return ONLY JSON with keys: "
                "operations (list of {op, description, target, files}), "
                "rename (optional {old_name, new_name}), "
                "target_file, target_symbol, risk, confidence.\n"
                f"Request: {goal}\n"
                f"Seed file: {(seed.target_file if seed else '')}\n"
                f"Known symbols: {', '.join(sample_symbols[:40])}\n"
            )
            resp = self._ai.generate(
                AIRequest(prompt=prompt, max_tokens=800, temperature=0.1)
            )
            text = getattr(resp, "content", None) or getattr(resp, "text", None) or str(resp)
            data = self._extract_json(text)
            if not data:
                return None
            rename = data.get("rename") or {}
            if rename.get("old_name") and rename.get("new_name"):
                req = TransformationRequest(
                    transformation_type=TransformationType.RENAME_SYMBOL,
                    target_file=str(data.get("target_file") or (seed.target_file if seed else "")),
                    target_symbol=str(rename.get("old_name")),
                    parameters={
                        "old_name": rename["old_name"],
                        "new_name": rename["new_name"],
                    },
                    scope="repository",
                    natural_language=goal,
                    ai_assisted=True,
                )
                plan = self._deterministic.create_plan(req, root)
                plan.goal = goal
                plan.estimated_confidence = float(data.get("confidence") or 0.7)
                plan.estimated_risk = str(data.get("risk") or plan.estimated_risk)
                ops_raw = data.get("operations") or []
                if ops_raw:
                    plan.operations = [
                        PlanOperation(
                            op=str(o.get("op") or "rename"),
                            description=str(o.get("description") or ""),
                            target=str(o.get("target") or ""),
                            files=list(o.get("files") or []),
                        )
                        for o in ops_raw
                        if isinstance(o, dict)
                    ]
                return plan
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("AI structured plan failed: {}", exc)
        return None

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        text = text.strip()
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            pass
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    def _enrich_from_graph(self, plan: TransformationPlan, root: Path) -> None:
        if self._graph is None:
            return
        try:
            # Best-effort: note most-connected files as dependencies.
            files = plan.affected_files or [s.file_path for s in plan.steps]
            if not files:
                return
            deps = list(plan.dependencies)
            for f in files[:5]:
                if f and f not in deps:
                    deps.append(f)
            plan.dependencies = deps
        except Exception:  # noqa: BLE001
            pass
