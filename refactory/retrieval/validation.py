"""Embedding quality validation helpers.

Evaluation-only tooling — does NOT change runtime behavior.
Computes Precision@K, recall notes, and semantic relevance metrics
to help tune embedding weights in review/impact/related pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from refactory.retrieval.service import RetrievalService


@dataclass
class ValidationCase:
    """A single evaluation query with expected results."""

    query: str
    expected_files: list[str]
    expected_symbols: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class PrecisionResult:
    """Precision@K result for one validation case."""

    query: str
    k: int
    retrieved: list[str]
    relevant: list[str]
    precision: float
    recall: float
    notes: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    """Aggregate validation output."""

    cases: list[PrecisionResult]
    mean_precision: float
    mean_recall: float
    notes: list[str] = field(default_factory=list)


# Pre-built validation cases for common domains
AUTH_TOKEN_CASES: list[ValidationCase] = [
    ValidationCase(
        query="authentication",
        expected_files=["auth.py", "auth/service.py", "auth_service.py"],
        expected_symbols=["AuthService", "authenticate", "login"],
        description="Core auth module should appear for 'authentication'",
    ),
    ValidationCase(
        query="token validation",
        expected_files=["auth.py", "token.py", "auth/token.py"],
        expected_symbols=["validate_token", "TokenValidator", "verify_token"],
        description="Token-related symbols should surface",
    ),
    ValidationCase(
        query="password reset",
        expected_files=["auth.py", "password.py", "auth/password.py"],
        expected_symbols=["reset_password", "PasswordReset"],
        description="Password reset flows",
    ),
    ValidationCase(
        query="session management",
        expected_files=["session.py", "auth/session.py"],
        expected_symbols=["SessionManager", "create_session"],
        description="Session-related modules",
    ),
]


def precision_at_k(
    retrieved: list[str],
    relevant: set[str],
    k: int,
) -> float:
    """Compute Precision@K: fraction of top-K results that are relevant."""
    if k <= 0:
        return 0.0
    top = retrieved[:k]
    if not top:
        return 0.0
    hits = sum(1 for item in top if _matches_any(item, relevant))
    return hits / len(top)


def recall_at_k(
    retrieved: list[str],
    relevant: set[str],
    k: int,
) -> float:
    """Compute Recall@K: fraction of relevant items found in top-K."""
    if not relevant:
        return 1.0
    top = retrieved[:k]
    hits = sum(1 for item in top if _matches_any(item, relevant))
    return hits / len(relevant)


def evaluate_retrieval(
    retrieval: "RetrievalService",
    cases: list[ValidationCase],
    *,
    root: Path | str | None = None,
    k: int = 5,
) -> ValidationReport:
    """Run validation cases against a retrieval service.

    Returns a report with per-case Precision@K, Recall@K, and aggregate
    metrics useful for tuning embedding parameters.
    """
    results: list[PrecisionResult] = []

    for case in cases:
        retrieved_paths: list[str] = []
        try:
            search_result = retrieval.search(case.query, top_k=k, root=root)
            for hit in search_result.hits:
                retrieved_paths.append(hit.file_path)
        except Exception:  # noqa: BLE001
            pass

        relevant = set(case.expected_files + case.expected_symbols)

        prec = precision_at_k(retrieved_paths, relevant, k)
        rec = recall_at_k(retrieved_paths, relevant, k)

        notes: list[str] = []
        if prec == 0.0:
            notes.append(f"No relevant results in top-{k} for '{case.query}'")
        if case.description:
            notes.append(case.description)

        results.append(PrecisionResult(
            query=case.query,
            k=k,
            retrieved=retrieved_paths[:k],
            relevant=list(relevant),
            precision=round(prec, 4),
            recall=round(rec, 4),
            notes=notes,
        ))

    mean_prec = sum(r.precision for r in results) / max(len(results), 1)
    mean_rec = sum(r.recall for r in results) / max(len(results), 1)

    report_notes: list[str] = []
    if mean_prec < 0.3:
        report_notes.append(
            "Low mean precision — consider re-embedding or adjusting chunking"
        )
    if mean_rec < 0.3:
        report_notes.append(
            "Low mean recall — expected modules not surfacing in top-K"
        )

    return ValidationReport(
        cases=results,
        mean_precision=round(mean_prec, 4),
        mean_recall=round(mean_rec, 4),
        notes=report_notes,
    )


def _matches_any(item: str, relevant: set[str]) -> bool:
    """Fuzzy match: check if item path/symbol matches any relevant entry."""
    item_lower = item.lower().replace("\\", "/")
    for r in relevant:
        r_lower = r.lower().replace("\\", "/")
        if r_lower in item_lower or item_lower.endswith(r_lower):
            return True
        stem = Path(r_lower).stem
        if stem and stem in item_lower:
            return True
    return False
