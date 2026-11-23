"""Review domain package — models always; engine via lazy export."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from refactory.review.models import (
    Repository,
    RepositorySummary,
    ReviewResult,
    ReviewSuggestion,
)

if TYPE_CHECKING:
    from refactory.review.engine import ReviewEngine as ReviewEngine

__all__ = [
    "ReviewEngine",
    "Repository",
    "RepositorySummary",
    "ReviewResult",
    "ReviewSuggestion",
]


def __getattr__(name: str) -> Any:
    if name == "ReviewEngine":
        from refactory.review.engine import ReviewEngine

        return ReviewEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
