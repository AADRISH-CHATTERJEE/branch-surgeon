"""Dependency injection container.

Constructs and wires infrastructure → services → ReviewEngine.
Presentation layers (CLI / future FastAPI) should only talk to this container
(or to engine/services obtained from it) — never construct graphs ad hoc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from refactory.analysis.service import RepositoryAnalysisService
from refactory.ai.gateway import AIGateway
from refactory.ai.providers import build_ai_provider_pair
from refactory.ai.response_parser import ResponseParser
from refactory.ai.service import AIService
from refactory.cache.store import DeterministicCache, NullCache
from refactory.codesearch.service import CodeSearchService
from refactory.company.checker import CompanyRulesChecker
from refactory.core.config import Settings, get_settings
from refactory.core.logger import get_service_logger, setup_logging
from refactory.history.service import AnalysisHistoryService
from refactory.organization.catalog import get_catalog_session_factory
from refactory.organization.management_service import OrganizationManagementService
from refactory.organization.service import OrganizationRuleService
from refactory.documentation.service import DocumentationService
from refactory.embedding.interfaces import EmbeddingProvider
from refactory.embedding.providers import SentenceTransformerProvider
from refactory.embedding.service import EmbeddingService
from refactory.git.commit_service import CommitService
from refactory.git.service import GitService
from refactory.github.service import GitHubService
from refactory.graph.service import RepositoryGraphService
from refactory.impact.service import ImpactAnalysisService
from refactory.indexer.service import IndexerService
from refactory.parser.service import ParserService
from refactory.policies.service import ArchitecturePolicyService
from refactory.prompt.builder import PromptBuilder
from refactory.refactor.service import RefactoringService
from refactory.prompt.budget import ContextBudget
from refactory.response.parser import ResponseParser as ReviewResponseParser
from refactory.retrieval.service import RetrievalService
from refactory.review.engine import ReviewEngine
from refactory.requirement.parser import RequirementParser
from refactory.requirement.planner import ImplementationPlanner
from refactory.requirement.search import RequirementSearch
from refactory.requirement.service import RequirementAnalysisService
from refactory.rules.engine import RuleEngine
from refactory.storage.chroma import ChromaStore
from refactory.surgeon.service import BranchSurgeonService
from refactory.intelligence.service import AIIntelligenceService
from refactory.intelligence.session import SessionContext
from refactory.testing.service import TestIntelligenceService
from refactory.cache.repository_cache import RepositoryCache
from refactory.core.profiler import PerformanceProfiler
from refactory.indexer.background import BackgroundIndexer
from refactory.pr.service import PRIntelligenceService
from refactory.prompts import PromptTemplateService
from refactory.recommendation.patch_apply_service import PatchService
from refactory.recommendation.patch_service import RecommendationPatchService
from refactory.recommendation.post_transformation import PostTransformationPipeline
from refactory.recommendation.recommendation_service import RecommendationService
from refactory.recommendation.service import RecommendationEngine
from refactory.recommendation.stats import RecommendationStatsService
from refactory.review.suggestion_status import ReviewSuggestionStatusService
from refactory.db.database import DatabaseManager
from refactory.db.persistence import PersistenceService
from refactory.db.query_service import RepositoryQueryService
from refactory.db.session import SessionFactory
from refactory.storage.service import StorageService
from refactory.transformation.service import TransformationService
from refactory.workspace.manager import WorkspaceManager

if TYPE_CHECKING:
    from refactory.backend.client import BackendClient


@dataclass
class ServiceContainer:
    """Holds constructed services for the current process/session."""

    settings: Settings
    git_service: GitService
    commit_service: CommitService
    repository_analysis_service: RepositoryAnalysisService
    github_service: GitHubService
    parser_service: ParserService
    embedding_provider: EmbeddingProvider
    embedding_service: EmbeddingService
    chroma_store: ChromaStore
    indexer_service: IndexerService
    graph_service: RepositoryGraphService
    retrieval_service: RetrievalService
    code_search_service: CodeSearchService
    impact_analysis_service: ImpactAnalysisService
    test_intelligence_service: TestIntelligenceService
    documentation_service: DocumentationService
    branch_surgeon_service: BranchSurgeonService
    requirement_analysis_service: RequirementAnalysisService
    refactoring_service: RefactoringService
    ai_intelligence_service: AIIntelligenceService
    session_context: SessionContext
    repository_cache: RepositoryCache
    workspace_manager: WorkspaceManager
    background_indexer: BackgroundIndexer
    performance_profiler: PerformanceProfiler
    pr_intelligence_service: PRIntelligenceService
    storage_service: StorageService
    rule_engine: RuleEngine
    architecture_policy_service: ArchitecturePolicyService
    company_rules_checker: CompanyRulesChecker
    organization_rule_service: OrganizationRuleService
    organization_management_service: OrganizationManagementService
    analysis_history_service: AnalysisHistoryService
    prompt_template_service: PromptTemplateService
    recommendation_engine: RecommendationEngine
    recommendation_patch_service: RecommendationPatchService
    patch_service: PatchService
    recommendation_service: RecommendationService
    recommendation_stats_service: RecommendationStatsService
    review_suggestion_status_service: ReviewSuggestionStatusService
    post_transformation_pipeline: PostTransformationPipeline
    transformation_service: TransformationService
    database_manager: DatabaseManager
    session_factory: SessionFactory
    persistence_service: PersistenceService
    query_service: RepositoryQueryService
    prompt_builder: PromptBuilder
    review_response_parser: ReviewResponseParser
    ai_gateway: AIGateway
    ai_service: AIService
    review_engine: ReviewEngine
    _backend_client: "BackendClient | None" = field(default=None, init=False, repr=False)

    def get_backend_client(self) -> "BackendClient | None":
        """Lazily construct BackendClient when ``backend.url`` is configured.

        Local commands (review/search/embed) may call this without requiring login.
        Returns None when the control plane URL is disabled.
        """
        from refactory.backend.auth import TokenStore
        from refactory.backend.client import BackendClient

        url = self.settings.backend.url
        if not url:
            return None
        if self._backend_client is None:
            self._backend_client = BackendClient(
                base_url=url,
                token_store=TokenStore(),
                logger=get_service_logger("backend", self.settings.logging.level),
            )
        return self._backend_client

    def require_backend_client(self) -> "BackendClient":
        from refactory.backend.exceptions import BackendNotConfiguredError

        client = self.get_backend_client()
        if client is None:
            raise BackendNotConfiguredError(
                "Backend URL is not configured. Set REFACTORY_BACKEND_URL."
            )
        return client


def build_container(
    settings: Settings | None = None,
    *,
    repo_root: Path | None = None,
) -> ServiceContainer:
    """Build a fully wired application graph."""
    settings = settings or get_settings()
    ai = settings.ai
    cache_cfg = settings.cache
    prompt_cfg = settings.prompt
    github_cfg = settings.github
    embedding_cfg = settings.embedding
    logging_cfg = settings.logging

    setup_logging(logging_cfg.level)

    root = (repo_root or Path.cwd()).resolve()
    cache_dir = cache_cfg.dir(root)
    shared_cache = (
        DeterministicCache(enabled=True, disk_dir=cache_dir, namespace="pipeline")
        if cache_cfg.enabled
        else NullCache()
    )

    git_service = GitService(
        logger=get_service_logger("git", logging_cfg.level),
        path=root,
        allow_parent_discovery=False,
    )
    commit_service = CommitService(
        logger=get_service_logger("commit", logging_cfg.level),
        path=root,
    )
    github_service = GitHubService(
        settings=github_cfg,
        logger=get_service_logger("github", logging_cfg.level),
    )
    parser_service = ParserService(
        ignore_dirs=settings.ignore_dirs,
        logger=get_service_logger("parser", logging_cfg.level),
    )
    embedding_provider: EmbeddingProvider = SentenceTransformerProvider(
        model_name=embedding_cfg.model,
        logger=get_service_logger("embedding.provider", logging_cfg.level),
    )
    chroma_store = ChromaStore(
        persist_path=embedding_cfg.chroma_dir(root),
        collection_name="refactory_code",
        logger=get_service_logger("storage", logging_cfg.level),
    )

    database_manager = DatabaseManager(
        repo_root=root,
        logger=get_service_logger("db", logging_cfg.level),
    )
    database_manager.create_all()
    session_factory = SessionFactory(database_manager.engine)
    persistence_service = PersistenceService(
        session_factory,
        logger=get_service_logger("persistence", logging_cfg.level),
    )
    query_service = RepositoryQueryService(
        session_factory,
        logger=get_service_logger("query", logging_cfg.level),
    )

    embedding_service = EmbeddingService(
        provider=embedding_provider,
        logger=get_service_logger("embedding", logging_cfg.level),
        settings=embedding_cfg,
        persistence_service=persistence_service,
    )

    indexer_service = IndexerService(
        parser_service=parser_service,
        ignore_dirs=settings.ignore_dirs,
        logger=get_service_logger("indexer", logging_cfg.level),
        persistence_service=persistence_service,
    )
    graph_service = RepositoryGraphService(
        logger=get_service_logger("graph", logging_cfg.level),
        cache=shared_cache,
        persistence_service=persistence_service,
    )

    repository_analysis_service = RepositoryAnalysisService(
        logger=get_service_logger("analysis", logging_cfg.level),
        git_service=git_service,
        commit_service=commit_service,
        parser_service=parser_service,
        indexer_service=indexer_service,
        graph_service=graph_service,
        ignore_dirs=settings.ignore_dirs,
    )

    retrieval_service = RetrievalService(
        embedding_provider=embedding_provider,
        logger=get_service_logger("retrieval", logging_cfg.level),
        cache=shared_cache,
    )

    code_search_service = CodeSearchService(
        logger=get_service_logger("codesearch", logging_cfg.level),
        git_service=git_service,
        indexer_service=indexer_service,
        graph_service=graph_service,
        parser_service=parser_service,
        retrieval_service=retrieval_service,
    )

    impact_analysis_service = ImpactAnalysisService(
        logger=get_service_logger("impact", logging_cfg.level),
        git_service=git_service,
        indexer_service=indexer_service,
        graph_service=graph_service,
        parser_service=parser_service,
        retrieval_service=retrieval_service,
    )

    test_intelligence_service = TestIntelligenceService(
        logger=get_service_logger("testing", logging_cfg.level),
        git_service=git_service,
        commit_service=commit_service,
        parser_service=parser_service,
        indexer_service=indexer_service,
        graph_service=graph_service,
        impact_analysis_service=impact_analysis_service,
        repository_analysis_service=repository_analysis_service,
        code_search_service=code_search_service,
    )

    documentation_service = DocumentationService(
        logger=get_service_logger("documentation", logging_cfg.level),
        git_service=git_service,
        commit_service=commit_service,
        parser_service=parser_service,
        indexer_service=indexer_service,
        graph_service=graph_service,
        repository_analysis_service=repository_analysis_service,
        impact_analysis_service=impact_analysis_service,
        code_search_service=code_search_service,
        test_intelligence_service=test_intelligence_service,
        ignore_dirs=settings.ignore_dirs,
    )

    requirement_parser = RequirementParser()
    requirement_search = RequirementSearch(
        logger=get_service_logger("requirement.search", logging_cfg.level),
        code_search_service=code_search_service,
        graph_service=graph_service,
        retrieval_service=retrieval_service,
    )
    implementation_planner = ImplementationPlanner(
        logger=get_service_logger("requirement.planner", logging_cfg.level),
        graph_service=graph_service,
    )
    requirement_analysis_service = RequirementAnalysisService(
        logger=get_service_logger("requirement", logging_cfg.level),
        parser=requirement_parser,
        search=requirement_search,
        planner=implementation_planner,
        impact_service=impact_analysis_service,
        testing_service=test_intelligence_service,
        documentation_service=documentation_service,
    )

    refactoring_service = RefactoringService(
        logger=get_service_logger("refactor", logging_cfg.level),
        parser_service=parser_service,
        indexer_service=indexer_service,
        graph_service=graph_service,
        documentation_service=documentation_service,
    )

    prompt_builder = PromptBuilder(
        logger=get_service_logger("prompt", logging_cfg.level),
        default_budget=ContextBudget.from_settings(prompt_cfg),
        cache=shared_cache,
    )
    review_response_parser = ReviewResponseParser(
        logger=get_service_logger("response.parser", logging_cfg.level)
    )
    response_parser = ResponseParser(
        logger=get_service_logger("ai.parser", logging_cfg.level)
    )
    ai_provider, ai_fallback = build_ai_provider_pair(
        ai,
        get_service_logger(f"ai.{ai.provider}", logging_cfg.level),
    )
    ai_gateway = AIGateway(
        provider=ai_provider,
        logger=get_service_logger("ai.gateway", logging_cfg.level),
        max_retries=ai.max_retries,
        fallback_provider=ai_fallback,
        timeout_seconds=ai.timeout_seconds,
        cache=shared_cache,
        cache_responses=cache_cfg.ai_responses,
    )
    ai_service = AIService(
        gateway=ai_gateway,
        prompt_builder=prompt_builder,
        response_parser=response_parser,
        logger=get_service_logger("ai", logging_cfg.level),
    )

    rule_engine = RuleEngine(
        logger=get_service_logger("rules", logging_cfg.level),
    )
    architecture_policy_service = ArchitecturePolicyService(
        logger=get_service_logger("policy", logging_cfg.level),
        parser_service=parser_service,
    )
    organization_rule_service = OrganizationRuleService(
        logger=get_service_logger("organization-rules", logging_cfg.level),
        session_factory=session_factory,
        persistence_service=persistence_service,
        query_service=query_service,
        rule_engine=rule_engine,
    )
    catalog_sessions = get_catalog_session_factory(
        logger=get_service_logger("org-catalog", logging_cfg.level),
    )
    organization_management_service = OrganizationManagementService(catalog_sessions)
    organization_management_service.ensure_defaults(local_repo_root=root)
    analysis_history_service = AnalysisHistoryService(
        logger=get_service_logger("analysis-history", logging_cfg.level),
        session_factory=session_factory,
    )
    persistence_service.set_history_service(analysis_history_service)
    company_rules_checker = CompanyRulesChecker(
        logger=get_service_logger("company-rules", logging_cfg.level),
        rule_engine=rule_engine,
        architecture_policy=architecture_policy_service,
        organization_rule_service=organization_rule_service,
    )

    review_engine = ReviewEngine(
        git_service=git_service,
        github_service=github_service,
        parser_service=parser_service,
        indexer_service=indexer_service,
        retrieval_service=retrieval_service,
        ai_service=ai_service,
        logger=get_service_logger("review", logging_cfg.level),
        graph_service=graph_service,
        prompt_builder=prompt_builder,
        ai_gateway=ai_gateway,
        response_parser=review_response_parser,
        budget=ContextBudget.from_settings(prompt_cfg),
        persistence_service=persistence_service,
        company_rules_checker=company_rules_checker,
    )

    ai_intelligence_service = AIIntelligenceService(
        logger=get_service_logger("intelligence", logging_cfg.level),
        ai_gateway=ai_gateway,
        parser_service=parser_service,
        indexer_service=indexer_service,
        graph_service=graph_service,
        impact_service=impact_analysis_service,
    )
    session_context = SessionContext(
        logger=get_service_logger("session", logging_cfg.level),
    )

    repository_cache = RepositoryCache(cache_dir=cache_dir / "repository")
    workspace_manager = WorkspaceManager(
        logger=get_service_logger("workspace", logging_cfg.level),
    )
    background_indexer = BackgroundIndexer(
        indexer_service=indexer_service,
        logger=get_service_logger("bg-indexer", logging_cfg.level),
    )
    performance_profiler = PerformanceProfiler(
        logger=get_service_logger("profiler", logging_cfg.level),
    )
    pr_intelligence_service = PRIntelligenceService(
        logger=get_service_logger("pr", logging_cfg.level),
        git_service=git_service,
        parser_service=parser_service,
        indexer_service=indexer_service,
        graph_service=graph_service,
        impact_service=impact_analysis_service,
        ai_gateway=ai_gateway,
    )

    storage_service = StorageService(
        logger=get_service_logger("storage", logging_cfg.level),
        background=True,
        repo_root=root,
    )

    prompt_template_service = PromptTemplateService()

    recommendation_stats_service = RecommendationStatsService(
        logger=get_service_logger("recommend-stats", logging_cfg.level),
        query_service=query_service,
        persistence_service=persistence_service,
    )

    recommendation_engine = RecommendationEngine(
        logger=get_service_logger("recommend", logging_cfg.level),
        parser_service=parser_service,
        indexer_service=indexer_service,
        graph_service=graph_service,
        impact_service=impact_analysis_service,
        rule_engine=rule_engine,
        policy_service=architecture_policy_service,
        storage_service=storage_service,
        ai_gateway=ai_gateway,
        prompt_service=prompt_template_service,
        query_service=query_service,
        persistence_service=persistence_service,
        organization_rule_service=organization_rule_service,
        recommendation_stats_service=recommendation_stats_service,
    )

    # After query/recommendation/rules deps exist so compose_workspace can orchestrate.
    branch_surgeon_service = BranchSurgeonService(
        logger=get_service_logger("surgeon", logging_cfg.level),
        git_service=git_service,
        commit_service=commit_service,
        indexer_service=indexer_service,
        graph_service=graph_service,
        impact_analysis_service=impact_analysis_service,
        test_intelligence_service=test_intelligence_service,
        documentation_service=documentation_service,
        query_service=query_service,
        recommendation_engine=recommendation_engine,
        recommendation_stats_service=recommendation_stats_service,
        company_rules_checker=company_rules_checker,
    )

    patch_service = PatchService(
        logger=get_service_logger("patch", logging_cfg.level),
        git_service=git_service,
        query_service=query_service,
        persistence_service=persistence_service,
        parser_service=parser_service,
        indexer_service=indexer_service,
        graph_service=graph_service,
        company_rules_checker=company_rules_checker,
    )
    recommendation_service = RecommendationService(
        logger=get_service_logger("recommendation", logging_cfg.level),
        git_service=git_service,
        query_service=query_service,
        persistence_service=persistence_service,
        patch_service=patch_service,
        recommendation_stats_service=recommendation_stats_service,
    )
    recommendation_patch_service = RecommendationPatchService(
        logger=get_service_logger("recommend-patch", logging_cfg.level),
        ai_gateway=ai_gateway,
        prompt_service=prompt_template_service,
        query_service=query_service,
        persistence_service=persistence_service,
        parser_service=parser_service,
        indexer_service=indexer_service,
        graph_service=graph_service,
        company_rules_checker=company_rules_checker,
        recommendation_service=recommendation_service,
    )

    transformation_service = TransformationService(
        logger=get_service_logger("transform", logging_cfg.level),
        parser_service=parser_service,
        indexer_service=indexer_service,
        graph_service=graph_service,
        rule_engine=rule_engine,
        policy_service=architecture_policy_service,
        storage_service=storage_service,
        ai_gateway=ai_gateway,
        prompt_service=prompt_template_service,
        query_service=query_service,
        persistence_service=persistence_service,
    )

    review_suggestion_status_service = ReviewSuggestionStatusService(
        logger=get_service_logger("review-suggestion", logging_cfg.level),
        query_service=query_service,
        persistence_service=persistence_service,
        recommendation_stats_service=recommendation_stats_service,
    )

    post_transformation_pipeline = PostTransformationPipeline(
        logger=get_service_logger("post-transform", logging_cfg.level),
        indexer_service=indexer_service,
        graph_service=graph_service,
        recommendation_engine=recommendation_engine,
        recommendation_stats_service=recommendation_stats_service,
        branch_surgeon_service=branch_surgeon_service,
        query_service=query_service,
        persistence_service=persistence_service,
        suggestion_status_service=review_suggestion_status_service,
    )

    container = ServiceContainer(
        settings=settings,
        git_service=git_service,
        commit_service=commit_service,
        repository_analysis_service=repository_analysis_service,
        github_service=github_service,
        parser_service=parser_service,
        embedding_provider=embedding_provider,
        embedding_service=embedding_service,
        chroma_store=chroma_store,
        indexer_service=indexer_service,
        graph_service=graph_service,
        retrieval_service=retrieval_service,
        code_search_service=code_search_service,
        impact_analysis_service=impact_analysis_service,
        test_intelligence_service=test_intelligence_service,
        documentation_service=documentation_service,
        branch_surgeon_service=branch_surgeon_service,
        requirement_analysis_service=requirement_analysis_service,
        refactoring_service=refactoring_service,
        ai_intelligence_service=ai_intelligence_service,
        session_context=session_context,
        repository_cache=repository_cache,
        workspace_manager=workspace_manager,
        background_indexer=background_indexer,
        performance_profiler=performance_profiler,
        pr_intelligence_service=pr_intelligence_service,
        storage_service=storage_service,
        rule_engine=rule_engine,
        architecture_policy_service=architecture_policy_service,
        company_rules_checker=company_rules_checker,
        organization_rule_service=organization_rule_service,
        organization_management_service=organization_management_service,
        analysis_history_service=analysis_history_service,
        prompt_template_service=prompt_template_service,
        recommendation_engine=recommendation_engine,
        recommendation_patch_service=recommendation_patch_service,
        patch_service=patch_service,
        recommendation_service=recommendation_service,
        recommendation_stats_service=recommendation_stats_service,
        review_suggestion_status_service=review_suggestion_status_service,
        post_transformation_pipeline=post_transformation_pipeline,
        transformation_service=transformation_service,
        database_manager=database_manager,
        session_factory=session_factory,
        persistence_service=persistence_service,
        query_service=query_service,
        prompt_builder=prompt_builder,
        review_response_parser=review_response_parser,
        ai_gateway=ai_gateway,
        ai_service=ai_service,
        review_engine=review_engine,
    )
    # Lazy BackendClient: PromptBuilder resolves the same instance as CLI auth/config.
    prompt_builder._backend_client_factory = container.get_backend_client

    def _post_transform_activity(**kwargs: object) -> None:
        from refactory.api.routes._activity import persist_repo_activity

        persist_repo_activity(container, **kwargs)  # type: ignore[arg-type]

    post_transformation_pipeline._activity_writer = _post_transform_activity
    return container
