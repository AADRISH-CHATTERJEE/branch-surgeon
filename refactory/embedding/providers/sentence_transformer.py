"""Sentence Transformers embedding provider (local, offline after model download)."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, ClassVar

from refactory.core.exceptions import EmbeddingError

if TYPE_CHECKING:
    from loguru import Logger
    from sentence_transformers import SentenceTransformer


class SentenceTransformerProvider:
    """Lazy-loading wrapper around ``sentence_transformers.SentenceTransformer``.

    Loaded weights are cached **per process** (and model name) so multiple
    provider instances — e.g. from repeated ``build_container()`` calls —
    reuse the same in-memory model.
    """

    _models: ClassVar[dict[str, "SentenceTransformer"]] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, model_name: str, logger: "Logger") -> None:
        self._model_name = model_name
        self._logger = logger
        self._model: "SentenceTransformer | None" = None

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed_text(self, text: str) -> list[float]:
        vectors = self.embed_batch([text])
        return vectors[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get_model()
        try:
            # normalize_embeddings keeps vectors comparable for later retrieval
            raw = model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingError(f"SentenceTransformer encode failed: {exc}") from exc

        # Convert numpy / tensor rows to plain Python lists
        return [self._to_float_list(row) for row in raw]

    def _get_model(self) -> "SentenceTransformer":
        """Return the process-wide model for ``self._model_name`` (load once)."""
        cached = type(self)._models.get(self._model_name)
        if cached is not None:
            self._logger.debug("Reusing loaded embedding model {}", self._model_name)
            self._model = cached
            return cached

        with type(self)._lock:
            cached = type(self)._models.get(self._model_name)
            if cached is not None:
                self._logger.debug("Reusing loaded embedding model {}", self._model_name)
                self._model = cached
                return cached

            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise EmbeddingError(
                    "sentence-transformers is not installed. "
                    "Install with: pip install sentence-transformers"
                ) from exc

            self._logger.info("Loading embedding model {}", self._model_name)
            try:
                model = SentenceTransformer(self._model_name)
            except Exception as exc:  # noqa: BLE001
                raise EmbeddingError(
                    f"Failed to load embedding model {self._model_name!r}: {exc}"
                ) from exc

            type(self)._models[self._model_name] = model
            self._model = model
            return model

    # Backwards-compatible alias used by older call sites / tests.
    def _ensure_model(self) -> "SentenceTransformer":
        return self._get_model()

    @classmethod
    def reset_model_cache(cls) -> None:
        """Clear the process-wide model cache (tests only)."""
        with cls._lock:
            cls._models.clear()

    @staticmethod
    def _to_float_list(row: object) -> list[float]:
        if hasattr(row, "tolist"):
            values = row.tolist()  # type: ignore[union-attr]
            return [float(v) for v in values]
        return [float(v) for v in list(row)]  # type: ignore[arg-type]
