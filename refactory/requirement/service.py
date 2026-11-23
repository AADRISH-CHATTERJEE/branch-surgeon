"""RequirementAnalysisService — top-level orchestrator.

Wires RequirementParser, RequirementSearch, ImplementationPlanner, and
existing services (ImpactAnalysisService, TestIntelligenceService,
DocumentationService). No AI. No network. No GitHub. No Jira.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from refactory.documentation.service import DocumentationService
from refactory.impact.service import ImpactAnalysisService
from refactory.requirement.models import (
    RequirementAnalysis,
    RequirementCandidate,
    RequirementImpact,
    RequirementRequest,
)
from refactory.requirement.parser import RequirementParser
from refactory.requirement.planner import ImplementationPlanner
from refactory.requirement.search import RequirementSearch
from refactory.testing.service import TestIntelligenceService

if TYPE_CHECKING:
    from loguru import Logger

# File-path tokens indicating config / database files
_CONFIG_TOKENS = frozenset({
    "config", "settings", "env", "dotenv", "configuration",
    "yaml", "toml", "json", "ini", "properties",
})
_DATABASE_TOKENS = frozenset({
    "migration", "migrations", "schema", "model", "models",
    "database", "db", "orm", "entity", "dao", "repository",
    "alembic",
})


class RequirementAnalysisService:
    """Analyze a plain-English requirement against the local repository.

    Orchestrates existing services — never duplicates graph traversal,
    search, or impact logic.
    """

    def __init__(
        self,
        logger: "Logger",
        parser: RequirementParser,
        search: RequirementSearch,
        planner: ImplementationPlanner,
        impact_service: ImpactAnalysisService,
        testing_service: TestIntelligenceService,
        documentation_service: DocumentationService,
    ) -> None:
        self._logger = logger
        self._parser = parser
        self._search = search
        self._planner = planner
        self._impact = impact_service
        self._testing = testing_service
        self._docs = documentation_service

    def analyze(self, request: RequirementRequest) -> RequirementAnalysis:
        """Run the full analysis pipeline for a raw requirement."""
        self._logger.info("Requirement analysis starting")

        # 1. Parse
        summary = self._parser.parse(request.raw_text)
        if not summary.detected_keywords:
            self._logger.info("No keywords detected — returning minimal analysis")
            return RequirementAnalysis(
                summary=summary.summary or request.raw_text[:200],
                notes=["No technical keywords detected in the requirement text."],
            )

        # 2. Search for candidate files
        candidates = self._search.find_candidates(summary)

        # 3. Expand impact via ImpactAnalysisService
        include_full_test = self._wants_full_test_impact(request.raw_text)
        impacts = self._expand_impact(
            candidates, include_full_test_impact=include_full_test,
        )

        # 4. Find affected tests
        impacted_tests = self._find_affected_tests(candidates)

        # 5. Find affected documentation
        impacted_docs = self._find_affected_docs(candidates)

        # 6. Classify config / database files
        config_files = self._classify_config(candidates)
        db_files = self._classify_database(candidates)

        # 7. Plan
        plan = self._planner.plan(
            summary, candidates, impacts, impacted_tests, impacted_docs
        )
        confidence = self._planner.estimate_confidence(summary, candidates)

        notes: list[str] = []
        if not candidates:
            notes.append(
                "No candidate files found. The repository may not contain "
                "code related to this requirement."
            )

        analysis = RequirementAnalysis(
            summary=summary.summary,
            features=summary.detected_features,
            keywords=summary.detected_keywords,
            candidate_files=candidates,
            impacted_files=impacts,
            impacted_tests=impacted_tests,
            impacted_docs=impacted_docs,
            configuration_files=config_files,
            database_files=db_files,
            complexity=plan.estimated_complexity,
            risk=plan.estimated_risk,
            confidence=confidence,
            implementation_plan=plan.implementation_order,
            notes=notes,
        )

        self._logger.info(
            "Requirement analysis complete — {} candidate(s), confidence={:.2f}",
            len(candidates),
            confidence,
        )
        return analysis

    # ---------------------------------------------------------------
    # Impact expansion
    # ---------------------------------------------------------------

    def _expand_impact(
        self,
        candidates: list[RequirementCandidate],
        *,
        include_full_test_impact: bool = False,
    ) -> list[RequirementImpact]:
        """Use ImpactAnalysisService to find blast radius for top candidates."""
        seen: set[str] = set()
        impacts: list[RequirementImpact] = []

        for candidate in candidates[:10]:
            try:
                report = self._impact.analyze(candidate.path)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("Impact skipped for {}: {}", candidate.path, exc)
                continue

            severity = report.risk_level.value
            severity = self._cap_test_severity(
                candidate.path, severity, include_full_test_impact,
            )
            if candidate.path not in seen:
                seen.add(candidate.path)
                impacts.append(
                    RequirementImpact(
                        file=candidate.path,
                        severity=severity,
                        why=f"Direct candidate ({len(report.direct_impact)} dependent(s))",
                    )
                )

            for loc in report.direct_impact[:5]:
                if loc.path not in seen:
                    seen.add(loc.path)
                    dep_sev = self._cap_test_severity(
                        loc.path, "medium", include_full_test_impact,
                    )
                    impacts.append(
                        RequirementImpact(
                            file=loc.path,
                            severity=dep_sev,
                            why=f"Depends on {candidate.path}",
                        )
                    )

        return impacts

    @staticmethod
    def _cap_test_severity(
        path: str, severity: str, include_full: bool,
    ) -> str:
        """Cap test file severity at MEDIUM unless full test impact requested."""
        if include_full:
            return severity
        if _is_test_path(path) and severity == "high":
            return "medium"
        return severity

    # ---------------------------------------------------------------
    # Test discovery
    # ---------------------------------------------------------------

    def _find_affected_tests(
        self, candidates: list[RequirementCandidate]
    ) -> list[str]:
        seen: set[str] = set()
        tests: list[str] = []
        for candidate in candidates[:15]:
            try:
                report = self._testing.find_related_tests(candidate.path)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("Test lookup skipped for {}: {}", candidate.path, exc)
                continue
            for match in report.tests:
                if match.path not in seen:
                    seen.add(match.path)
                    tests.append(match.path)
        return tests

    # ---------------------------------------------------------------
    # Documentation discovery
    # ---------------------------------------------------------------

    def _find_affected_docs(
        self, candidates: list[RequirementCandidate]
    ) -> list[str]:
        docs: list[str] = []
        try:
            stale = self._docs.find_stale_documentation()
            candidate_paths = {c.path for c in candidates}
            for item in stale:
                src = item.related_source or ""
                if src in candidate_paths and item.path not in docs:
                    docs.append(item.path)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("Doc lookup skipped: {}", exc)

        try:
            missing = self._docs.find_missing_readmes()
            candidate_dirs = {
                str(Path(c.path).parent).replace("\\", "/") for c in candidates
            }
            for gap in missing:
                gap_dir = str(Path(gap.path).parent).replace("\\", "/")
                if gap_dir in candidate_dirs and gap.path not in docs:
                    docs.append(gap.path)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("Missing-readme lookup skipped: {}", exc)

        return docs

    # ---------------------------------------------------------------
    # File classification
    # ---------------------------------------------------------------

    @staticmethod
    def _wants_full_test_impact(raw_text: str) -> bool:
        """Check if user explicitly requested full test impact analysis."""
        lower = raw_text.lower()
        return (
            "include test impact" in lower
            or "full impact" in lower
            or "full test impact" in lower
        )

    @staticmethod
    def _classify_config(candidates: list[RequirementCandidate]) -> list[str]:
        result: list[str] = []
        for c in candidates:
            stem = Path(c.path).stem.lower()
            parts = [p.lower() for p in Path(c.path).parts]
            if any(tok in stem or tok in parts for tok in _CONFIG_TOKENS):
                result.append(c.path)
        return result

    @staticmethod
    def _classify_database(candidates: list[RequirementCandidate]) -> list[str]:
        result: list[str] = []
        for c in candidates:
            stem = Path(c.path).stem.lower()
            parts = [p.lower() for p in Path(c.path).parts]
            if any(tok in stem or tok in parts for tok in _DATABASE_TOKENS):
                result.append(c.path)
        return result


def _is_test_path(path: str) -> bool:
    parts = [p.lower() for p in Path(path).parts]
    stem = Path(path).stem.lower()
    return (
        any(t in parts for t in ("tests", "test", "spec", "specs"))
        or stem.startswith("test_")
        or stem.endswith("_test")
    )
