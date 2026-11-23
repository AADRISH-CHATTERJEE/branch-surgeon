"""Unit tests for Rich review report helpers."""

from __future__ import annotations

from refactory.cli.ui.style import format_cache_hit, format_cost_usd, format_ms, severity_style


def test_severity_and_format_helpers():
    assert "red" in severity_style("high")
    assert format_cache_hit(True) == "[green]hit[/green]"
    assert format_cache_hit(False) == "[dim]miss[/dim]"
    assert format_cost_usd(0.001234) == "$0.001234"
    assert format_ms(1500) == "1.50s"
    assert format_ms(12.3) == "12.3ms"
