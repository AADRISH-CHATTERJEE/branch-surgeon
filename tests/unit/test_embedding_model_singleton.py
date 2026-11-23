"""Regression tests: embedding model loads once per process."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from refactory.core.logger import get_service_logger
from refactory.embedding.providers.sentence_transformer import SentenceTransformerProvider


@pytest.fixture(autouse=True)
def _clear_model_cache():
    SentenceTransformerProvider.reset_model_cache()
    yield
    SentenceTransformerProvider.reset_model_cache()


def _logger():
    return get_service_logger("test.embedding.singleton")


def _fake_model_factory():
    """Build a fresh mock model each time SentenceTransformer(...) is called."""
    call_count = {"n": 0}

    def factory(name: str):
        call_count["n"] += 1
        model = MagicMock(name=f"FakeST:{name}:{call_count['n']}")
        model.encode.return_value = [[0.1, 0.2, 0.3]]
        return model

    factory.call_count = call_count  # type: ignore[attr-defined]
    return factory


def test_model_loads_exactly_once():
    factory = _fake_model_factory()
    logger = MagicMock()
    with patch(
        "sentence_transformers.SentenceTransformer",
        side_effect=factory,
    ):
        provider = SentenceTransformerProvider("BAAI/bge-small-en-v1.5", logger)
        provider.embed_text("one")
        provider.embed_text("two")
        provider.embed_batch(["a", "b"])

    assert factory.call_count["n"] == 1
    logger.info.assert_called()
    assert any(
        "Loading embedding model" in str(call)
        for call in logger.info.call_args_list
    )


def test_multiple_provider_instances_reuse_same_model():
    factory = _fake_model_factory()
    with patch(
        "sentence_transformers.SentenceTransformer",
        side_effect=factory,
    ):
        a = SentenceTransformerProvider("BAAI/bge-small-en-v1.5", _logger())
        b = SentenceTransformerProvider("BAAI/bge-small-en-v1.5", _logger())
        a.embed_text("query-a")
        b.embed_text("query-b")
        assert a._get_model() is b._get_model()

    assert factory.call_count["n"] == 1


def test_reuse_logs_debug_not_info():
    factory = _fake_model_factory()
    logger = MagicMock()
    with patch(
        "sentence_transformers.SentenceTransformer",
        side_effect=factory,
    ):
        provider = SentenceTransformerProvider("BAAI/bge-small-en-v1.5", logger)
        provider.embed_text("first")
        logger.info.reset_mock()
        logger.debug.reset_mock()
        provider.embed_text("second")

    logger.info.assert_not_called()
    assert any(
        "Reusing loaded embedding model" in str(call)
        for call in logger.debug.call_args_list
    )


def test_retrieval_service_reuses_provider_model():
    from refactory.retrieval.service import RetrievalService

    factory = _fake_model_factory()
    provider = SentenceTransformerProvider("BAAI/bge-small-en-v1.5", _logger())

    with patch(
        "sentence_transformers.SentenceTransformer",
        side_effect=factory,
    ):
        retrieval = RetrievalService(embedding_provider=provider, logger=_logger())
        retrieval._provider.embed_text("alpha")
        retrieval._provider.embed_text("beta")
        # Second provider instance (as if container rebuilt) shares cache.
        other = SentenceTransformerProvider("BAAI/bge-small-en-v1.5", _logger())
        other.embed_text("gamma")

    assert factory.call_count["n"] == 1


def test_review_pipeline_container_rebuild_reuses_model():
    """Simulates repeated build_container() creating new provider instances."""
    from refactory.core.config import Settings
    from refactory.core.container import build_container

    factory = _fake_model_factory()
    with patch(
        "sentence_transformers.SentenceTransformer",
        side_effect=factory,
    ):
        settings = Settings().model_copy(update={"ai_provider": "mock"})
        c1 = build_container(settings=settings)
        c2 = build_container(settings=settings)
        assert c1.embedding_provider is not c2.embedding_provider
        c1.embedding_provider.embed_text("review-query-1")
        c2.embedding_provider.embed_text("review-query-2")
        # Review engine shares the container provider.
        c1.review_engine  # touch
        assert c1.embedding_provider._get_model() is c2.embedding_provider._get_model()

    assert factory.call_count["n"] == 1


def test_different_model_names_load_separately():
    factory = _fake_model_factory()
    with patch(
        "sentence_transformers.SentenceTransformer",
        side_effect=factory,
    ):
        a = SentenceTransformerProvider("model-a", _logger())
        b = SentenceTransformerProvider("model-b", _logger())
        a.embed_text("x")
        b.embed_text("y")

    assert factory.call_count["n"] == 2
