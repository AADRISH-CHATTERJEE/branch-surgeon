"""Regression tests: every AI review finding displays all 8 acceptance-criteria fields.

Sprint 5 acceptance criteria for review findings:
  1. Severity
  2. Category
  3. File
  4. Line
  5. Explanation
  6. Suggested Fix
  7. Confidence
  8. Estimated Impact

Tests verify both the model layer and the CLI rendering layer.
"""

from __future__ import annotations

from io import StringIO
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


def _make_service() -> PRIntelligenceService:
    ai = MagicMock()
    resp = MagicMock()
    resp.content = "AI summary"
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


# ---------------------------------------------------------------------------
# Model field completeness
# ---------------------------------------------------------------------------

class TestReviewCommentModel:
    def test_all_eight_fields_exist(self):
        c = ReviewComment()
        assert hasattr(c, "severity")
        assert hasattr(c, "category")
        assert hasattr(c, "file")
        assert hasattr(c, "line")
        assert hasattr(c, "explanation")
        assert hasattr(c, "suggested_fix")
        assert hasattr(c, "confidence")
        assert hasattr(c, "estimated_impact")

    def test_fully_populated_comment(self):
        c = ReviewComment(
            file="app.py", line=42,
            category=ReviewCategory.SECURITY,
            severity="critical",
            explanation="Use of eval()",
            suggested_fix="Use ast.literal_eval()",
            confidence=0.95,
            estimated_impact="Remote code execution",
        )
        assert c.file == "app.py"
        assert c.line == 42
        assert c.category == ReviewCategory.SECURITY
        assert c.severity == "critical"
        assert c.explanation == "Use of eval()"
        assert c.suggested_fix == "Use ast.literal_eval()"
        assert c.confidence == 0.95
        assert c.estimated_impact == "Remote code execution"

    def test_default_values(self):
        c = ReviewComment()
        assert c.file == ""
        assert c.line == 0
        assert c.category == ReviewCategory.STYLE
        assert c.severity == "info"
        assert c.explanation == ""
        assert c.suggested_fix == ""
        assert c.confidence == 0.0
        assert c.estimated_impact == ""

    def test_serialization_includes_all_fields(self):
        c = ReviewComment(
            file="x.py", line=1, category=ReviewCategory.BUG_RISK,
            severity="warning", explanation="bare except",
            suggested_fix="use Exception", confidence=0.9,
            estimated_impact="masks errors",
        )
        data = c.model_dump()
        for field in ("file", "line", "category", "severity",
                       "explanation", "suggested_fix", "confidence",
                       "estimated_impact"):
            assert field in data, f"Missing field in serialization: {field}"


# ---------------------------------------------------------------------------
# Heuristic review populates all 8 fields
# ---------------------------------------------------------------------------

class TestHeuristicFieldCompleteness:
    """Every heuristic pattern must populate all 8 fields."""

    @pytest.fixture
    def svc(self) -> PRIntelligenceService:
        return _make_service()

    def _review_code(self, svc, tmp_path, code, filename="test_file.py"):
        (tmp_path / filename).write_text(code)
        diff = DiffSummary(
            changed_files=[ChangedFile(path=filename, change_kind=DiffChangeKind.MODIFIED)],
        )
        return svc.ai_review(diff, tmp_path)

    def _assert_all_fields_populated(self, comment: ReviewComment):
        assert comment.file, "file must be set"
        assert comment.line > 0, "line must be > 0"
        assert comment.category, "category must be set"
        assert comment.severity, "severity must be set"
        assert comment.explanation, "explanation must be set"
        assert comment.suggested_fix, "suggested_fix must be set"
        assert comment.confidence > 0, "confidence must be > 0"
        assert comment.estimated_impact, "estimated_impact must be set"

    def test_todo_all_fields(self, svc, tmp_path):
        report = self._review_code(svc, tmp_path, "# TODO: fix later\n")
        assert len(report.comments) >= 1
        self._assert_all_fields_populated(report.comments[0])

    def test_bare_except_all_fields(self, svc, tmp_path):
        report = self._review_code(svc, tmp_path, "try:\n    x=1\nexcept:\n    pass\n")
        bare = [c for c in report.comments if c.category == ReviewCategory.BUG_RISK]
        assert len(bare) >= 1
        self._assert_all_fields_populated(bare[0])

    def test_eval_all_fields(self, svc, tmp_path):
        report = self._review_code(svc, tmp_path, "x = eval('1')\n")
        sec = [c for c in report.comments if c.category == ReviewCategory.SECURITY]
        assert len(sec) >= 1
        self._assert_all_fields_populated(sec[0])

    def test_wildcard_import_all_fields(self, svc, tmp_path):
        report = self._review_code(svc, tmp_path, "from os import *\n")
        wc = [c for c in report.comments if "wildcard" in c.explanation.lower()]
        assert len(wc) >= 1
        self._assert_all_fields_populated(wc[0])

    def test_hardcoded_password_all_fields(self, svc, tmp_path):
        report = self._review_code(svc, tmp_path, 'password = "secret"\n')
        sec = [c for c in report.comments if c.category == ReviewCategory.SECURITY]
        assert len(sec) >= 1
        self._assert_all_fields_populated(sec[0])

    def test_print_all_fields(self, svc, tmp_path):
        report = self._review_code(svc, tmp_path, "print('hello')\n", "service.py")
        prints = [c for c in report.comments if "print" in c.explanation.lower()]
        assert len(prints) >= 1
        self._assert_all_fields_populated(prints[0])


# ---------------------------------------------------------------------------
# CLI renderer output
# ---------------------------------------------------------------------------

class TestCLIRendererOutput:
    """Verify _render_ai_review outputs all 8 fields for each finding."""

    def test_all_fields_in_output(self):
        from unittest.mock import patch as mpatch
        from refactory.cli.commands.pr import _render_ai_review

        report = AIReviewReport(
            comments=[
                ReviewComment(
                    file="app.py", line=10,
                    category=ReviewCategory.SECURITY,
                    severity="critical",
                    explanation="eval() detected",
                    suggested_fix="Use ast.literal_eval()",
                    confidence=0.95,
                    estimated_impact="Remote code execution",
                ),
            ],
            summary="One critical finding.",
        )

        captured: list[str] = []
        original_print = None

        class FakeConsole:
            def print(self, *args, **kwargs):
                for a in args:
                    captured.append(str(a))

        with mpatch("refactory.cli.commands.pr.console", FakeConsole()):
            _render_ai_review(report)

        output = "\n".join(captured)

        assert "CRITICAL" in output or "critical" in output.lower(), "Severity missing"
        assert "Security" in output, "Category missing"
        assert "app.py" in output, "File missing"
        assert "10" in output, "Line missing"
        assert "eval() detected" in output, "Explanation missing"
        assert "ast.literal_eval()" in output, "Suggested Fix missing"
        assert "95%" in output, "Confidence missing"
        assert "Remote code execution" in output, "Estimated Impact missing"

    def test_summary_in_output(self):
        from unittest.mock import patch as mpatch
        from refactory.cli.commands.pr import _render_ai_review

        report = AIReviewReport(
            comments=[],
            summary="All clean.",
        )

        captured: list[str] = []

        class FakeConsole:
            def print(self, *args, **kwargs):
                for a in args:
                    captured.append(str(a))

        with mpatch("refactory.cli.commands.pr.console", FakeConsole()):
            _render_ai_review(report)

        output = "\n".join(captured)
        assert "All clean." in output

    def test_no_findings_message(self):
        from unittest.mock import patch as mpatch
        from refactory.cli.commands.pr import _render_ai_review

        report = AIReviewReport(comments=[], summary="")

        captured: list[str] = []

        class FakeConsole:
            def print(self, *args, **kwargs):
                for a in args:
                    captured.append(str(a))

        with mpatch("refactory.cli.commands.pr.console", FakeConsole()):
            _render_ai_review(report)

        output = "\n".join(captured)
        assert "No findings" in output

    def test_multiple_findings_numbered(self):
        from unittest.mock import patch as mpatch
        from refactory.cli.commands.pr import _render_ai_review

        report = AIReviewReport(
            comments=[
                ReviewComment(
                    file="a.py", line=1, category=ReviewCategory.STYLE,
                    severity="info", explanation="print stmt",
                    suggested_fix="use logging", confidence=0.7,
                    estimated_impact="unstructured output",
                ),
                ReviewComment(
                    file="b.py", line=5, category=ReviewCategory.BUG_RISK,
                    severity="warning", explanation="bare except",
                    suggested_fix="use Exception", confidence=0.9,
                    estimated_impact="masks errors",
                ),
            ],
            summary="Two findings.",
        )

        captured: list[str] = []

        class FakeConsole:
            def print(self, *args, **kwargs):
                for a in args:
                    captured.append(str(a))

        with mpatch("refactory.cli.commands.pr.console", FakeConsole()):
            _render_ai_review(report)

        output = "\n".join(captured)
        assert "Finding 1" in output
        assert "Finding 2" in output
        assert "a.py" in output
        assert "b.py" in output

    def test_json_output_contains_all_fields(self):
        report = AIReviewReport(
            comments=[
                ReviewComment(
                    file="x.py", line=7,
                    category=ReviewCategory.PERFORMANCE,
                    severity="warning",
                    explanation="nested loops",
                    suggested_fix="use itertools.product",
                    confidence=0.8,
                    estimated_impact="O(n^2) runtime",
                ),
            ],
            summary="perf issue",
        )
        import json
        data = json.loads(json.dumps(report.model_dump(), default=str))
        comment = data["comments"][0]
        for field in ("file", "line", "category", "severity",
                       "explanation", "suggested_fix", "confidence",
                       "estimated_impact"):
            assert field in comment, f"JSON output missing field: {field}"
        assert comment["confidence"] == 0.8
        assert comment["estimated_impact"] == "O(n^2) runtime"
