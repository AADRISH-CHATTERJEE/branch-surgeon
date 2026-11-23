"""Architectural guard: business layers must never import the CLI."""

from __future__ import annotations

import ast
from pathlib import Path


FORBIDDEN_PREFIXES = ("refactory.cli",)


def _iter_python_files(package: str) -> list[Path]:
    root = Path(__file__).resolve().parents[2] / "refactory" / package
    return list(root.rglob("*.py"))


def _imports_cli(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(FORBIDDEN_PREFIXES):
                    bad.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(FORBIDDEN_PREFIXES):
                bad.append(node.module)
    return bad


def test_core_and_services_do_not_import_cli():
    packages = [
        "core",
        "review",
        "git",
        "github",
        "parser",
        "indexer",
        "retrieval",
        "embeddings",
        "embedding",
        "graph",
        "backend",
        "prompt",
        "ai",
        "storage",
        "utils",
    ]
    violations: list[str] = []
    for package in packages:
        for path in _iter_python_files(package):
            for name in _imports_cli(path):
                violations.append(f"{path}: imports {name}")
    assert violations == []
