"""Unit tests for refactory.response.ResponseParser."""

from __future__ import annotations

from refactory.ai.models import AIResponse
from refactory.response.json_repair import repair_json_text, try_parse_json
from refactory.response.models import PartialReviewResult, ReviewResult
from refactory.response.parser import ResponseParser
from refactory.response.schema import validate_review_document


PERFECT_MARKDOWN = """
# Summary
Authentication looks mostly sound with one boundary gap.

# Overall Risk
medium

# Confidence
0.82

# Findings

## Missing auth check on admin route
- file: auth.py
- line: 42
- severity: high
- category: security
- confidence: 0.9
- explanation: Admin endpoint skips the session guard.
- recommendation: Reuse require_admin() middleware.
- code_snippet: def admin(): return data

## Unused import
- file: utils.py
- line: 3
- severity: low
- category: maintainability
- explanation: imported but never referenced
- recommendation: Remove the import
"""


def _parser() -> ResponseParser:
    return ResponseParser()


def test_perfect_markdown():
    result = _parser().parse(PERFECT_MARKDOWN)

    assert isinstance(result, ReviewResult)
    assert not result.is_partial
    assert "Authentication looks mostly sound" in result.summary
    assert result.overall_risk == "medium"
    assert result.confidence == 0.82
    assert len(result.suggestions) == 2

    first = result.suggestions[0]
    assert first.title == "Missing auth check on admin route"
    assert first.file == "auth.py"
    assert first.line == 42
    assert first.severity == "high"
    assert first.category == "security"
    assert first.confidence == 0.9
    assert "session guard" in first.explanation
    assert "require_admin" in first.recommendation
    assert first.code_snippet is not None


def test_malformed_markdown_still_returns_result():
    text = """
# Sumary
kinda broken

Findings maybe?
- something odd without structure
# Risk
not-a-real-level
"""
    result = _parser().parse(text)
    assert result is not None
    assert isinstance(result, (ReviewResult, PartialReviewResult))
    assert result.warnings


def test_empty_response():
    result = _parser().parse("   \n\t  ")
    assert isinstance(result, PartialReviewResult)
    assert result.is_partial
    assert result.summary == ""
    assert "Empty response text" in result.warnings
    assert "EMPTY_RESPONSE" in result.metadata.extra.get("error_codes", [])


def test_duplicate_findings_merged():
    text = """
# Summary
Dupes present
# Risk
low
# Confidence
0.5
# Findings
## Same issue
- file: a.py
- line: 1
- severity: medium
- explanation: first
## Same issue
- file: a.py
- line: 1
- severity: high
- explanation: second has more detail here
- recommendation: fix it
"""
    result = _parser().parse(text)
    assert len(result.suggestions) == 1
    sug = result.suggestions[0]
    assert sug.severity == "high"
    assert "second has more detail" in sug.explanation
    assert sug.recommendation == "fix it"
    assert any("Duplicate finding merged" in w for w in result.warnings)
    assert "DUPLICATE_MERGED" in result.metadata.extra.get("error_codes", [])


def test_missing_severity_defaults_with_warning():
    text = """
# Summary
Ok
# Risk
low
# Findings
## No severity set
- file: x.py
- line: 9
- explanation: details here
"""
    result = _parser().parse(text)
    assert len(result.suggestions) == 1
    assert result.suggestions[0].severity == "info"
    assert any("Missing severity" in w for w in result.warnings)


def test_missing_file_warns_but_keeps_finding():
    text = """
# Summary
Ok
# Risk
medium
# Findings
## Floating finding
- severity: high
- explanation: no file provided
"""
    result = _parser().parse(text)
    assert len(result.suggestions) == 1
    assert result.suggestions[0].file is None
    assert any("missing file" in w.lower() for w in result.warnings)


def test_malformed_json_does_not_crash():
    # Unrepairable: truncated string mid-token with no closing quote/brace balance
    text = '{ "summary": "broken", "findings": [{"title": "x'
    result = _parser().parse(text)
    assert isinstance(result, (ReviewResult, PartialReviewResult))
    assert any(
        "Malformed" in w or "JSON repair failed" in w or "parse failed" in w
        for w in result.warnings
    )


def test_json_repair_trailing_comma_and_truncation():
    text = '{ "summary": "repaired", "overall_risk": "low", "confidence": 0.6, "findings": [], '
    result = _parser().parse(text)
    assert result.summary == "repaired"
    assert result.overall_risk == "low"
    assert result.confidence == 0.6
    assert result.metadata.source_format == "json"
    assert any("JSON repaired" in w or "trailing" in w.lower() for w in result.warnings)


def test_valid_json_parse():
    text = """
{
  "summary": "JSON review",
  "risk_level": "high",
  "confidence": 0.7,
  "findings": [
    {
      "title": "SQL concat",
      "detail": "User input in query",
      "severity": "critical",
      "file_path": "db.py",
      "line": 10,
      "category": "security",
      "recommendation": "Use parameterized queries"
    }
  ]
}
"""
    result = _parser().parse(text)
    assert isinstance(result, ReviewResult)
    assert result.summary == "JSON review"
    assert result.overall_risk == "high"
    assert result.confidence == 0.7
    assert result.metadata.source_format == "json"
    assert result.suggestions[0].file == "db.py"
    assert result.suggestions[0].severity == "critical"
    assert "SCHEMA_OK" in result.metadata.extra.get("error_codes", [])


def test_confidence_extraction_percent_and_inline():
    text = """
summary: Percent form works
risk_level: low
confidence: 85%
"""
    result = _parser().parse(text)
    assert result.confidence == 0.85

    inline = _parser().parse(
        "# Summary\nHello\n# Risk\nlow\n\nOverall confidence: 0.55 for this review.\n"
    )
    assert inline.confidence == 0.55


def test_confidence_estimated_when_missing():
    text = """
# Summary
Estimated confidence case
# Risk
medium
# Findings
## Issue
- file: a.py
- severity: high
- explanation: something
"""
    result = _parser().parse(text)
    assert result.confidence is not None
    assert 0.05 <= result.confidence <= 0.95
    assert any("Confidence estimated" in w for w in result.warnings)
    assert result.metadata.extra.get("confidence_estimated") is True


def test_severity_normalization_aliases():
    text = """
{
  "summary": "sev norms",
  "overall_risk": "medium",
  "confidence": 0.5,
  "findings": [
    {"title": "warn", "severity": "warning", "file": "a.py"},
    {"title": "err", "severity": "error", "file": "b.py"},
    {"title": "weird", "severity": "URGENT!!!", "file": "c.py"}
  ]
}
"""
    result = _parser().parse(text)
    by_title = {s.title: s.severity for s in result.suggestions}
    assert by_title["warn"] == "medium"
    assert by_title["err"] == "high"
    assert by_title["weird"] == "info"
    assert any("Unrecognized severity" in w for w in result.warnings)


def test_key_value_mock_provider_style():
    text = (
        "MOCK_REVIEW\n"
        "digest=abc\n"
        "pr=1\n"
        "repo=demo\n"
        "summary: Deterministic mock review response.\n"
        "risk_level: low\n"
        "findings: []\n"
        "confidence: 0.5\n"
    )
    result = _parser().parse(text)
    assert result.summary == "Deterministic mock review response."
    assert result.overall_risk == "low"
    assert result.confidence == 0.5
    assert result.suggestions == []


def test_parse_response_attaches_provider_metadata():
    response = AIResponse(
        text="# Summary\nOk\n# Risk\nlow\n# Confidence\n0.4\n",
        provider="mock",
        model="mock-review-1",
        latency_ms=1.0,
    )
    result = _parser().parse_response(response)
    assert result.metadata.provider == "mock"
    assert result.metadata.model == "mock-review-1"


def test_minor_formatting_inconsistencies():
    text = """
## summary
  Slightly messy formatting

**Risk Level**: HIGH

confidence = 70%

### Findings
- **Title**: Weird bullets
  - File : auth/service.py
  - Line: 7
  - Severity: High
  - Detail: Inconsistent keys still parse
  - Fix: Normalize at the edge
"""
    result = _parser().parse(text)
    assert "messy formatting" in result.summary.lower() or "Slightly" in result.summary
    assert result.overall_risk == "high"
    assert result.confidence == 0.7
    assert len(result.suggestions) >= 1
    sug = result.suggestions[0]
    assert sug.file == "auth/service.py"
    assert sug.line == 7
    assert sug.severity == "high"


def test_fenced_json_block():
    text = """
Here is the review:

```json
{
  "summary": "Fenced",
  "overall_risk": "low",
  "confidence": 0.4,
  "suggestions": []
}
```
"""
    result = _parser().parse(text)
    assert result.summary == "Fenced"
    assert result.metadata.source_format == "json"


def test_partial_recovery_missing_core_fields():
    text = "# Findings\n## Only a finding\n- severity: high\n- file: z.py\n"
    result = _parser().parse(text)
    assert isinstance(result, PartialReviewResult)
    assert result.is_partial
    assert len(result.suggestions) == 1
    assert result.metadata.extra.get("partial_recovery") is True


def test_parser_never_raises_on_garbage():
    garbage_inputs = ["", "{}", "[]", "not a review", "# Only heading", "\x00\x01"]
    for payload in garbage_inputs:
        result = _parser().parse(payload)
        assert isinstance(result, (ReviewResult, PartialReviewResult))


def test_try_parse_json_repairs_single_quotes():
    data, warnings = try_parse_json("{'summary': 'ok', 'overall_risk': 'low'}")
    assert data is not None
    assert data["summary"] == "ok"
    assert any("quote" in w.lower() or "repaired" in w.lower() for w in warnings)


def test_repair_json_text_closes_braces():
    repaired, notes = repair_json_text('{"summary": "x", "findings": [')
    assert repaired.count("{") == repaired.count("}")
    assert repaired.count("[") == repaired.count("]")
    assert notes


def test_validate_review_document_canonicalizes():
    data, warnings = validate_review_document(
        {"overview": "Hi", "risk": "high", "findings": [{"title": "t"}]}
    )
    assert data is not None
    assert data["summary"] == "Hi"
    assert data["overall_risk"] == "high"
    assert data["suggestions"] is not None
    assert any("schema validated" in w.lower() for w in warnings)


def test_review_result_contract_fields_stable():
    result = _parser().parse(PERFECT_MARKDOWN)
    dumped = result.model_dump()
    assert set(dumped.keys()) >= {
        "summary",
        "overall_risk",
        "suggestions",
        "confidence",
        "metadata",
        "is_partial",
    }
    assert dumped["is_partial"] is False
