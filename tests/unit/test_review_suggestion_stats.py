"""Phase 11.5B — review list/detail suggestion stats consistency."""

from __future__ import annotations

from types import SimpleNamespace

from refactory.db.query_service import RepositoryQueryService


def test_suggestion_stats_counts_by_severity_and_files() -> None:
    suggestions = [
        {"file": "a.py", "severity": "critical"},
        {"file": "a.py", "severity": "high"},
        {"file": "b.py", "severity": "medium"},
        {"file": "c.py", "severity": "low"},
    ]
    stats = RepositoryQueryService.suggestion_stats(suggestions)
    assert stats["suggestion_count"] == 4
    assert stats["file_count"] == 3
    assert stats["critical_count"] == 2
    assert stats["warning_count"] == 2


def test_suggestion_stats_accepts_orm_like_rows() -> None:
    rows = [
        SimpleNamespace(file="x.py", severity="blocker"),
        SimpleNamespace(file="", severity="info"),
    ]
    stats = RepositoryQueryService.suggestion_stats(rows)
    assert stats["suggestion_count"] == 2
    assert stats["file_count"] == 1
    assert stats["critical_count"] == 1
    assert stats["warning_count"] == 0


def test_review_to_dict_includes_stats() -> None:
    review = SimpleNamespace(
        id="r1",
        repository_id="repo",
        pr_number=1,
        provider="openai",
        model="gpt",
        risk="high",
        confidence=0.9,
        summary="ok",
        created_at=None,
    )
    suggestions = [
        SimpleNamespace(file="a.py", severity="high"),
        SimpleNamespace(file="b.py", severity="medium"),
        SimpleNamespace(file="a.py", severity="low"),
    ]
    data = RepositoryQueryService._review_to_dict(review, suggestions=suggestions)
    assert data["suggestion_count"] == 3
    assert data["file_count"] == 2
    assert data["critical_count"] == 1
    assert data["warning_count"] == 2
    assert "suggestions" not in data
