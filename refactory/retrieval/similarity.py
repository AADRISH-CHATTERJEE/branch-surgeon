"""Pluggable similarity metrics for vector retrieval.

RetrievalService depends on SimilarityMetric, not a concrete formula.
"""

from __future__ import annotations

import math
from typing import Protocol, runtime_checkable

from refactory.core.exceptions import RefactoryError


class SimilarityError(RefactoryError):
    """Invalid vectors for similarity computation."""


@runtime_checkable
class SimilarityMetric(Protocol):
    """Contract for scoring two equal-length embedding vectors."""

    @property
    def name(self) -> str:
        ...

    def score(self, left: list[float], right: list[float]) -> float:
        """Higher is more similar."""
        ...


def _validate_pair(left: list[float], right: list[float]) -> None:
    if not left or not right:
        raise SimilarityError("Cannot score empty embedding vectors")
    if len(left) != len(right):
        raise SimilarityError(
            f"Embedding dimension mismatch: {len(left)} vs {len(right)}"
        )


class CosineSimilarity:
    """Cosine similarity in [-1, 1] (1 = identical direction)."""

    @property
    def name(self) -> str:
        return "cosine"

    def score(self, left: list[float], right: list[float]) -> float:
        _validate_pair(left, right)
        dot = 0.0
        left_norm = 0.0
        right_norm = 0.0
        for a, b in zip(left, right, strict=True):
            dot += a * b
            left_norm += a * a
            right_norm += b * b
        if left_norm == 0.0 or right_norm == 0.0:
            raise SimilarityError("Cannot compute cosine similarity for a zero vector")
        return dot / (math.sqrt(left_norm) * math.sqrt(right_norm))


class DotProductSimilarity:
    """Raw dot product (useful for already-normalized embeddings)."""

    @property
    def name(self) -> str:
        return "dot"

    def score(self, left: list[float], right: list[float]) -> float:
        _validate_pair(left, right)
        return sum(a * b for a, b in zip(left, right, strict=True))


class EuclideanSimilarity:
    """Negative Euclidean distance so higher scores mean closer vectors."""

    @property
    def name(self) -> str:
        return "euclidean"

    def score(self, left: list[float], right: list[float]) -> float:
        _validate_pair(left, right)
        dist_sq = sum((a - b) ** 2 for a, b in zip(left, right, strict=True))
        return -math.sqrt(dist_sq)


_METRICS: dict[str, type] = {
    "cosine": CosineSimilarity,
    "dot": DotProductSimilarity,
    "dot_product": DotProductSimilarity,
    "euclidean": EuclideanSimilarity,
}


def get_similarity_metric(name: str = "cosine") -> SimilarityMetric:
    """Resolve a metric by name (default: cosine)."""
    key = name.strip().lower().replace("-", "_")
    try:
        cls = _METRICS[key]
    except KeyError as exc:
        known = ", ".join(sorted({"cosine", "dot", "euclidean"}))
        raise SimilarityError(f"Unknown similarity metric {name!r}. Choose from: {known}") from exc
    return cls()
