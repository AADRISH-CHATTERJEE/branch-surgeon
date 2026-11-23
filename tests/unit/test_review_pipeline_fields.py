"""End-to-end regression tests for the `refactory review` pipeline.

Verifies that all 8 Sprint-5 acceptance-criteria fields survive the full
chain: AI JSON response → ResponseParser → _to_engine_result → ReviewResult
→ render_review_report.

Chain under test:
  1. AI returns JSON with {category, line, confidence, estimated_impact, ...}
  2. ResponseParser._suggestion_from_mapping → response.models.ReviewSuggestion
  3. ReviewEngine._to_engine_result → review.models.ReviewSuggestion
  4. render_review_report → CLI output
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from refactory.response.models import ReviewSuggestion as ParsedSuggestion
from refactory.response.parser import ResponseParser
from refactory.review.engine import ReviewEngine
from refactory.review.models import ReviewResult, ReviewSuggestion


# ---------------------------------------------------------------------------
# 1. ResponseParser extracts all fields from AI JSON
# ---------------------------------------------------------------------------

class TestParserExtractsAllFields:
    @pytest.fixture
    def parser(self):
        return ResponseParser()

    def test_json_finding_has_all_fields(self, parser):
        ai_json = json.dumps({
            "summary": "Two issues found",
            "risk_level": "medium",
            "confidence": 0.85,
            "findings": [
                {
                    "title": "SQL injection risk",
                    "severity": "critical",
                    "category": "security",
                    "file": "db/query.py",
                    "line": 42,
                    "explanation": "User input concatenated into SQL",
                    "recommendation": "Use parameterized queries",
                    "confidence": 0.95,
                    "estimated_impact": "Data breach via injection",
                },
            ],
        })
        result = parser.parse(ai_json)
        assert len(result.suggestions) == 1
        s = result.suggestions[0]
        assert s.title == "SQL injection risk"
        assert s.severity == "critical"
        assert s.category == "security"
        assert s.file == "db/query.py"
        assert s.line == 42
        assert s.explanation == "User input concatenated into SQL"
        assert s.recommendation == "Use parameterized queries"
        assert s.confidence == 0.95
        assert s.estimated_impact == "Data breach via injection"

    def test_impact_alias_parsed(self, parser):
        """AI might use 'impact' instead of 'estimated_impact'."""
        ai_json = json.dumps({
            "summary": "ok",
            "risk_level": "low",
            "findings": [
                {
                    "title": "Print statement",
                    "severity": "info",
                    "file": "app.py",
                    "line": 10,
                    "explanation": "Debug print in production",
                    "recommendation": "Use logging",
                    "impact": "Unstructured stdout output",
                },
            ],
        })
        result = parser.parse(ai_json)
        s = result.suggestions[0]
        assert s.estimated_impact == "Unstructured stdout output"

    def test_missing_optional_fields_graceful(self, parser):
        ai_json = json.dumps({
            "summary": "clean",
            "risk_level": "low",
            "findings": [
                {
                    "title": "Minor style issue",
                    "severity": "info",
                    "explanation": "Long line",
                },
            ],
        })
        result = parser.parse(ai_json)
        s = result.suggestions[0]
        assert s.category is None
        assert s.line is None
        assert s.confidence is None
        assert s.estimated_impact is None

    def test_markdown_findings_preserve_category(self, parser):
        md = (
            "## Summary\n\nTwo issues.\n\n"
            "## Risk\n\nmedium\n\n"
            "## Findings\n\n"
            "### Eval usage\n\n"
            "- **Severity**: critical\n"
            "- **Category**: security\n"
            "- **File**: app.py\n"
            "- **Line**: 5\n"
            "- **Explanation**: eval() is dangerous\n"
            "- **Recommendation**: Use ast.literal_eval\n"
            "- **Confidence**: 0.9\n"
            "- **Estimated Impact**: Remote code execution\n"
        )
        result = parser.parse(md)
        assert len(result.suggestions) >= 1
        s = result.suggestions[0]
        assert s.category == "security"
        assert s.estimated_impact == "Remote code execution"


# ---------------------------------------------------------------------------
# 2. _to_engine_result maps all fields from ParsedSuggestion to ReviewSuggestion
# ---------------------------------------------------------------------------

class TestEngineResultMapping:
    def test_all_fields_mapped(self):
        parsed_suggestion = ParsedSuggestion(
            title="Hardcoded secret",
            explanation="API key in source",
            recommendation="Use env var",
            severity="critical",
            file="config.py",
            line=15,
            confidence=0.92,
            category="security",
            estimated_impact="Credential exposure",
        )
        parsed_review = MagicMock()
        parsed_review.suggestions = [parsed_suggestion]
        parsed_review.summary = "One critical finding"
        parsed_review.overall_risk = "high"
        parsed_review.confidence = 0.85
        parsed_review.warnings = []
        parsed_review.is_partial = False
        parsed_review.metadata = MagicMock()
        parsed_review.metadata.source_format = "json"
        parsed_review.metadata.raw_length = 500
        parsed_review.metadata.provider = "test"
        parsed_review.metadata.model = "test-model"
        parsed_review.metadata.extra = {}

        result = ReviewEngine._to_engine_result(99, parsed_review)

        assert len(result.suggestions) == 1
        s = result.suggestions[0]
        assert s.title == "Hardcoded secret"
        assert s.severity == "critical"
        assert s.file_path == "config.py"
        assert s.line == 15
        assert s.confidence == 0.92
        assert s.category == "security"
        assert s.suggested_fix == "Use env var"
        assert s.estimated_impact == "Credential exposure"
        assert "API key in source" in s.detail

    def test_missing_optional_fields_get_inferred(self):
        """When AI omits confidence/estimated_impact, fallbacks infer values."""
        parsed_suggestion = ParsedSuggestion(
            title="Style issue",
            explanation="Long line",
            severity="info",
        )
        parsed_review = MagicMock()
        parsed_review.suggestions = [parsed_suggestion]
        parsed_review.summary = ""
        parsed_review.overall_risk = "low"
        parsed_review.confidence = 0.5
        parsed_review.warnings = []
        parsed_review.is_partial = False
        parsed_review.metadata = MagicMock()
        parsed_review.metadata.source_format = "json"
        parsed_review.metadata.raw_length = 100
        parsed_review.metadata.provider = None
        parsed_review.metadata.model = None
        parsed_review.metadata.extra = {}

        result = ReviewEngine._to_engine_result(1, parsed_review)
        s = result.suggestions[0]
        assert s.line is None
        assert s.category is None
        assert s.confidence == 0.4, "info severity → inferred confidence 0.4"
        assert s.suggested_fix == ""
        assert "Maintainability" in s.estimated_impact, "info severity → Maintainability impact"

    def test_ai_provided_fields_not_overridden(self):
        """When AI provides confidence/estimated_impact, fallbacks don't override."""
        parsed_suggestion = ParsedSuggestion(
            title="SQL injection",
            explanation="User input in query",
            severity="critical",
            confidence=0.95,
            category="security",
            estimated_impact="Data breach via SQL injection",
        )
        parsed_review = MagicMock()
        parsed_review.suggestions = [parsed_suggestion]
        parsed_review.summary = ""
        parsed_review.overall_risk = "high"
        parsed_review.confidence = 0.9
        parsed_review.warnings = []
        parsed_review.is_partial = False
        parsed_review.metadata = MagicMock()
        parsed_review.metadata.source_format = "json"
        parsed_review.metadata.raw_length = 200
        parsed_review.metadata.provider = None
        parsed_review.metadata.model = None
        parsed_review.metadata.extra = {}

        result = ReviewEngine._to_engine_result(1, parsed_review)
        s = result.suggestions[0]
        assert s.confidence == 0.95, "AI-provided confidence preserved"
        assert s.estimated_impact == "Data breach via SQL injection", "AI-provided impact preserved"


# ---------------------------------------------------------------------------
# 3. render_review_report displays all 8 fields
# ---------------------------------------------------------------------------

class TestRendererDisplaysAllFields:
    def test_all_8_fields_in_output(self):
        result = ReviewResult(
            pull_request_number=25,
            summary="One security issue.",
            risk_level="high",
            confidence=0.9,
            suggestions=[
                ReviewSuggestion(
                    title="SQL injection",
                    detail="User input concatenated into SQL query",
                    severity="critical",
                    file_path="db/query.py",
                    line=42,
                    category="security",
                    confidence=0.95,
                    suggested_fix="Use parameterized queries",
                    estimated_impact="Data breach via injection",
                ),
            ],
        )

        captured: list[str] = []

        class FakeConsole:
            def print(self, *args, **kwargs):
                for a in args:
                    captured.append(str(a))

        with patch("refactory.cli.ui.report.console", FakeConsole()):
            from refactory.cli.ui.report import render_review_report
            render_review_report(result)

        output = "\n".join(captured)

        assert "CRITICAL" in output or "critical" in output.lower(), "Severity missing"
        assert "Security" in output or "security" in output.lower(), "Category missing"
        assert "db/query.py" in output, "File missing"
        assert "42" in output, "Line missing"
        assert "User input concatenated" in output, "Explanation missing"
        assert "parameterized queries" in output, "Suggested Fix missing"
        assert "95%" in output, "Confidence missing"
        assert "Data breach" in output, "Estimated Impact missing"

    def test_finding_with_no_optional_fields(self):
        result = ReviewResult(
            pull_request_number=1,
            summary="Minor.",
            risk_level="low",
            confidence=0.5,
            suggestions=[
                ReviewSuggestion(
                    title="Style issue",
                    detail="Long line",
                    severity="info",
                ),
            ],
        )

        captured: list[str] = []

        class FakeConsole:
            def print(self, *args, **kwargs):
                for a in args:
                    captured.append(str(a))

        with patch("refactory.cli.ui.report.console", FakeConsole()):
            from refactory.cli.ui.report import render_review_report
            render_review_report(result)

        output = "\n".join(captured)
        assert "Finding 1" in output
        assert "—" in output  # dashes for missing fields


# ---------------------------------------------------------------------------
# 4. Full chain: AI JSON → Parser → Engine → ReviewResult
# ---------------------------------------------------------------------------

class TestFullChain:
    def test_json_to_review_result(self):
        ai_json = json.dumps({
            "summary": "Critical security issue",
            "risk_level": "high",
            "confidence": 0.88,
            "findings": [
                {
                    "title": "eval() usage",
                    "severity": "critical",
                    "category": "security",
                    "file": "handler.py",
                    "line": 23,
                    "explanation": "eval() allows arbitrary code execution",
                    "recommendation": "Use ast.literal_eval()",
                    "confidence": 0.95,
                    "estimated_impact": "Remote code execution vulnerability",
                },
                {
                    "title": "Missing type hints",
                    "severity": "info",
                    "category": "maintainability",
                    "file": "utils.py",
                    "line": 1,
                    "explanation": "Module lacks type annotations",
                    "recommendation": "Add type hints to public functions",
                    "confidence": 0.7,
                    "estimated_impact": "Reduced IDE support and documentation",
                },
            ],
        })

        parser = ResponseParser()
        parsed = parser.parse(ai_json, provider="gemini", model="gemini-pro")

        result = ReviewEngine._to_engine_result(25, parsed)

        assert result.pull_request_number == 25
        assert len(result.suggestions) == 2

        s1 = result.suggestions[0]
        assert s1.title == "eval() usage"
        assert s1.severity == "critical"
        assert s1.category == "security"
        assert s1.file_path == "handler.py"
        assert s1.line == 23
        assert "arbitrary code execution" in s1.detail
        assert s1.suggested_fix == "Use ast.literal_eval()"
        assert s1.confidence == 0.95
        assert s1.estimated_impact == "Remote code execution vulnerability"

        s2 = result.suggestions[1]
        assert s2.title == "Missing type hints"
        assert s2.category == "maintainability"
        assert s2.confidence == 0.7
        assert s2.estimated_impact == "Reduced IDE support and documentation"

    def test_json_without_confidence_and_impact_gets_inferred(self):
        """Full chain: AI omits confidence/estimated_impact → engine infers them."""
        ai_json = json.dumps({
            "summary": "Style issues",
            "risk_level": "low",
            "confidence": 0.75,
            "findings": [
                {
                    "title": "Bare except clause",
                    "severity": "medium",
                    "category": "correctness",
                    "file": "handler.py",
                    "line": 10,
                    "explanation": "Catches all exceptions including SystemExit",
                    "recommendation": "Use except Exception instead",
                },
                {
                    "title": "Print statement",
                    "severity": "info",
                    "file": "utils.py",
                    "explanation": "Debug print left in code",
                    "recommendation": "Use logging module",
                },
            ],
        })

        parser = ResponseParser()
        parsed = parser.parse(ai_json, provider="gemini", model="gemini-pro")

        result = ReviewEngine._to_engine_result(25, parsed)

        s1 = result.suggestions[0]
        assert s1.confidence == 0.7, "medium severity → inferred 0.7"
        assert "Correctness" in s1.estimated_impact, "correctness category → Correctness impact"

        s2 = result.suggestions[1]
        assert s2.confidence == 0.4, "info severity → inferred 0.4"
        assert s2.estimated_impact, "should have non-empty inferred impact"

    def test_inferred_fields_render_in_cli(self):
        """Full chain: inferred confidence/impact display correctly in renderer."""
        ai_json = json.dumps({
            "summary": "One finding",
            "risk_level": "medium",
            "findings": [
                {
                    "title": "Eval usage",
                    "severity": "high",
                    "category": "security",
                    "file": "run.py",
                    "line": 5,
                    "explanation": "eval() is dangerous",
                    "recommendation": "Use literal_eval",
                },
            ],
        })

        parser = ResponseParser()
        parsed = parser.parse(ai_json, provider="gemini", model="gemini-pro")
        result = ReviewEngine._to_engine_result(1, parsed)

        captured: list[str] = []

        class FakeConsole:
            def print(self, *args, **kwargs):
                for a in args:
                    captured.append(str(a))

        with patch("refactory.cli.ui.report.console", FakeConsole()):
            from refactory.cli.ui.report import render_review_report
            render_review_report(result)

        output = "\n".join(captured)
        assert "80%" in output, "high severity → inferred 80% confidence in CLI"
        assert "Security" in output, "security category → Security in estimated impact"
