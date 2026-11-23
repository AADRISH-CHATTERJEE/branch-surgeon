"""Provider contract for swappable embedding backends."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Interface for embedding backends (local ST, OpenAI, Voyage, Azure, …)."""

    @property
    def model_name(self) -> str:
        """Configured model identifier."""
        ...

    def embed_text(self, text: str) -> list[float]:
        """Embed a single text string."""
        ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts (order-preserving)."""
        ...
