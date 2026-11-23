"""Tests for hybrid retrieval ranking and context budget."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from refactory.github.models import ChangedFile, PullRequest
from refactory.prompt.budget import ContextBudget
from refactory.retrieval.hybrid import HybridRanker
from refactory.retrieval.models import EntityKind, RetrievedFile, RetrievedSymbol, SearchQuery, SearchResult


def test_context_budget_estimate_tokens():
    assert ContextBudget.estimate_tokens("") == 0
    assert ContextBudget.estimate_tokens("abcd") == 1
    assert ContextBudget.estimate_tokens("a" * 40) == 10


def test_hybrid_ranker_combines_changed_and_semantic():
    retrieval = MagicMock()
    retrieval.search.return_value = SearchResult(
        query=SearchQuery(text="auth"),
        hits=[
            RetrievedSymbol(
                result="function:login",
                score=0.88,
                file_path="login.py",
                module_name="login",
                symbol="login",
                kind=EntityKind.FUNCTION,
            )
        ],
    )
    retrieval.related_files.return_value = [
        RetrievedFile(
            file_path="helpers.py",
            module_name="helpers",
            score=0.7,
            best_symbol="util",
            best_kind=EntityKind.FUNCTION,
        )
    ]

    graph = MagicMock()
    graph.graph.return_value = MagicMock(
        file_index={"auth.py": "file:auth.py", "login.py": "file:login.py"},
        nodes={},
    )
    graph.dependencies_of.return_value = ["login.py"]
    graph.reverse_dependencies.return_value = []
    graph.affected_files.return_value = ["login.py"]
    graph.graph_distance.return_value = 1
    graph.defined_symbols_in_file.return_value = []
    graph.files_referencing_symbol.return_value = []

    pr = PullRequest(
        number=1,
        title="auth",
        changed_files=[ChangedFile(path="auth.py", status="modified")],
    )
    ranked = HybridRanker(retrieval, graph=graph).rank(
        pr, query="auth", root=Path("."), top_k=10
    )
    paths = [e.file_path for e in ranked.entries]
    assert "auth.py" in paths
    assert any("changed" in e.reasons for e in ranked.entries if e.file_path == "auth.py")
    assert ranked.symbols
    assert ranked.entries[0].score >= ranked.entries[-1].score
