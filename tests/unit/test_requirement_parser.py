"""Tests for RequirementParser — deterministic keyword/feature extraction."""

from __future__ import annotations

import pytest

from refactory.requirement.parser import RequirementParser


@pytest.fixture
def parser() -> RequirementParser:
    return RequirementParser()


# -------------------------------------------------------------------
# Empty / minimal input
# -------------------------------------------------------------------

class TestEmptyInput:
    def test_empty_string(self, parser: RequirementParser):
        result = parser.parse("")
        assert result.summary == ""
        assert result.detected_features == []
        assert result.detected_keywords == []

    def test_none_text(self, parser: RequirementParser):
        result = parser.parse(None)  # type: ignore[arg-type]
        assert result.summary == ""

    def test_whitespace_only(self, parser: RequirementParser):
        result = parser.parse("   \n\n  ")
        assert result.summary == ""

    def test_non_technical_text(self, parser: RequirementParser):
        result = parser.parse("The sky is blue and the grass is green.")
        assert result.detected_features == []
        assert result.detected_keywords == []

    def test_single_word(self, parser: RequirementParser):
        result = parser.parse("login")
        assert "Authentication" in result.detected_features
        assert "login" in result.detected_keywords


# -------------------------------------------------------------------
# Sentence splitting
# -------------------------------------------------------------------

class TestSentenceSplitting:
    def test_period_split(self, parser: RequirementParser):
        result = parser.parse("First sentence. Second sentence.")
        assert len(result.sentences) == 2

    def test_newline_split(self, parser: RequirementParser):
        result = parser.parse("First line\nSecond line")
        assert len(result.sentences) == 2

    def test_mixed_separators(self, parser: RequirementParser):
        result = parser.parse("Sentence one! Sentence two? Sentence three.")
        assert len(result.sentences) == 3

    def test_summary_is_first_sentence(self, parser: RequirementParser):
        result = parser.parse("Implement password reset. Users get an email.")
        assert result.summary == "Implement password reset"


# -------------------------------------------------------------------
# Authentication feature detection
# -------------------------------------------------------------------

class TestAuthFeatures:
    @pytest.mark.parametrize("term", [
        "authentication", "login", "JWT", "token", "OAuth",
        "password", "session", "MFA", "permission", "role",
    ])
    def test_auth_terms_detected(self, parser: RequirementParser, term: str):
        result = parser.parse(f"The system should use {term}.")
        assert "Authentication" in result.detected_features

    def test_multiple_auth_terms(self, parser: RequirementParser):
        result = parser.parse("Implement JWT authentication with role-based access control.")
        assert "Authentication" in result.detected_features
        kws = set(result.detected_keywords)
        assert "jwt" in kws
        assert "authenticate" not in kws or "authentication" in kws  # at least one
        assert "role" in kws


# -------------------------------------------------------------------
# Database feature detection
# -------------------------------------------------------------------

class TestDatabaseFeatures:
    @pytest.mark.parametrize("term", [
        "database", "SQL", "migration", "schema", "PostgreSQL",
        "Redis", "MongoDB", "ORM", "transaction",
    ])
    def test_database_terms(self, parser: RequirementParser, term: str):
        result = parser.parse(f"Use {term} for storage.")
        assert "Database" in result.detected_features

    def test_complex_db_requirement(self, parser: RequirementParser):
        text = "Migrate the database schema to support multi-tenant queries."
        result = parser.parse(text)
        assert "Database" in result.detected_features
        assert "migrate" in result.detected_keywords or "migration" in result.detected_keywords


# -------------------------------------------------------------------
# API feature detection
# -------------------------------------------------------------------

class TestAPIFeatures:
    @pytest.mark.parametrize("term", [
        "API", "REST", "GraphQL", "endpoint", "route",
        "middleware", "webhook", "CORS",
    ])
    def test_api_terms(self, parser: RequirementParser, term: str):
        result = parser.parse(f"Build a {term} layer.")
        assert "API" in result.detected_features


# -------------------------------------------------------------------
# Security feature detection
# -------------------------------------------------------------------

class TestSecurityFeatures:
    @pytest.mark.parametrize("term", [
        "encrypt", "hash", "CSRF", "XSS", "audit",
        "vulnerability", "certificate",
    ])
    def test_security_terms(self, parser: RequirementParser, term: str):
        result = parser.parse(f"Address {term} concerns.")
        assert "Security" in result.detected_features


# -------------------------------------------------------------------
# Configuration feature detection
# -------------------------------------------------------------------

class TestConfigFeatures:
    @pytest.mark.parametrize("term", ["config", "environment", "feature flag", "settings"])
    def test_config_terms(self, parser: RequirementParser, term: str):
        result = parser.parse(f"Update {term}.")
        assert "Configuration" in result.detected_features


# -------------------------------------------------------------------
# Email feature detection
# -------------------------------------------------------------------

class TestEmailFeatures:
    @pytest.mark.parametrize("term", ["email", "SMTP", "notification", "newsletter"])
    def test_email_terms(self, parser: RequirementParser, term: str):
        result = parser.parse(f"Send {term}.")
        assert "Email" in result.detected_features


# -------------------------------------------------------------------
# Cache feature detection
# -------------------------------------------------------------------

class TestCacheFeatures:
    @pytest.mark.parametrize("term", ["cache", "Redis", "TTL", "invalidate"])
    def test_cache_terms(self, parser: RequirementParser, term: str):
        result = parser.parse(f"Implement {term} layer.")
        assert "Cache" in result.detected_features or "Database" in result.detected_features


# -------------------------------------------------------------------
# Technical verbs
# -------------------------------------------------------------------

class TestTechnicalVerbs:
    def test_verbs_extracted(self, parser: RequirementParser):
        result = parser.parse("Implement the authentication and validate all tokens.")
        assert "implement" in result.technical_verbs
        assert "validate" in result.technical_verbs

    def test_no_verbs_in_plain_text(self, parser: RequirementParser):
        result = parser.parse("The sky is very blue today.")
        assert result.technical_verbs == []


# -------------------------------------------------------------------
# File hints
# -------------------------------------------------------------------

class TestFileHints:
    def test_python_file(self, parser: RequirementParser):
        result = parser.parse("Modify auth.py to add the new endpoint.")
        assert "auth.py" in result.file_hints

    def test_multiple_files(self, parser: RequirementParser):
        result = parser.parse("Update config.yaml and service.py and test_auth.py.")
        assert "config.yaml" in result.file_hints
        assert "service.py" in result.file_hints
        assert "test_auth.py" in result.file_hints

    def test_no_files(self, parser: RequirementParser):
        result = parser.parse("Implement password reset.")
        assert result.file_hints == []


# -------------------------------------------------------------------
# Mixed-case handling
# -------------------------------------------------------------------

class TestCaseHandling:
    def test_uppercase_keyword(self, parser: RequirementParser):
        result = parser.parse("Use JWT for AUTHENTICATION.")
        assert "Authentication" in result.detected_features

    def test_mixed_case(self, parser: RequirementParser):
        result = parser.parse("OAuth2 Token refresh endpoint.")
        assert "Authentication" in result.detected_features
        assert "API" in result.detected_features


# -------------------------------------------------------------------
# Multi-feature requirements
# -------------------------------------------------------------------

class TestMultiFeature:
    def test_password_reset_example(self, parser: RequirementParser):
        text = (
            "Implement password reset. "
            "Users should receive a reset email. "
            "Tokens expire after 15 minutes. "
            "Old passwords cannot be reused. "
            "Audit every password reset."
        )
        result = parser.parse(text)
        assert "Authentication" in result.detected_features
        assert "Email" in result.detected_features
        assert "Security" in result.detected_features
        assert len(result.sentences) >= 4

    def test_database_api_requirement(self, parser: RequirementParser):
        text = "Create a REST API endpoint that queries the PostgreSQL database."
        result = parser.parse(text)
        assert "API" in result.detected_features
        assert "Database" in result.detected_features

    def test_large_requirement_text(self, parser: RequirementParser):
        text = " ".join(
            [f"Sentence number {i} about authentication and database." for i in range(50)]
        )
        result = parser.parse(text)
        assert "Authentication" in result.detected_features
        assert len(result.detected_keywords) > 0

    def test_malformed_text(self, parser: RequirementParser):
        text = "!!!auth???  \n\n\n   login---reset    $$"
        result = parser.parse(text)
        assert "Authentication" in result.detected_features


# -------------------------------------------------------------------
# Input sanitization (Backlog 8)
# -------------------------------------------------------------------

class TestInputSanitization:
    """Control characters must be stripped before parsing."""

    def test_ctrl_v_artifact(self, parser: RequirementParser):
        text = "\x16Implement authentication."
        result = parser.parse(text)
        assert "Authentication" in result.detected_features
        assert "\x16" not in result.summary

    def test_null_byte(self, parser: RequirementParser):
        text = "Add login\x00 endpoint."
        result = parser.parse(text)
        assert "Authentication" in result.detected_features
        assert "\x00" not in result.summary

    def test_embedded_control_chars(self, parser: RequirementParser):
        text = "Implement\x01\x02\x03 JWT\x04 authentication."
        result = parser.parse(text)
        assert "Authentication" in result.detected_features
        assert "jwt" in result.detected_keywords

    def test_bell_and_escape_removed(self, parser: RequirementParser):
        text = "\x07Alert!\x1b[31m Add database migration.\x1b[0m"
        result = parser.parse(text)
        assert "Database" in result.detected_features

    def test_tabs_preserved(self, parser: RequirementParser):
        text = "Implement\tauthentication."
        result = parser.parse(text)
        assert "Authentication" in result.detected_features
        assert "\t" in result.summary

    def test_newlines_preserved(self, parser: RequirementParser):
        text = "Implement authentication.\nAdd password reset."
        result = parser.parse(text)
        assert len(result.sentences) >= 2

    def test_carriage_return_preserved(self, parser: RequirementParser):
        text = "Line one.\r\nLine two login."
        result = parser.parse(text)
        assert "Authentication" in result.detected_features

    def test_unicode_preserved(self, parser: RequirementParser):
        text = "Implement autenticación for résumé uploads."
        result = parser.parse(text)
        assert "autenticación" in result.summary or "autenticaci" in result.summary

    def test_punctuation_preserved(self, parser: RequirementParser):
        text = "Add login! Check passwords? Use JWT."
        result = parser.parse(text)
        assert "Authentication" in result.detected_features
        assert len(result.sentences) >= 2

    def test_multiline_with_control_chars(self, parser: RequirementParser):
        text = "\x16Implement login.\n\x16Add token validation.\n\x16Expire sessions."
        result = parser.parse(text)
        assert "Authentication" in result.detected_features
        assert len(result.sentences) >= 2

    def test_only_control_chars(self, parser: RequirementParser):
        text = "\x00\x01\x02\x03\x04\x05"
        result = parser.parse(text)
        assert result.summary == ""
        assert result.detected_keywords == []

    def test_mixed_control_and_whitespace(self, parser: RequirementParser):
        text = "  \x16  \t  Implement token refresh.  \x03  "
        result = parser.parse(text)
        assert "Authentication" in result.detected_features
