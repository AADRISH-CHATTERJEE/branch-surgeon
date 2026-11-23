"""RequirementParser — deterministic keyword and feature extraction.

No ML. No AI. Pure text heuristics: split sentences, extract technical
nouns/verbs, detect domain categories (auth, database, API, etc.).
"""

from __future__ import annotations

import re
from typing import Sequence

from refactory.requirement.models import RequirementSummary


# ---------------------------------------------------------------
# Domain vocabularies
# ---------------------------------------------------------------

_AUTH_TERMS = frozenset({
    "auth", "authenticate", "authentication", "authorization", "authorize",
    "login", "logout", "signin", "signup", "sign-in", "sign-up",
    "password", "credential", "jwt", "token", "oauth", "oauth2",
    "session", "sso", "mfa", "2fa", "otp", "totp", "role", "roles",
    "permission", "permissions", "access", "acl", "rbac", "abac",
    "identity", "principal", "claim", "scope", "refresh",
})

_DATABASE_TERMS = frozenset({
    "database", "db", "sql", "query", "migration", "migrate",
    "schema", "table", "column", "index", "foreign", "primary",
    "postgres", "postgresql", "mysql", "sqlite", "redis",
    "mongodb", "mongo", "dynamo", "dynamodb", "orm", "model",
    "repository", "dao", "entity", "relation", "join", "aggregate",
    "transaction", "cursor", "connection", "pool",
})

_API_TERMS = frozenset({
    "api", "rest", "graphql", "grpc", "endpoint", "route", "router",
    "controller", "handler", "middleware", "request", "response",
    "http", "https", "websocket", "webhook", "rpc", "url", "uri",
    "get", "post", "put", "patch", "delete", "head", "options",
    "status", "header", "cors", "rate", "limit", "throttle",
})

_SECURITY_TERMS = frozenset({
    "security", "encrypt", "decrypt", "encryption", "hash", "hashing",
    "salt", "bcrypt", "argon", "sha", "hmac", "secret", "vault",
    "certificate", "ssl", "tls", "xss", "csrf", "injection",
    "sanitize", "validate", "audit", "compliance", "firewall",
    "vulnerability", "cve", "penetration",
})

_CONFIG_TERMS = frozenset({
    "config", "configuration", "setting", "settings", "env",
    "environment", "variable", "dotenv", "yaml", "toml", "json",
    "ini", "properties", "feature", "flag", "toggle",
})

_EMAIL_TERMS = frozenset({
    "email", "mail", "smtp", "notification", "notify", "send",
    "template", "newsletter", "subscribe", "unsubscribe", "inbox",
})

_CACHE_TERMS = frozenset({
    "cache", "caching", "redis", "memcached", "ttl", "invalidate",
    "evict", "warm", "preload", "lru", "memoize",
})

_TESTING_TERMS = frozenset({
    "test", "tests", "testing", "pytest", "unittest", "mock",
    "fixture", "assert", "coverage", "ci", "integration",
    "e2e", "end-to-end", "acceptance", "regression",
})

_ALL_DOMAIN_CATEGORIES: dict[str, frozenset[str]] = {
    "Authentication": _AUTH_TERMS,
    "Database": _DATABASE_TERMS,
    "API": _API_TERMS,
    "Security": _SECURITY_TERMS,
    "Configuration": _CONFIG_TERMS,
    "Email": _EMAIL_TERMS,
    "Cache": _CACHE_TERMS,
    "Testing": _TESTING_TERMS,
}

# Technical verbs that signal implementation actions
_TECHNICAL_VERBS = frozenset({
    "implement", "add", "create", "update", "delete", "remove",
    "modify", "refactor", "migrate", "integrate", "deploy",
    "configure", "validate", "sanitize", "encrypt", "decrypt",
    "authenticate", "authorize", "cache", "queue", "send",
    "receive", "parse", "serialize", "deserialize", "transform",
    "filter", "sort", "aggregate", "generate", "expire",
    "reset", "revoke", "audit", "log", "monitor", "track",
    "store", "retrieve", "upload", "download", "import",
    "export", "batch", "schedule", "retry", "throttle",
    "render", "route", "handle", "dispatch", "subscribe",
    "publish", "notify", "emit", "connect", "disconnect",
})

# File-hint patterns
_FILE_HINT_RE = re.compile(
    r"\b([\w/\\]+\.(?:py|js|ts|java|go|rs|rb|css|html|sql|yml|yaml|json|toml|md|txt))\b",
    re.IGNORECASE,
)

# Sentence splitting
_SENTENCE_RE = re.compile(r"[.!?]\s+|\n+")


_CONTROL_CHAR_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]",
)


class RequirementParser:
    """Deterministic parser: extract keywords, features, and file hints
    from plain English requirement text."""

    def parse(self, raw_text: str) -> RequirementSummary:
        text = self._sanitize(raw_text or "").strip()
        if not text:
            return RequirementSummary()

        sentences = self._split_sentences(text)
        summary = sentences[0] if sentences else text[:200]
        tokens = self._tokenize(text)

        keywords = self._extract_keywords(tokens)
        features = self._detect_features(tokens)
        file_hints = self._extract_file_hints(text)
        verbs = self._extract_verbs(tokens)

        return RequirementSummary(
            summary=summary,
            detected_features=features,
            detected_keywords=keywords,
            sentences=sentences,
            file_hints=file_hints,
            technical_verbs=verbs,
        )

    # ---------------------------------------------------------------
    # Internals
    # ---------------------------------------------------------------

    @staticmethod
    def _sanitize(text: str) -> str:
        """Strip non-printable control characters (preserve \\n, \\r, \\t, Unicode)."""
        return _CONTROL_CHAR_RE.sub("", text)

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        raw = _SENTENCE_RE.split(text)
        return [s.strip() for s in raw if s.strip()]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        words = re.findall(r"[a-zA-Z][a-zA-Z0-9_]*", text)
        return [w.lower() for w in words]

    @staticmethod
    def _extract_keywords(tokens: list[str]) -> list[str]:
        all_domain = set()
        for terms in _ALL_DOMAIN_CATEGORIES.values():
            all_domain |= terms
        all_domain |= _TECHNICAL_VERBS

        seen: set[str] = set()
        result: list[str] = []
        for tok in tokens:
            if tok in all_domain and tok not in seen:
                seen.add(tok)
                result.append(tok)
        return result

    @staticmethod
    def _detect_features(tokens: list[str]) -> list[str]:
        token_set = set(tokens)
        features: list[str] = []
        for category, terms in _ALL_DOMAIN_CATEGORIES.items():
            if token_set & terms:
                features.append(category)
        return sorted(features)

    @staticmethod
    def _extract_file_hints(text: str) -> list[str]:
        return list(dict.fromkeys(_FILE_HINT_RE.findall(text)))

    @staticmethod
    def _extract_verbs(tokens: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for tok in tokens:
            if tok in _TECHNICAL_VERBS and tok not in seen:
                seen.add(tok)
                result.append(tok)
        return result
