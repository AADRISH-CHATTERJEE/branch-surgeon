"""Shared Rich styling helpers for CLI presentation."""

from __future__ import annotations

from rich.text import Text

_SEVERITY_STYLE = {
    "critical": "bold red",
    "high": "red",
    "medium": "yellow",
    "low": "cyan",
    "info": "dim",
    "unknown": "dim",
}

_RISK_STYLE = {
    "critical": "bold red",
    "high": "red",
    "medium": "yellow",
    "low": "green",
    "info": "cyan",
    "unknown": "dim",
}


def severity_style(severity: str | None) -> str:
    key = (severity or "info").strip().lower()
    return _SEVERITY_STYLE.get(key, "magenta")


def risk_style(risk: str | None) -> str:
    key = (risk or "unknown").strip().lower()
    return _RISK_STYLE.get(key, "white")


def format_cache_hit(value: bool | None) -> str:
    if value is True:
        return "[green]hit[/green]"
    if value is False:
        return "[dim]miss[/dim]"
    return "[dim]n/a[/dim]"


def format_cost_usd(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:.6f}"


def format_ms(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value >= 1000:
        return f"{value / 1000.0:.2f}s"
    return f"{value:.1f}ms"


def colored_severity(severity: str) -> Text:
    text = Text(severity or "info")
    text.stylize(severity_style(severity))
    return text
