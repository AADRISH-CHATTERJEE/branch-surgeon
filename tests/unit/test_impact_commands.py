"""CLI / DI presentation tests for impact analysis."""

from __future__ import annotations

from unittest.mock import MagicMock

from typer.testing import CliRunner

from refactory.cli.app import app
from refactory.impact.models import (
    DependencyChain,
    ImpactedLocation,
    ImpactReport,
    ImpactTargetKind,
    RiskLevel,
)

runner = CliRunner()


def test_impact_command_renders_sections(mocker):
    report = ImpactReport(
        target="auth.py",
        target_kind=ImpactTargetKind.FILE,
        resolved_paths=["auth.py"],
        direct_impact=[
            ImpactedLocation(
                path="login.py",
                confidence=0.9,
                reasons=["imported_by"],
                kind="direct",
            )
        ],
        indirect_impact=[
            ImpactedLocation(
                path="service.py",
                confidence=0.7,
                reasons=["transitive_impact"],
                kind="indirect",
            )
        ],
        dependency_chains=[
            DependencyChain(nodes=["auth.py", "login.py"], relationship="imported_by")
        ],
        impacted_files=["auth.py", "login.py", "service.py"],
        impacted_symbols=["validate_token"],
        risk_level=RiskLevel.MEDIUM,
        confidence=0.82,
    )
    service = MagicMock()
    service.analyze.return_value = report
    container = MagicMock()
    container.impact_analysis_service = service
    mocker.patch("refactory.cli.commands.impact.get_container", return_value=container)

    result = runner.invoke(app, ["impact", "auth.py"])
    assert result.exit_code == 0, result.output
    service.analyze.assert_called_once_with("auth.py")
    assert "Direct Impact" in result.output
    assert "Indirect Impact" in result.output
    assert "Risk Level" in result.output
    assert "MEDIUM" in result.output
    assert "Dependency Chain" in result.output
    assert "login.py" in result.output
    assert "Confidence" in result.output


def test_impact_symbol_cli(mocker):
    service = MagicMock()
    service.analyze.return_value = ImpactReport(
        target="validate_token",
        target_kind=ImpactTargetKind.FUNCTION,
        resolved_paths=["auth.py"],
        resolved_symbols=["validate_token"],
        confidence=0.7,
        risk_level=RiskLevel.LOW,
    )
    container = MagicMock()
    container.impact_analysis_service = service
    mocker.patch("refactory.cli.commands.impact.get_container", return_value=container)

    result = runner.invoke(app, ["impact", "validate_token"])
    assert result.exit_code == 0, result.output
    assert "validate_token" in result.output


def test_help_lists_impact():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "impact" in result.output
