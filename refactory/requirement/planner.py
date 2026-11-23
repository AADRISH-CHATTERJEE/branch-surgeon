"""ImplementationPlanner — deterministic complexity, risk, confidence,
and implementation order estimation.

No AI. No network. Pure heuristics over requirement metadata and
repository search results.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from refactory.requirement.models import (
    Complexity,
    RequirementCandidate,
    RequirementImpact,
    RequirementPlan,
    RequirementSummary,
    RiskEstimate,
)

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.graph.service import RepositoryGraphService

# Priority ordering: lower number = implement first
_LAYER_PRIORITY: dict[str, int] = {
    "auth": 1,
    "security": 1,
    "model": 2,
    "schema": 2,
    "database": 2,
    "db": 2,
    "migration": 2,
    "config": 3,
    "settings": 3,
    "service": 4,
    "core": 4,
    "util": 5,
    "utils": 5,
    "helper": 5,
    "api": 6,
    "route": 6,
    "router": 6,
    "controller": 6,
    "handler": 6,
    "middleware": 6,
    "view": 7,
    "template": 7,
    "email": 7,
    "notification": 7,
}

_RISK_KEYWORDS = frozenset({
    "auth", "security", "password", "token", "encrypt", "decrypt",
    "database", "migration", "schema", "transaction", "secret",
    "permission", "role", "access", "session", "credential",
    "payment", "billing", "financial",
})


class ImplementationPlanner:
    """Estimate complexity, risk, confidence, and implementation order."""

    def __init__(
        self,
        logger: "Logger",
        graph_service: "RepositoryGraphService | None" = None,
    ) -> None:
        self._logger = logger
        self._graph = graph_service

    def plan(
        self,
        summary: RequirementSummary,
        candidates: list[RequirementCandidate],
        impacts: list[RequirementImpact],
        impacted_tests: list[str],
        impacted_docs: list[str],
    ) -> RequirementPlan:
        complexity = self._estimate_complexity(
            summary, candidates, impacts
        )
        risk = self._estimate_risk(summary, impacts)
        effort = self._estimate_effort(complexity)
        order = self._implementation_order(
            candidates, impacted_tests, impacted_docs
        )

        return RequirementPlan(
            implementation_order=order,
            estimated_complexity=complexity,
            estimated_risk=risk,
            estimated_effort=effort,
        )

    def estimate_confidence(
        self,
        summary: RequirementSummary,
        candidates: list[RequirementCandidate],
    ) -> float:
        """Compute an overall confidence score (0-1)."""
        if not summary.detected_keywords:
            return 0.0
        if not candidates:
            return 0.1

        keyword_signal = min(len(summary.detected_keywords) / 5.0, 1.0) * 0.3
        feature_signal = min(len(summary.detected_features) / 3.0, 1.0) * 0.2
        candidate_signal = min(len(candidates) / 5.0, 1.0) * 0.3

        avg_conf = sum(c.confidence for c in candidates[:10]) / min(len(candidates), 10)
        match_quality = avg_conf * 0.2

        confidence = keyword_signal + feature_signal + candidate_signal + match_quality
        return round(min(confidence, 1.0), 3)

    # ---------------------------------------------------------------
    # Internals
    # ---------------------------------------------------------------

    def _estimate_complexity(
        self,
        summary: RequirementSummary,
        candidates: list[RequirementCandidate],
        impacts: list[RequirementImpact],
    ) -> Complexity:
        n_files = len(candidates)
        n_impacts = len(impacts)
        n_features = len(summary.detected_features)
        n_sentences = len(summary.sentences)

        score = 0.0
        score += min(n_files, 20) * 1.0
        score += min(n_impacts, 15) * 1.5
        score += n_features * 2.0
        score += n_sentences * 0.5

        score += self._graph_complexity_bonus(candidates)

        if score >= 30:
            return Complexity.VERY_HIGH
        if score >= 18:
            return Complexity.HIGH
        if score >= 8:
            return Complexity.MEDIUM
        return Complexity.LOW

    def _graph_complexity_bonus(
        self, candidates: list[RequirementCandidate],
    ) -> float:
        """Graph-derived complexity: fan-in, fan-out, centrality, cross-module, depth."""
        if self._graph is None or not candidates:
            return 0.0

        total_fan_in = 0
        total_fan_out = 0
        max_depth = 0
        modules: set[str] = set()

        for cand in candidates[:15]:
            path = cand.path
            modules.add("/".join(path.replace("\\", "/").split("/")[:-1]) or "root")

            try:
                deps = self._graph.dependencies_of(path)
                fan_out = len(deps) if deps else 0
            except Exception:  # noqa: BLE001
                fan_out = 0
            try:
                rev = self._graph.reverse_dependencies(path)
                fan_in = len(rev) if rev else 0
            except Exception:  # noqa: BLE001
                fan_in = 0

            total_fan_in += fan_in
            total_fan_out += fan_out

            try:
                dist = self._graph.graph_distance(path, path, max_depth=5)
                if dist is not None:
                    max_depth = max(max_depth, dist)
            except Exception:  # noqa: BLE001
                pass

        bonus = 0.0

        avg_fan_in = total_fan_in / max(len(candidates[:15]), 1)
        avg_fan_out = total_fan_out / max(len(candidates[:15]), 1)
        bonus += min(avg_fan_in, 10) * 0.3
        bonus += min(avg_fan_out, 10) * 0.2

        n_modules = len(modules)
        if n_modules > 3:
            bonus += (n_modules - 3) * 1.5

        bonus += min(max_depth, 5) * 0.4

        return bonus

    def _estimate_risk(
        self,
        summary: RequirementSummary,
        impacts: list[RequirementImpact],
    ) -> RiskEstimate:
        keyword_set = set(summary.detected_keywords)
        risk_overlap = keyword_set & _RISK_KEYWORDS
        high_severity = sum(1 for i in impacts if i.severity == "high")

        risk_score = len(risk_overlap) * 3.0 + high_severity * 2.0

        if risk_score >= 12:
            return RiskEstimate.CRITICAL
        if risk_score >= 6:
            return RiskEstimate.HIGH
        if risk_score >= 3:
            return RiskEstimate.MEDIUM
        return RiskEstimate.LOW

    @staticmethod
    def _estimate_effort(complexity: Complexity) -> str:
        return {
            Complexity.LOW: "Small (hours)",
            Complexity.MEDIUM: "Medium (1-2 days)",
            Complexity.HIGH: "Large (3-5 days)",
            Complexity.VERY_HIGH: "Very large (1-2 weeks)",
        }[complexity]

    def _implementation_order(
        self,
        candidates: list[RequirementCandidate],
        tests: list[str],
        docs: list[str],
    ) -> list[str]:
        """Produce a topological-ish order: core layers first, then tests, docs."""

        def _layer_priority(path: str) -> int:
            stem = Path(path).stem.lower()
            parts = [p.lower() for p in Path(path).parts]
            for token, priority in _LAYER_PRIORITY.items():
                if token in stem or token in parts:
                    return priority
            return 5  # default middle-tier

        # Sort candidates by layer priority then confidence
        file_paths = [
            c.path for c in candidates
            if not _is_test_path(c.path) and not _is_demo_path(c.path)
        ]
        file_paths.sort(key=lambda p: (_layer_priority(p), p))

        order: list[str] = list(dict.fromkeys(file_paths))[:15]

        if tests:
            order.append("tests")
        if docs:
            order.append("documentation")

        return order


def _is_test_path(path: str) -> bool:
    parts = [p.lower() for p in Path(path).parts]
    stem = Path(path).stem.lower()
    return (
        any(t in parts for t in ("tests", "test", "spec", "specs"))
        or stem.startswith("test_")
        or stem.endswith("_test")
    )


def _is_demo_path(path: str) -> bool:
    parts = [p.lower() for p in Path(path).parts]
    stem = Path(path).stem.lower()
    return (
        stem.endswith("_demo")
        or stem.endswith("_example")
        or any(p in parts for p in ("examples", "demo", "demos"))
    )
