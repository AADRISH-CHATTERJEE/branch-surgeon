"""CLI presentation tests for test intelligence commands."""

from __future__ import annotations

from unittest.mock import MagicMock

from typer.testing import CliRunner

from refactory.cli.app import app
from refactory.testing.models import (
    DuplicateTestGroup,
    ProductionCoverage,
    RelatedTestsReport,
    TestCoverageMap,
    TestFramework,
    TestImpactReport,
    TestMatch,
    TestRiskLevel,
)

runner = CliRunner()


def test_tests_command(mocker):
    service = MagicMock()
    service.find_related_tests.return_value = RelatedTestsReport(
        target="auth.py",
        tests=[
            TestMatch(
                path="tests/test_auth.py",
                symbol="test_validate_token",
                framework=TestFramework.PYTEST,
                confidence=0.92,
                reasons=["imports"],
            )
        ],
        coverage_confidence=0.92,
        framework_hint=TestFramework.PYTEST,
    )
    container = MagicMock()
    container.test_intelligence_service = service
    mocker.patch("refactory.cli.commands.tests_cmd.get_container", return_value=container)

    result = runner.invoke(app, ["tests", "auth.py"])
    assert result.exit_code == 0, result.output
    service.find_related_tests.assert_called_once_with("auth.py")
    assert "tests/test_auth.py" in result.output
    assert "Related Tests" in result.output


def test_tests_command_with_impact(mocker):
    service = MagicMock()
    service.find_related_tests.return_value = RelatedTestsReport(
        target="User",
        tests=[TestMatch(path="tests/unit/test_user.py", confidence=0.8, reasons=["imports"])],
        coverage_confidence=0.8,
    )
    service.estimate_test_impact.return_value = TestImpactReport(
        target="User",
        recommended_tests=[TestMatch(path="tests/unit/test_user.py", confidence=0.8)],
        coverage_confidence=0.8,
        risk_if_skipped=TestRiskLevel.MEDIUM,
        missing_critical_tests=["payments.py"],
    )
    container = MagicMock()
    container.test_intelligence_service = service
    mocker.patch("refactory.cli.commands.tests_cmd.get_container", return_value=container)

    result = runner.invoke(app, ["tests", "User", "--impact"])
    assert result.exit_code == 0, result.output
    assert "Risk if skipped" in result.output
    assert "MEDIUM" in result.output


def test_uncovered_command(mocker):
    service = MagicMock()
    service.compute_test_coverage_map.return_value = TestCoverageMap(
        uncovered_files=["payments.py"],
        uncovered_classes=["payments.py::Charge"],
        uncovered_functions=["payments.py::charge"],
        coverage_ratio=0.5,
    )
    container = MagicMock()
    container.test_intelligence_service = service
    mocker.patch("refactory.cli.commands.uncovered.get_container", return_value=container)

    result = runner.invoke(app, ["uncovered"])
    assert result.exit_code == 0, result.output
    assert "payments.py" in result.output


def test_orphan_tests_command(mocker):
    service = MagicMock()
    service.find_orphan_tests.return_value = [
        TestMatch(path="tests/test_orphan.py", confidence=0.75, reasons=["no_production_links"])
    ]
    container = MagicMock()
    container.test_intelligence_service = service
    mocker.patch("refactory.cli.commands.orphan_tests.get_container", return_value=container)

    result = runner.invoke(app, ["orphan-tests"])
    assert result.exit_code == 0, result.output
    assert "tests/test_orphan.py" in result.output


def test_duplicate_tests_command(mocker):
    service = MagicMock()
    service.find_duplicate_tests.return_value = [
        DuplicateTestGroup(
            key="name:test_validate_token",
            tests=[
                TestMatch(path="tests/test_auth.py", symbol="test_validate_token"),
                TestMatch(path="tests/nested/deep/test_auth.py", symbol="test_validate_token"),
            ],
            confidence=0.7,
        )
    ]
    container = MagicMock()
    container.test_intelligence_service = service
    mocker.patch("refactory.cli.commands.duplicate_tests.get_container", return_value=container)

    result = runner.invoke(app, ["duplicate-tests"])
    assert result.exit_code == 0, result.output
    assert "test_validate_token" in result.output


def test_coverage_map_command(mocker):
    service = MagicMock()
    service.compute_test_coverage_map.return_value = TestCoverageMap(
        production_files=[
            ProductionCoverage(
                path="auth.py",
                covered=True,
                coverage_confidence=0.9,
                tests=[TestMatch(path="tests/test_auth.py", confidence=0.9)],
            )
        ],
        test_files=["tests/test_auth.py"],
        coverage_ratio=1.0,
    )
    container = MagicMock()
    container.test_intelligence_service = service
    mocker.patch("refactory.cli.commands.coverage_map.get_container", return_value=container)

    result = runner.invoke(app, ["coverage-map"])
    assert result.exit_code == 0, result.output
    assert "Coverage Map" in result.output
    assert "auth.py" in result.output
    # Windows cp1252 consoles cannot encode Unicode arrows (←).
    assert "<-" in result.output
    assert "\u2190" not in result.output


def test_help_lists_test_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("tests", "uncovered", "orphan-tests", "duplicate-tests", "coverage-map"):
        assert name in result.output
