"""Verify the DI container builds and wires the foundation graph."""

from __future__ import annotations

from refactory.ai.gateway import AIGateway
from refactory.ai.providers.mock import MockProvider
from refactory.ai.service import AIService
from refactory.core.container import build_container
from refactory.embedding.interfaces import EmbeddingProvider
from refactory.embedding.providers import SentenceTransformerProvider
from refactory.embedding.service import EmbeddingService
from refactory.analysis.service import RepositoryAnalysisService
from refactory.codesearch.service import CodeSearchService
from refactory.impact.service import ImpactAnalysisService
from refactory.testing.service import TestIntelligenceService
from refactory.documentation.service import DocumentationService
from refactory.git.commit_service import CommitService
from refactory.git.service import GitService
from refactory.github.service import GitHubService
from refactory.graph.service import RepositoryGraphService
from refactory.indexer.service import IndexerService
from refactory.parser.service import ParserService
from refactory.prompt.builder import PromptBuilder
from refactory.response.parser import ResponseParser as ReviewResponseParser
from refactory.retrieval.service import RetrievalService
from refactory.review.engine import ReviewEngine
from refactory.storage.chroma import ChromaStore


def test_build_container_returns_wired_services():
    from refactory.core.config import Settings

    container = build_container(
        settings=Settings().model_copy(update={"ai_provider": "mock"})
    )

    assert isinstance(container.git_service, GitService)
    assert isinstance(container.commit_service, CommitService)
    assert isinstance(container.repository_analysis_service, RepositoryAnalysisService)
    assert isinstance(container.github_service, GitHubService)
    assert isinstance(container.code_search_service, CodeSearchService)
    assert isinstance(container.impact_analysis_service, ImpactAnalysisService)
    assert isinstance(container.test_intelligence_service, TestIntelligenceService)
    assert isinstance(container.documentation_service, DocumentationService)
    assert isinstance(container.parser_service, ParserService)
    assert isinstance(container.embedding_provider, SentenceTransformerProvider)
    assert isinstance(container.embedding_service, EmbeddingService)
    assert isinstance(container.chroma_store, ChromaStore)
    assert isinstance(container.indexer_service, IndexerService)
    assert isinstance(container.graph_service, RepositoryGraphService)
    assert isinstance(container.retrieval_service, RetrievalService)
    assert isinstance(container.prompt_builder, PromptBuilder)
    assert isinstance(container.review_response_parser, ReviewResponseParser)
    assert isinstance(container.ai_gateway, AIGateway)
    assert isinstance(container.ai_gateway.provider, MockProvider)
    assert isinstance(container.ai_service, AIService)
    assert isinstance(container.review_engine, ReviewEngine)


def test_review_engine_receives_injected_dependencies():
    container = build_container()
    engine = container.review_engine

    assert engine._git is container.git_service
    assert engine._github is container.github_service
    assert engine._parser is container.parser_service
    assert engine._indexer is container.indexer_service
    assert engine._retrieval is container.retrieval_service
    assert engine._ai is container.ai_service
    assert engine._graph is container.graph_service
    assert engine._prompt_builder is container.prompt_builder
    assert engine._gateway is container.ai_gateway
    assert engine._response_parser is container.review_response_parser
    # Analysis is independent of the review pipeline.
    assert not hasattr(engine, "_analysis")
    assert container.repository_analysis_service._commits is container.commit_service
    assert container.repository_analysis_service._git is container.git_service
    assert container.code_search_service._indexer is container.indexer_service
    assert container.code_search_service._graph is container.graph_service
    assert container.code_search_service._retrieval is container.retrieval_service
    assert container.code_search_service._parser is container.parser_service
    assert container.impact_analysis_service._indexer is container.indexer_service
    assert container.impact_analysis_service._graph is container.graph_service
    assert container.impact_analysis_service._retrieval is container.retrieval_service
    assert not hasattr(container.review_engine, "_impact")
    assert container.test_intelligence_service._impact is container.impact_analysis_service
    assert container.test_intelligence_service._search is container.code_search_service
    assert container.test_intelligence_service._commits is container.commit_service
    assert not hasattr(container.review_engine, "_testing")
    assert container.documentation_service._indexer is container.indexer_service
    assert container.documentation_service._parser is container.parser_service
    assert container.documentation_service._testing is container.test_intelligence_service
    assert not hasattr(container.review_engine, "_documentation")


def test_embedding_service_uses_injected_provider():
    container = build_container()
    assert isinstance(container.embedding_provider, EmbeddingProvider)
    assert container.embedding_service._provider is container.embedding_provider


def test_retrieval_service_uses_provider_not_chroma():
    container = build_container()
    assert container.retrieval_service._provider is container.embedding_provider
    assert getattr(container.retrieval_service, "_store", None) is None


def test_backend_client_is_lazy_and_not_on_review_engine():
    container = build_container()
    assert container._backend_client is None
    client = container.get_backend_client()
    assert client is not None
    assert not hasattr(container.review_engine, "_backend")


def test_prompt_builder_shares_lazy_backend_client_factory():
    container = build_container()
    assert container.prompt_builder._backend_client is None
    assert callable(container.prompt_builder._backend_client_factory)
    assert container.prompt_builder._get_backend_client() is container.get_backend_client()
    assert container._backend_client is not None


def test_indexer_is_wired_with_parser_via_di():
    container = build_container()
    indexer = container.indexer_service

    assert indexer._parser is container.parser_service
    assert indexer._ignore_dirs == container.settings.ignore_dirs
