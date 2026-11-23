"""Tests for RequirementAnalysisService — end-to-end orchestration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from refactory.codesearch.models import CodeSearchHit, CodeSearchResult
from refactory.codesearch.service import CodeSearchService
from refactory.core.logger import get_service_logger
from refactory.documentation.models import DocGap, StaleDoc
from refactory.documentation.service import DocumentationService
from refactory.graph.service import RepositoryGraphService
from refactory.impact.models import ImpactedLocation, ImpactReport, RiskLevel
from refactory.impact.service import ImpactAnalysisService
from refactory.requirement.models import (
    Complexity,
    RequirementAnalysis,
    RequirementRequest,
    RiskEstimate,
)
from refactory.requirement.parser import RequirementParser
from refactory.requirement.planner import ImplementationPlanner
from refactory.requirement.search import RequirementSearch
from refactory.requirement.service import RequirementAnalysisService
from refactory.retrieval.service import RetrievalService
from refactory.testing.models import RelatedTestsReport, TestMatch
from refactory.testing.service import TestIntelligenceService


def _logger(name: str = "test.req"):
    return get_service_logger(name)


def _search_hit(file: str, score: float = 0.8) -> CodeSearchHit:
    return CodeSearchHit(file=file, score=score, reasons=["test"])


def _search_result(hits: list[CodeSearchHit] | None = None) -> CodeSearchResult:
    return CodeSearchResult(query="test", hits=hits or [])


def _impact_report(
    target: str = "auth.py",
    risk: RiskLevel = RiskLevel.MEDIUM,
    direct: list[str] | None = None,
) -> ImpactReport:
    locs = [ImpactedLocation(path=p) for p in (direct or [])]
    return ImpactReport(
        target=target,
        risk_level=risk,
        direct_impact=locs,
    )


def _test_report(target: str, tests: list[str] | None = None) -> RelatedTestsReport:
    matches = [TestMatch(path=t, confidence=0.8) for t in (tests or [])]
    return RelatedTestsReport(target=target, tests=matches)


def _make_service(
    *,
    search_hits: list[CodeSearchHit] | None = None,
    impact_reports: dict[str, ImpactReport] | None = None,
    test_reports: dict[str, RelatedTestsReport] | None = None,
    stale_docs: list[StaleDoc] | None = None,
    missing_readmes: list[DocGap] | None = None,
) -> RequirementAnalysisService:
    code_search = MagicMock(spec=CodeSearchService)
    code_search.search.return_value = _search_result(search_hits or [])
    code_search.search_files.return_value = _search_result()

    graph_service = MagicMock(spec=RepositoryGraphService)
    graph_service.dependencies_of.return_value = []
    graph_service.reverse_dependencies.return_value = []

    retrieval = MagicMock(spec=RetrievalService)

    impact = MagicMock(spec=ImpactAnalysisService)
    if impact_reports:
        def _analyze(target: str):
            if target in impact_reports:
                return impact_reports[target]
            return _impact_report(target)
        impact.analyze.side_effect = _analyze
    else:
        impact.analyze.return_value = _impact_report()

    testing = MagicMock(spec=TestIntelligenceService)
    if test_reports:
        def _find_tests(target: str):
            if target in test_reports:
                return test_reports[target]
            return _test_report(target)
        testing.find_related_tests.side_effect = _find_tests
    else:
        testing.find_related_tests.return_value = _test_report("x")

    docs = MagicMock(spec=DocumentationService)
    docs.find_stale_documentation.return_value = stale_docs or []
    docs.find_missing_readmes.return_value = missing_readmes or []

    parser = RequirementParser()
    search = RequirementSearch(
        logger=_logger("test.req.search"),
        code_search_service=code_search,
        graph_service=graph_service,
        retrieval_service=retrieval,
    )
    planner = ImplementationPlanner(logger=_logger("test.req.planner"))

    return RequirementAnalysisService(
        logger=_logger(),
        parser=parser,
        search=search,
        planner=planner,
        impact_service=impact,
        testing_service=testing,
        documentation_service=docs,
    )


# -------------------------------------------------------------------
# Empty / minimal
# -------------------------------------------------------------------

class TestEmptyInput:
    def test_empty_requirement(self):
        svc = _make_service()
        result = svc.analyze(RequirementRequest(raw_text=""))
        assert result.confidence == 0.0
        assert result.candidate_files == []

    def test_non_technical_requirement(self):
        svc = _make_service()
        result = svc.analyze(RequirementRequest(raw_text="The weather is nice today."))
        assert "No technical keywords" in result.notes[0]

    def test_whitespace_requirement(self):
        svc = _make_service()
        result = svc.analyze(RequirementRequest(raw_text="   \n\n  "))
        assert result.candidate_files == []


# -------------------------------------------------------------------
# Auth requirement
# -------------------------------------------------------------------

class TestAuthRequirement:
    def test_detects_auth_features(self):
        svc = _make_service(
            search_hits=[_search_hit("auth.py", 0.9)]
        )
        result = svc.analyze(
            RequirementRequest(raw_text="Implement JWT authentication with token refresh.")
        )
        assert "Authentication" in result.features
        assert any(c.path == "auth.py" for c in result.candidate_files)

    def test_password_reset_scenario(self):
        svc = _make_service(
            search_hits=[
                _search_hit("auth.py", 0.9),
                _search_hit("service.py", 0.7),
            ],
            impact_reports={
                "auth.py": _impact_report("auth.py", RiskLevel.HIGH, ["login.py", "service.py"]),
            },
            test_reports={
                "auth.py": _test_report("auth.py", ["tests/test_auth.py"]),
            },
        )
        result = svc.analyze(
            RequirementRequest(raw_text=(
                "Implement password reset. "
                "Users should receive a reset email. "
                "Tokens expire after 15 minutes."
            ))
        )
        assert "Authentication" in result.features
        assert "Email" in result.features
        assert any(c.path == "auth.py" for c in result.candidate_files)
        assert any(t == "tests/test_auth.py" for t in result.impacted_tests)

    def test_auth_requirement_has_medium_or_higher_risk(self):
        svc = _make_service(
            search_hits=[_search_hit("auth.py")]
        )
        result = svc.analyze(
            RequirementRequest(raw_text="Add authentication and password validation.")
        )
        assert result.risk in {RiskEstimate.MEDIUM, RiskEstimate.HIGH, RiskEstimate.CRITICAL}


# -------------------------------------------------------------------
# Database requirement
# -------------------------------------------------------------------

class TestDatabaseRequirement:
    def test_detects_database_features(self):
        svc = _make_service(
            search_hits=[_search_hit("models/user.py")]
        )
        result = svc.analyze(
            RequirementRequest(raw_text="Add database migration for user schema.")
        )
        assert "Database" in result.features

    def test_database_files_classified(self):
        svc = _make_service(
            search_hits=[
                _search_hit("models/user.py", 0.9),
                _search_hit("migrations/001_users.py", 0.8),
            ]
        )
        result = svc.analyze(
            RequirementRequest(raw_text="Create database schema for users.")
        )
        assert any("model" in f.lower() or "migration" in f.lower() for f in result.database_files)


# -------------------------------------------------------------------
# API requirement
# -------------------------------------------------------------------

class TestAPIRequirement:
    def test_detects_api_features(self):
        svc = _make_service(
            search_hits=[_search_hit("api/router.py")]
        )
        result = svc.analyze(
            RequirementRequest(raw_text="Create a REST API endpoint for users.")
        )
        assert "API" in result.features


# -------------------------------------------------------------------
# Security requirement
# -------------------------------------------------------------------

class TestSecurityRequirement:
    def test_detects_security_features(self):
        svc = _make_service(
            search_hits=[_search_hit("security.py")]
        )
        result = svc.analyze(
            RequirementRequest(raw_text="Encrypt all passwords and prevent XSS attacks.")
        )
        assert "Security" in result.features
        assert result.risk in {RiskEstimate.MEDIUM, RiskEstimate.HIGH, RiskEstimate.CRITICAL}


# -------------------------------------------------------------------
# Documentation impact
# -------------------------------------------------------------------

class TestDocumentationImpact:
    def test_stale_docs_included(self):
        svc = _make_service(
            search_hits=[_search_hit("auth.py")],
            stale_docs=[StaleDoc(path="README.md", related_source="auth.py")],
        )
        result = svc.analyze(
            RequirementRequest(raw_text="Update authentication logic.")
        )
        assert "README.md" in result.impacted_docs

    def test_docs_failure_handled(self):
        svc = _make_service(search_hits=[_search_hit("auth.py")])
        # Override to raise
        svc._docs.find_stale_documentation.side_effect = RuntimeError("fail")
        svc._docs.find_missing_readmes.side_effect = RuntimeError("fail")
        result = svc.analyze(
            RequirementRequest(raw_text="Update authentication.")
        )
        assert isinstance(result, RequirementAnalysis)


# -------------------------------------------------------------------
# Configuration files
# -------------------------------------------------------------------

class TestConfigFiles:
    def test_config_files_classified(self):
        svc = _make_service(
            search_hits=[
                _search_hit("config/settings.py", 0.9),
                _search_hit("auth.py", 0.8),
            ]
        )
        result = svc.analyze(
            RequirementRequest(raw_text="Update settings for authentication.")
        )
        assert any("config" in f.lower() or "settings" in f.lower()
                    for f in result.configuration_files)


# -------------------------------------------------------------------
# Impact expansion
# -------------------------------------------------------------------

class TestImpactExpansion:
    def test_impact_service_called_for_candidates(self):
        impact_mock = MagicMock(spec=ImpactAnalysisService)
        impact_mock.analyze.return_value = _impact_report(
            "auth.py", RiskLevel.HIGH, ["login.py"]
        )

        svc = _make_service(
            search_hits=[_search_hit("auth.py")],
        )
        svc._impact = impact_mock

        result = svc.analyze(
            RequirementRequest(raw_text="Add authentication.")
        )
        assert impact_mock.analyze.called
        assert any(i.file == "auth.py" for i in result.impacted_files)

    def test_impact_failure_handled(self):
        impact_mock = MagicMock(spec=ImpactAnalysisService)
        impact_mock.analyze.side_effect = RuntimeError("analysis failed")

        svc = _make_service(search_hits=[_search_hit("auth.py")])
        svc._impact = impact_mock

        result = svc.analyze(
            RequirementRequest(raw_text="Add authentication.")
        )
        assert isinstance(result, RequirementAnalysis)


# -------------------------------------------------------------------
# Test discovery
# -------------------------------------------------------------------

class TestTestDiscovery:
    def test_tests_found_for_candidates(self):
        svc = _make_service(
            search_hits=[_search_hit("auth.py")],
            test_reports={"auth.py": _test_report("auth.py", ["tests/test_auth.py"])},
        )
        result = svc.analyze(
            RequirementRequest(raw_text="Update authentication.")
        )
        assert "tests/test_auth.py" in result.impacted_tests

    def test_test_failure_handled(self):
        testing = MagicMock(spec=TestIntelligenceService)
        testing.find_related_tests.side_effect = RuntimeError("fail")

        svc = _make_service(search_hits=[_search_hit("auth.py")])
        svc._testing = testing

        result = svc.analyze(
            RequirementRequest(raw_text="Update auth.")
        )
        assert isinstance(result, RequirementAnalysis)


# -------------------------------------------------------------------
# JSON serialization
# -------------------------------------------------------------------

class TestSerialization:
    def test_json_output(self):
        svc = _make_service(search_hits=[_search_hit("auth.py")])
        result = svc.analyze(
            RequirementRequest(raw_text="Add authentication.")
        )
        json_str = result.model_dump_json()
        assert "auth.py" in json_str or "Authentication" in json_str

    def test_model_defaults(self):
        analysis = RequirementAnalysis()
        assert analysis.complexity == Complexity.MEDIUM
        assert analysis.risk == RiskEstimate.MEDIUM
        assert analysis.confidence == 0.0


# -------------------------------------------------------------------
# Edge cases
# -------------------------------------------------------------------

class TestEdgeCases:
    def test_single_keyword_requirement(self):
        svc = _make_service(search_hits=[_search_hit("auth.py")])
        result = svc.analyze(RequirementRequest(raw_text="login"))
        assert len(result.features) > 0

    def test_very_large_requirement(self):
        text = " ".join(
            [f"Implement feature {i} with authentication and database migration." for i in range(100)]
        )
        svc = _make_service(search_hits=[_search_hit("auth.py")])
        result = svc.analyze(RequirementRequest(raw_text=text))
        assert isinstance(result, RequirementAnalysis)

    def test_documentation_only_requirement(self):
        svc = _make_service()
        result = svc.analyze(
            RequirementRequest(raw_text="Update the project README with deployment instructions.")
        )
        assert isinstance(result, RequirementAnalysis)

    def test_unknown_domain_requirement(self):
        svc = _make_service()
        result = svc.analyze(
            RequirementRequest(raw_text="Optimize the rendering pipeline for the particle system.")
        )
        assert isinstance(result, RequirementAnalysis)
        # Low or no confidence when nothing matches
        assert result.confidence <= 0.5

    def test_requirement_with_file_hints(self):
        svc = _make_service(
            search_hits=[_search_hit("auth.py")],
        )
        result = svc.analyze(
            RequirementRequest(raw_text="Modify auth.py to add password reset.")
        )
        assert any(c.path == "auth.py" for c in result.candidate_files)

    def test_mixed_casing_requirement(self):
        svc = _make_service(search_hits=[_search_hit("auth.py")])
        result = svc.analyze(
            RequirementRequest(raw_text="JWT AUTHENTICATION with OAuth2 TOKEN REFRESH")
        )
        assert "Authentication" in result.features

    def test_repository_without_embeddings(self):
        svc = _make_service(search_hits=[_search_hit("auth.py")])
        result = svc.analyze(
            RequirementRequest(raw_text="Add authentication.")
        )
        assert isinstance(result, RequirementAnalysis)

    def test_implementation_plan_present(self):
        svc = _make_service(
            search_hits=[
                _search_hit("auth.py", 0.9),
                _search_hit("service.py", 0.7),
            ]
        )
        result = svc.analyze(
            RequirementRequest(raw_text="Add token authentication to the service.")
        )
        assert len(result.implementation_plan) > 0


# -------------------------------------------------------------------
# Impact severity capping (Backlog 6)
# -------------------------------------------------------------------


class TestImpactSeverityCapping:
    """Test files should be capped at MEDIUM severity by default."""

    def test_test_file_capped_at_medium(self):
        svc = _make_service(
            search_hits=[_search_hit("tests/conftest.py", 0.9)],
            impact_reports={
                "tests/conftest.py": _impact_report(
                    target="tests/conftest.py",
                    risk=RiskLevel.HIGH,
                ),
            },
        )
        result = svc.analyze(
            RequirementRequest(raw_text="Add authentication.")
        )
        test_impacts = [
            i for i in result.impacted_files
            if "test" in i.file.lower() or "conftest" in i.file.lower()
        ]
        for impact in test_impacts:
            assert impact.severity != "high", f"Test file {impact.file} got HIGH severity"

    def test_production_file_keeps_high(self):
        svc = _make_service(
            search_hits=[_search_hit("auth.py", 0.9)],
            impact_reports={
                "auth.py": _impact_report(
                    target="auth.py",
                    risk=RiskLevel.HIGH,
                ),
            },
        )
        result = svc.analyze(
            RequirementRequest(raw_text="Add authentication.")
        )
        prod_impacts = [
            i for i in result.impacted_files if i.file == "auth.py"
        ]
        assert any(i.severity == "high" for i in prod_impacts)

    def test_full_impact_request_uncaps(self):
        svc = _make_service(
            search_hits=[_search_hit("tests/conftest.py", 0.9)],
            impact_reports={
                "tests/conftest.py": _impact_report(
                    target="tests/conftest.py",
                    risk=RiskLevel.HIGH,
                ),
            },
        )
        result = svc.analyze(
            RequirementRequest(
                raw_text="Add authentication. Include test impact."
            )
        )
        test_impacts = [
            i for i in result.impacted_files
            if "test" in i.file.lower() or "conftest" in i.file.lower()
        ]
        assert any(i.severity == "high" for i in test_impacts)

    def test_full_impact_phrase_detected(self):
        from refactory.requirement.service import RequirementAnalysisService
        assert RequirementAnalysisService._wants_full_test_impact("full impact analysis")
        assert RequirementAnalysisService._wants_full_test_impact("include test impact")
        assert not RequirementAnalysisService._wants_full_test_impact("add login")
