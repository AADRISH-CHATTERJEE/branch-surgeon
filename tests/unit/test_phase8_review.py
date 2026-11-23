"""Tests for Phase 8: PR-1 (Structured AI review comments)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from refactory.pr.models import (
    AIReviewReport,
    ChangedFile,
    DiffChangeKind,
    DiffSummary,
    ReviewCategory,
    ReviewComment,
)
from refactory.pr.service import PRIntelligenceService


def _service():
    ai = MagicMock()
    resp = MagicMock()
    resp.content = "AI review summary"
    ai.generate.return_value = resp
    from loguru import logger
    return PRIntelligenceService(
        logger=logger,
        git_service=MagicMock(),
        parser_service=MagicMock(),
        indexer_service=MagicMock(),
        graph_service=MagicMock(),
        impact_service=MagicMock(),
        ai_gateway=ai,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    d = tmp_path / "repo"
    d.mkdir()
    return d


class TestStructuredReviewComments:
    def test_review_comment_has_all_fields(self):
        c = ReviewComment(
            file="app.py", line=10,
            category=ReviewCategory.SECURITY,
            severity="critical",
            explanation="eval() detected",
            confidence=0.95,
            suggested_fix="Use ast.literal_eval()",
            estimated_impact="Remote code execution",
        )
        assert c.severity == "critical"
        assert c.estimated_impact == "Remote code execution"
        assert c.suggested_fix != ""
        assert c.confidence > 0

    def test_bare_except_detected(self, repo: Path):
        (repo / "bad.py").write_text("try:\n    x = 1\nexcept:\n    pass\n")
        svc = _service()
        diff = DiffSummary(
            changed_files=[ChangedFile(path="bad.py", change_kind=DiffChangeKind.MODIFIED)],
        )
        report = svc.ai_review(diff, repo)
        bare = [c for c in report.comments if c.category == ReviewCategory.BUG_RISK]
        assert len(bare) >= 1
        assert bare[0].severity == "warning"
        assert bare[0].estimated_impact != ""

    def test_eval_security_critical(self, repo: Path):
        (repo / "danger.py").write_text("x = eval(input())\n")
        svc = _service()
        diff = DiffSummary(
            changed_files=[ChangedFile(path="danger.py", change_kind=DiffChangeKind.MODIFIED)],
        )
        report = svc.ai_review(diff, repo)
        sec = [c for c in report.comments if c.category == ReviewCategory.SECURITY]
        assert len(sec) >= 1
        assert sec[0].severity == "critical"

    def test_wildcard_import(self, repo: Path):
        (repo / "mod.py").write_text("from os import *\n")
        svc = _service()
        diff = DiffSummary(
            changed_files=[ChangedFile(path="mod.py", change_kind=DiffChangeKind.MODIFIED)],
        )
        report = svc.ai_review(diff, repo)
        style = [c for c in report.comments if c.category == ReviewCategory.STYLE and "wildcard" in c.explanation.lower()]
        assert len(style) >= 1

    def test_hardcoded_password(self, repo: Path):
        (repo / "config.py").write_text('password = "secret123"\n')
        svc = _service()
        diff = DiffSummary(
            changed_files=[ChangedFile(path="config.py", change_kind=DiffChangeKind.MODIFIED)],
        )
        report = svc.ai_review(diff, repo)
        sec = [c for c in report.comments if c.category == ReviewCategory.SECURITY]
        assert len(sec) >= 1

    def test_todo_has_impact(self, repo: Path):
        (repo / "util.py").write_text("# TODO: fix this later\nx = 1\n")
        svc = _service()
        diff = DiffSummary(
            changed_files=[ChangedFile(path="util.py", change_kind=DiffChangeKind.MODIFIED)],
        )
        report = svc.ai_review(diff, repo)
        todos = [c for c in report.comments if c.category == ReviewCategory.MAINTAINABILITY]
        assert len(todos) >= 1
        assert todos[0].estimated_impact != ""

    def test_print_in_production(self, repo: Path):
        (repo / "service.py").write_text("def run():\n    print('debug')\n")
        svc = _service()
        diff = DiffSummary(
            changed_files=[ChangedFile(path="service.py", change_kind=DiffChangeKind.MODIFIED)],
        )
        report = svc.ai_review(diff, repo)
        prints = [c for c in report.comments if "print" in c.explanation.lower()]
        assert len(prints) >= 1

    def test_clean_file_no_comments(self, repo: Path):
        (repo / "clean.py").write_text("def add(a, b):\n    return a + b\n")
        svc = _service()
        diff = DiffSummary(
            changed_files=[ChangedFile(path="clean.py", change_kind=DiffChangeKind.MODIFIED)],
        )
        report = svc.ai_review(diff, repo)
        assert len(report.comments) == 0

    def test_deleted_files_skipped(self, repo: Path):
        svc = _service()
        diff = DiffSummary(
            changed_files=[ChangedFile(path="deleted.py", change_kind=DiffChangeKind.DELETED)],
        )
        report = svc.ai_review(diff, repo)
        assert len(report.comments) == 0

    def test_multiple_files_reviewed(self, repo: Path):
        (repo / "a.py").write_text("# TODO: a\n")
        (repo / "b.py").write_text("# TODO: b\n")
        svc = _service()
        diff = DiffSummary(
            changed_files=[
                ChangedFile(path="a.py", change_kind=DiffChangeKind.MODIFIED),
                ChangedFile(path="b.py", change_kind=DiffChangeKind.MODIFIED),
            ],
        )
        report = svc.ai_review(diff, repo)
        files = {c.file for c in report.comments}
        assert "a.py" in files
        assert "b.py" in files

    def test_ai_summary_included(self, repo: Path):
        (repo / "x.py").write_text("x = 1\n")
        svc = _service()
        diff = DiffSummary(
            changed_files=[ChangedFile(path="x.py", change_kind=DiffChangeKind.MODIFIED)],
        )
        report = svc.ai_review(diff, repo)
        assert report.summary != ""
