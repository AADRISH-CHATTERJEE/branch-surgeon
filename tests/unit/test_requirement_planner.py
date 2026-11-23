"""Tests for ImplementationPlanner — complexity, risk, confidence, order."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from refactory.core.logger import get_service_logger
from refactory.graph.service import RepositoryGraphService
from refactory.requirement.models import (
    Complexity,
    RequirementCandidate,
    RequirementImpact,
    RequirementSummary,
    RiskEstimate,
)
from refactory.requirement.planner import ImplementationPlanner


@pytest.fixture
def planner() -> ImplementationPlanner:
    return ImplementationPlanner(logger=get_service_logger("test.planner"))


def _summary(
    keywords: list[str] | None = None,
    features: list[str] | None = None,
    sentences: list[str] | None = None,
) -> RequirementSummary:
    return RequirementSummary(
        summary="Test requirement",
        detected_keywords=keywords or [],
        detected_features=features or [],
        sentences=sentences or ["Test requirement"],
    )


def _candidate(path: str, confidence: float = 0.8) -> RequirementCandidate:
    return RequirementCandidate(path=path, confidence=confidence, reasons=["test"])


def _impact(file: str, severity: str = "medium") -> RequirementImpact:
    return RequirementImpact(file=file, severity=severity, why="test")


# -------------------------------------------------------------------
# Complexity estimation
# -------------------------------------------------------------------

class TestComplexity:
    def test_low_complexity_few_files(self, planner: ImplementationPlanner):
        result = planner.plan(
            _summary(keywords=["auth"]),
            [_candidate("auth.py")],
            [],
            [],
            [],
        )
        assert result.estimated_complexity == Complexity.LOW

    def test_medium_complexity(self, planner: ImplementationPlanner):
        files = [_candidate(f"file{i}.py") for i in range(5)]
        impacts = [_impact(f"dep{i}.py") for i in range(3)]
        result = planner.plan(
            _summary(keywords=["auth"], features=["Authentication"]),
            files,
            impacts,
            ["test_auth.py"],
            [],
        )
        assert result.estimated_complexity == Complexity.MEDIUM

    def test_high_complexity_many_files(self, planner: ImplementationPlanner):
        files = [_candidate(f"file{i}.py") for i in range(12)]
        impacts = [_impact(f"dep{i}.py") for i in range(8)]
        features = ["Authentication", "Database", "API"]
        sentences = [f"Sentence {i}" for i in range(5)]
        result = planner.plan(
            _summary(keywords=["a", "b"], features=features, sentences=sentences),
            files,
            impacts,
            [],
            [],
        )
        assert result.estimated_complexity in {Complexity.HIGH, Complexity.VERY_HIGH}

    def test_very_high_complexity(self, planner: ImplementationPlanner):
        files = [_candidate(f"file{i}.py") for i in range(20)]
        impacts = [_impact(f"dep{i}.py") for i in range(15)]
        features = ["Authentication", "Database", "API", "Security", "Email"]
        sentences = [f"Sentence {i}" for i in range(10)]
        result = planner.plan(
            _summary(keywords=["a"], features=features, sentences=sentences),
            files,
            impacts,
            [],
            [],
        )
        assert result.estimated_complexity == Complexity.VERY_HIGH


# -------------------------------------------------------------------
# Risk estimation
# -------------------------------------------------------------------

class TestRisk:
    def test_low_risk_neutral_keywords(self, planner: ImplementationPlanner):
        result = planner.plan(
            _summary(keywords=["implement", "add"]),
            [_candidate("utils.py")],
            [],
            [],
            [],
        )
        assert result.estimated_risk == RiskEstimate.LOW

    def test_medium_risk_auth_keyword(self, planner: ImplementationPlanner):
        result = planner.plan(
            _summary(keywords=["auth"]),
            [_candidate("auth.py")],
            [],
            [],
            [],
        )
        assert result.estimated_risk == RiskEstimate.MEDIUM

    def test_high_risk_multiple_security_keywords(self, planner: ImplementationPlanner):
        result = planner.plan(
            _summary(keywords=["auth", "password", "encrypt"]),
            [],
            [],
            [],
            [],
        )
        assert result.estimated_risk in {RiskEstimate.HIGH, RiskEstimate.CRITICAL}

    def test_risk_increases_with_high_severity_impacts(self, planner: ImplementationPlanner):
        impacts = [_impact(f"f{i}.py", "high") for i in range(5)]
        result = planner.plan(
            _summary(keywords=["auth", "token"]),
            [],
            impacts,
            [],
            [],
        )
        assert result.estimated_risk in {RiskEstimate.HIGH, RiskEstimate.CRITICAL}


# -------------------------------------------------------------------
# Confidence estimation
# -------------------------------------------------------------------

class TestConfidence:
    def test_zero_confidence_no_keywords(self, planner: ImplementationPlanner):
        conf = planner.estimate_confidence(_summary(), [])
        assert conf == 0.0

    def test_low_confidence_no_candidates(self, planner: ImplementationPlanner):
        conf = planner.estimate_confidence(
            _summary(keywords=["auth"]),
            [],
        )
        assert conf <= 0.2

    def test_higher_confidence_with_candidates(self, planner: ImplementationPlanner):
        conf = planner.estimate_confidence(
            _summary(keywords=["auth", "login", "jwt", "token", "session"],
                     features=["Authentication", "Security", "API"]),
            [_candidate("auth.py", 0.9), _candidate("login.py", 0.8),
             _candidate("service.py", 0.7)],
        )
        assert conf >= 0.5

    def test_confidence_capped_at_1(self, planner: ImplementationPlanner):
        conf = planner.estimate_confidence(
            _summary(
                keywords=[f"kw{i}" for i in range(20)],
                features=[f"feat{i}" for i in range(10)],
            ),
            [_candidate(f"file{i}.py", 1.0) for i in range(20)],
        )
        assert conf <= 1.0

    def test_confidence_between_0_and_1(self, planner: ImplementationPlanner):
        conf = planner.estimate_confidence(
            _summary(keywords=["auth"]),
            [_candidate("auth.py")],
        )
        assert 0.0 <= conf <= 1.0


# -------------------------------------------------------------------
# Implementation order
# -------------------------------------------------------------------

class TestImplementationOrder:
    def test_auth_before_service(self, planner: ImplementationPlanner):
        result = planner.plan(
            _summary(keywords=["auth"]),
            [_candidate("service.py"), _candidate("auth.py")],
            [],
            [],
            [],
        )
        order = result.implementation_order
        if "auth.py" in order and "service.py" in order:
            assert order.index("auth.py") < order.index("service.py")

    def test_tests_come_last(self, planner: ImplementationPlanner):
        result = planner.plan(
            _summary(),
            [_candidate("auth.py")],
            [],
            ["tests/test_auth.py"],
            ["README.md"],
        )
        order = result.implementation_order
        assert "tests" in order
        assert "documentation" in order
        # tests and docs should be at the end
        assert order.index("tests") > order.index("auth.py")
        assert order.index("documentation") > order.index("auth.py")

    def test_empty_candidates(self, planner: ImplementationPlanner):
        result = planner.plan(
            _summary(),
            [],
            [],
            [],
            [],
        )
        assert result.implementation_order == []

    def test_test_files_excluded_from_main_order(self, planner: ImplementationPlanner):
        result = planner.plan(
            _summary(),
            [_candidate("auth.py"), _candidate("tests/test_auth.py")],
            [],
            ["tests/test_auth.py"],
            [],
        )
        prod_files = [
            s for s in result.implementation_order if s not in ("tests", "documentation")
        ]
        assert "tests/test_auth.py" not in prod_files

    def test_model_before_api(self, planner: ImplementationPlanner):
        result = planner.plan(
            _summary(),
            [
                _candidate("api/router.py"),
                _candidate("models/user.py"),
                _candidate("service.py"),
            ],
            [],
            [],
            [],
        )
        order = result.implementation_order
        if "models/user.py" in order and "api/router.py" in order:
            assert order.index("models/user.py") < order.index("api/router.py")


# -------------------------------------------------------------------
# Effort estimation
# -------------------------------------------------------------------

class TestEffort:
    def test_effort_strings(self, planner: ImplementationPlanner):
        for complexity in Complexity:
            result = planner.plan(
                _summary(), [], [], [], []
            )
            # Force complexity to test effort mapping
            effort = planner._estimate_effort(complexity)
            assert isinstance(effort, str)
            assert len(effort) > 0


# -------------------------------------------------------------------
# Demo/example filtering (Backlog 5)
# -------------------------------------------------------------------

class TestDemoExampleFiltering:
    def test_demo_files_excluded(self, planner: ImplementationPlanner):
        candidates = [
            _candidate("auth/service.py", 0.9),
            _candidate("auth_demo.py", 0.8),
        ]
        result = planner.plan(_summary(), candidates, [], [], [])
        assert "auth/service.py" in result.implementation_order
        assert "auth_demo.py" not in result.implementation_order

    def test_example_files_excluded(self, planner: ImplementationPlanner):
        candidates = [
            _candidate("auth/service.py", 0.9),
            _candidate("auth_example.py", 0.8),
        ]
        result = planner.plan(_summary(), candidates, [], [], [])
        assert "auth_example.py" not in result.implementation_order

    def test_examples_dir_excluded(self, planner: ImplementationPlanner):
        candidates = [
            _candidate("auth/service.py", 0.9),
            _candidate("examples/login_flow.py", 0.8),
        ]
        result = planner.plan(_summary(), candidates, [], [], [])
        assert "examples/login_flow.py" not in result.implementation_order

    def test_demo_dir_excluded(self, planner: ImplementationPlanner):
        candidates = [
            _candidate("auth/service.py", 0.9),
            _candidate("demo/showcase.py", 0.8),
        ]
        result = planner.plan(_summary(), candidates, [], [], [])
        assert "demo/showcase.py" not in result.implementation_order

    def test_production_files_remain(self, planner: ImplementationPlanner):
        candidates = [
            _candidate("auth/service.py", 0.9),
            _candidate("config/settings.py", 0.8),
            _candidate("examples/demo.py", 0.7),
            _candidate("tests/test_auth.py", 0.6),
        ]
        result = planner.plan(_summary(), candidates, [], [], [])
        assert "auth/service.py" in result.implementation_order
        assert "config/settings.py" in result.implementation_order
        assert "examples/demo.py" not in result.implementation_order
        assert "tests/test_auth.py" not in result.implementation_order


# -------------------------------------------------------------------
# Graph-derived complexity (Backlog 3)
# -------------------------------------------------------------------

class TestGraphComplexity:
    def test_graph_increases_complexity(self):
        graph = MagicMock(spec=RepositoryGraphService)
        graph.dependencies_of.return_value = ["b.py", "c.py", "d.py", "e.py"]
        graph.reverse_dependencies.return_value = ["x.py", "y.py", "z.py"]
        graph.graph_distance.return_value = None
        planner_with_graph = ImplementationPlanner(
            logger=get_service_logger("test.planner"),
            graph_service=graph,
        )
        planner_no_graph = ImplementationPlanner(
            logger=get_service_logger("test.planner"),
        )
        summary = _summary(keywords=["auth", "token", "session"])
        candidates = [
            _candidate("pkg_a/service.py", 0.9),
            _candidate("pkg_b/handler.py", 0.8),
            _candidate("pkg_c/model.py", 0.7),
            _candidate("pkg_d/util.py", 0.6),
        ]
        impacts = [RequirementImpact(file="a.py", severity="high")]

        c_graph = planner_with_graph._estimate_complexity(summary, candidates, impacts)
        c_none = planner_no_graph._estimate_complexity(summary, candidates, impacts)

        complexity_rank = {Complexity.LOW: 0, Complexity.MEDIUM: 1,
                          Complexity.HIGH: 2, Complexity.VERY_HIGH: 3}
        assert complexity_rank[c_graph] >= complexity_rank[c_none]

    def test_no_graph_same_as_before(self):
        planner = ImplementationPlanner(
            logger=get_service_logger("test.planner"),
        )
        summary = _summary(keywords=["cache"])
        candidates = [_candidate("cache.py", 0.9)]
        c = planner._estimate_complexity(summary, candidates, [])
        assert c in (Complexity.LOW, Complexity.MEDIUM)

    def test_cross_module_penalty(self):
        graph = MagicMock(spec=RepositoryGraphService)
        graph.dependencies_of.return_value = ["x.py"]
        graph.reverse_dependencies.return_value = ["y.py"]
        graph.graph_distance.return_value = 2
        planner = ImplementationPlanner(
            logger=get_service_logger("test.planner"),
            graph_service=graph,
        )
        candidates = [
            _candidate("a/s1.py", 0.9),
            _candidate("b/s2.py", 0.8),
            _candidate("c/s3.py", 0.7),
            _candidate("d/s4.py", 0.6),
        ]
        bonus = planner._graph_complexity_bonus(candidates)
        assert bonus > 0
