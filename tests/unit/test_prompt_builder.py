"""Unit tests for deterministic PromptBuilder (no LLM calls)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from refactory.backend.exceptions import BackendUnavailableError
from refactory.backend.models import ReviewPrompt, ReviewWorkflow, WorkflowStep
from refactory.core.logger import get_service_logger
from refactory.github.models import ChangedFile, PullRequest
from refactory.graph.models import GraphStatistics, RepositoryGraph
from refactory.indexer.models import (
    RepositoryIndex,
    RepositoryStatistics,
    RepositorySummary,
)
from refactory.prompt.builder import PromptBuilder
from refactory.prompt.models import PromptContext, PromptMetadata, PromptRequest
from refactory.prompt.renderer import MarkdownRenderer
from refactory.prompt.templates import DEFAULT_REVIEW_PROMPT, SECTION_ORDER
from refactory.retrieval.models import (
    EntityKind,
    RetrievedFile,
    RetrievedSymbol,
    SearchQuery,
    SearchResult,
)
from refactory.review.models import Repository


def _logger():
    return get_service_logger("test.prompt")


def _pr(**kwargs: object) -> PullRequest:
    base = dict(
        number=42,
        title="Add token validation",
        body="Hardens JWT checks.",
        state="open",
        author="alice",
        base_branch="main",
        head_branch="feature/auth",
        changed_files=[
            ChangedFile(path="login.py", status="modified", additions=3, deletions=1),
            ChangedFile(path="auth.py", status="modified", additions=10, deletions=2),
        ],
    )
    base.update(kwargs)
    return PullRequest(**base)  # type: ignore[arg-type]


def _repo() -> Repository:
    return Repository(
        name="demo-repo",
        root_path="/tmp/demo-repo",
        current_branch="feature/auth",
        remote_url="https://example.com/demo.git",
        default_branch="main",
    )


def _index() -> RepositoryIndex:
    return RepositoryIndex(
        summary=RepositorySummary(
            repository_root="/tmp/demo-repo",
            repository_name="demo-repo",
            total_indexed_files=10,
            total_functions=11,
            total_classes=2,
            total_imports=6,
            todo_count=2,
            languages={"python": 10},
            timestamp=datetime(2026, 7, 22, tzinfo=timezone.utc),
        ),
        statistics=RepositoryStatistics(),
    )


def _graph() -> RepositoryGraph:
    return RepositoryGraph(
        repository_name="demo-repo",
        repository_root="/tmp/demo-repo",
        statistics=GraphStatistics(total_nodes=33, total_edges=86, import_edges=6),
    )


def _retrieval() -> SearchResult:
    return SearchResult(
        query=SearchQuery(text="authentication", top_k=2),
        hits=[
            RetrievedSymbol(
                result="function:validate_token",
                score=0.91,
                file_path="auth.py",
                module_name="auth",
                symbol="validate_token",
                kind=EntityKind.FUNCTION,
            ),
            RetrievedSymbol(
                result="module:auth",
                score=0.88,
                file_path="auth.py",
                module_name="auth",
                symbol="auth",
                kind=EntityKind.MODULE,
            ),
        ],
    )


def _full_context(**overrides: object) -> PromptContext:
    data = dict(
        pull_request=_pr(),
        repository=_repo(),
        index=_index(),
        graph=_graph(),
        retrieval=_retrieval(),
        related_files=[
            RetrievedFile(file_path="service.py", module_name="service", score=0.93),
            RetrievedFile(file_path="login.py", module_name="login", score=0.90),
        ],
        impacted_files=["login.py", "service.py", "tests/test_auth.py"],
        workflow=ReviewWorkflow(
            name="review",
            version="1.0.0",
            description="default",
            steps=[WorkflowStep(id="ensure_index", name="Ensure index", description="")],
            feature_flags={"telemetry_enabled": True, "incremental_index": True},
        ),
    )
    data.update(overrides)
    return PromptContext(**data)  # type: ignore[arg-type]


def test_deterministic_rendering():
    builder = PromptBuilder(logger=_logger())
    context = _full_context()
    first = builder.build(context)
    second = builder.build(context)
    assert first.system_prompt == second.system_prompt
    assert first.user_prompt == second.user_prompt
    assert first.model_dump() == second.model_dump()


def test_changed_files_sorted_deterministically():
    renderer = MarkdownRenderer()
    body = renderer.changed_files(
        [
            ChangedFile(path="z.py", status="modified", additions=1, deletions=0),
            ChangedFile(path="a.py", status="added", additions=2, deletions=0),
        ]
    )
    assert body.index("`a.py`") < body.index("`z.py`")


def test_missing_optional_sections_still_render_placeholders():
    builder = PromptBuilder(logger=_logger())
    result = builder.build(
        PromptContext(
            pull_request=PullRequest(number=1, title="Empty PR"),
        )
    )
    assert "====================\nRepository\n====================" in result.user_prompt
    assert "_No repository context._" in result.user_prompt
    assert "_No relevant code context._" in result.user_prompt
    assert "_No dependency impact._" in result.user_prompt
    assert result.metadata.section_keys == list(SECTION_ORDER)


def test_empty_retrieval_results():
    builder = PromptBuilder(logger=_logger())
    result = builder.build(
        _full_context(
            retrieval=SearchResult(query=SearchQuery(text="none"), hits=[]),
            related_files=[],
            impacted_files=[],
        )
    )
    assert "_No relevant code context._" in result.user_prompt
    assert result.metadata.extras["retrieval_hit_count"] == 0


def test_backend_template_unavailable_falls_back_local():
    backend = MagicMock()
    backend.get_review_prompt.side_effect = BackendUnavailableError("down")
    backend.get_review_workflow.side_effect = BackendUnavailableError("down")
    builder = PromptBuilder(logger=_logger(), backend_client=backend)
    result = builder.build(_full_context(prompt_template=None, workflow=None))
    assert result.metadata.template_source == "local_default"
    assert result.metadata.template_version == DEFAULT_REVIEW_PROMPT.version
    assert result.metadata.extras["workflow"] == ""
    assert "senior code reviewer" in result.system_prompt.lower() or "Refactory" in result.system_prompt
    backend.get_review_prompt.assert_called_once()
    backend.get_review_workflow.assert_called_once()


def test_backend_template_override():
    remote = ReviewPrompt(
        name="review",
        version="9.9.9",
        description="from backend",
        template="BACKEND SYSTEM PROMPT UNIQUE",
        variables=[],
        metadata={"feature_flags": {"security_focus": True}},
    )
    builder = PromptBuilder(logger=_logger())
    result = builder.build(_full_context(prompt_template=remote))
    assert result.system_prompt.startswith("BACKEND SYSTEM PROMPT UNIQUE")
    assert result.metadata.template_source == "backend"
    assert result.metadata.template_version == "9.9.9"
    assert result.metadata.feature_flags["security_focus"] is True


def test_backend_client_fetch_when_authenticated():
    from refactory.prompt.templates import PROMPT_TEMPLATE_VERSION

    remote = ReviewPrompt(
        name="review",
        version=PROMPT_TEMPLATE_VERSION,
        description="fetched",
        template="Fetched from GET /prompts/review",
        variables=[],
        metadata={},
    )
    backend = MagicMock()
    backend.get_review_prompt.return_value = remote
    backend.get_review_workflow.return_value = ReviewWorkflow(
        name="review",
        version="3.1.0",
        description="fetched workflow",
        steps=[WorkflowStep(id="ensure_index", name="Ensure index", description="")],
        feature_flags={"security_focus": True},
    )
    builder = PromptBuilder(logger=_logger(), backend_client=backend)
    result = builder.build(_full_context(prompt_template=None, workflow=None))
    assert result.metadata.template_source == "backend"
    assert result.metadata.template_version == PROMPT_TEMPLATE_VERSION
    assert "Fetched from GET /prompts/review" in result.system_prompt
    assert "workflow=review@3.1.0" in result.metadata.extras["workflow"]
    assert result.metadata.feature_flags["security_focus"] is True
    backend.get_review_prompt.assert_called_once()
    backend.get_review_workflow.assert_called_once()


def test_backend_prompt_version_guard():
    """Older backend prompt (2.0.0) must NOT override newer local template (2.1.0+).

    Regression test for a production bug where the backend prompt registry
    returned version 2.0.0, silently replacing the local template that
    contained mandatory per-finding fields (confidence, estimated_impact).

    Asserts:
      1. Local template is selected (template_source == "local_default")
      2. Warning is logged about the version mismatch
      3. Effective prompt version equals the local PROMPT_TEMPLATE_VERSION
    """
    import io

    from loguru import logger as loguru_logger

    from refactory.prompt.templates import PROMPT_TEMPLATE_VERSION

    stale_backend = ReviewPrompt(
        name="review",
        version="2.0.0",
        description="stale backend prompt missing required fields",
        template="Old backend template without confidence/estimated_impact enforcement",
        variables=[],
        metadata={},
    )
    backend = MagicMock()
    backend.get_review_prompt.return_value = stale_backend
    backend.get_review_workflow.side_effect = Exception("no workflow")

    log_capture = io.StringIO()
    sink_id = loguru_logger.add(log_capture, format="{message}", level="DEBUG")
    try:
        builder = PromptBuilder(
            logger=loguru_logger, backend_client=backend
        )
        result = builder.build(_full_context(prompt_template=None, workflow=None))
    finally:
        loguru_logger.remove(sink_id)

    logs = log_capture.getvalue()

    # 1. Local template is selected
    assert result.metadata.template_source == "local_default"

    # 2. Warning is logged about the version mismatch
    assert "2.0.0 is older than local" in logs
    assert PROMPT_TEMPLATE_VERSION in logs

    # 3. Effective prompt version equals the local PROMPT_TEMPLATE_VERSION
    assert result.metadata.template_version == PROMPT_TEMPLATE_VERSION

    # Backend template text must NOT appear in the system prompt
    assert "Old backend template" not in result.system_prompt

    # Backend was still called (we don't skip the fetch, just reject the result)
    backend.get_review_prompt.assert_called_once()


def test_backend_prompt_accepted_when_version_matches_or_newer():
    """Backend prompt with version >= local should be accepted normally."""
    from refactory.prompt.templates import PROMPT_TEMPLATE_VERSION

    newer_backend = ReviewPrompt(
        name="review",
        version="99.0.0",
        description="future backend prompt",
        template="Future backend template with all fields",
        variables=[],
        metadata={},
    )
    backend = MagicMock()
    backend.get_review_prompt.return_value = newer_backend
    backend.get_review_workflow.side_effect = Exception("no workflow")

    builder = PromptBuilder(logger=_logger(), backend_client=backend)
    result = builder.build(_full_context(prompt_template=None, workflow=None))

    assert result.metadata.template_source == "backend"
    assert result.metadata.template_version == "99.0.0"
    assert "Future backend template" in result.system_prompt


def test_backend_client_factory_resolves_lazy_client():
    remote = ReviewPrompt(
        name="review",
        version="4.0.0",
        description="via factory",
        template="Factory-resolved backend prompt",
        variables=[],
        metadata={},
    )
    backend = MagicMock()
    backend.get_review_prompt.return_value = remote
    backend.get_review_workflow.return_value = ReviewWorkflow(
        name="review",
        version="4.0.0",
        description="via factory",
        steps=[],
        feature_flags={"incremental_index": True},
    )
    builder = PromptBuilder(
        logger=_logger(),
        backend_client_factory=lambda: backend,
    )
    result = builder.build(_full_context(prompt_template=None, workflow=None))
    assert result.metadata.template_source == "backend"
    assert "Factory-resolved backend prompt" in result.system_prompt
    assert "workflow=review@4.0.0" in result.metadata.extras["workflow"]
    backend.get_review_prompt.assert_called_once()
    backend.get_review_workflow.assert_called_once()


def test_offline_mode_skips_backend_when_client_unavailable():
    builder = PromptBuilder(logger=_logger(), backend_client=None)
    result = builder.build(_full_context(prompt_template=None, workflow=None))
    assert result.metadata.template_source == "local_default"
    assert result.metadata.extras["workflow"] == ""
    assert result.metadata.template_name == DEFAULT_REVIEW_PROMPT.name


def test_backend_workflow_failure_keeps_backend_template():
    remote = ReviewPrompt(
        name="review",
        version="2.1.0",
        description="prompt ok",
        template="Prompt from backend despite workflow failure",
        variables=[],
        metadata={},
    )
    backend = MagicMock()
    backend.get_review_prompt.return_value = remote
    backend.get_review_workflow.side_effect = BackendUnavailableError("workflow down")
    builder = PromptBuilder(logger=_logger(), backend_client=backend)
    result = builder.build(_full_context(prompt_template=None, workflow=None))
    assert result.metadata.template_source == "backend"
    assert result.metadata.extras["workflow"] == ""
    assert "Prompt from backend despite workflow failure" in result.system_prompt


def test_metadata_serialization_stable():
    builder = PromptBuilder(logger=_logger())
    result = builder.build(_full_context())
    payload = result.metadata.model_dump(mode="json")
    assert payload["pr_number"] == 42
    assert payload["repository_name"] == "demo-repo"
    assert payload["section_keys"] == list(SECTION_ORDER)
    assert "telemetry_enabled" in payload["feature_flags"]
    # Round-trip
    restored = PromptMetadata.model_validate(payload)
    assert restored == result.metadata


def test_user_prompt_contains_all_primary_sections():
    result = PromptBuilder(logger=_logger()).build(_full_context())
    for title in (
        "Repository",
        "PR Summary",
        "Changed Files",
        "Git Diff",
        "Relevant Code",
        "Dependency Impact",
        "Review Instructions",
        "Expected JSON Output",
    ):
        assert f"====================\n{title}\n====================" in result.user_prompt
    assert "validate_token" in result.user_prompt
    assert "`auth.py`" in result.user_prompt
    assert "tests/test_auth.py" in result.user_prompt


def test_user_prompt_includes_pull_request_diff():
    pr = _pr(
        diff=(
            "diff --git a/auth.py b/auth.py\n"
            "--- a/auth.py\n"
            "+++ b/auth.py\n"
            "@@ -1,3 +1,5 @@\n"
            "- old\n"
            "+ new\n"
        ),
        changed_files=[ChangedFile(path="auth.py", status="modified")],
    )
    result = PromptBuilder(logger=_logger()).build(_full_context(pull_request=pr))
    assert "====================\nGit Diff\n====================" in result.user_prompt
    assert "diff --git a/auth.py b/auth.py" in result.user_prompt
    assert "+ new" in result.user_prompt


def test_user_prompt_prefers_changed_file_patches():
    pr = _pr(
        diff="diff --git a/ignored.py b/ignored.py\n+ ignored\n",
        changed_files=[
            ChangedFile(
                path="auth.py",
                status="modified",
                patch=(
                    "diff --git a/auth.py b/auth.py\n"
                    "--- a/auth.py\n"
                    "+++ b/auth.py\n"
                    "@@ -1,3 +1,5 @@\n"
                    "- old\n"
                    "+ new\n"
                ),
            )
        ],
    )
    result = PromptBuilder(logger=_logger()).build(_full_context(pull_request=pr))
    assert "diff --git a/auth.py b/auth.py" in result.user_prompt
    assert "+ new" in result.user_prompt
    assert "ignored.py" not in result.user_prompt


def test_ai_request_preserves_git_diff_section():
    from refactory.ai.models import AIRequest

    pr = _pr(
        diff=(
            "diff --git a/auth.py b/auth.py\n"
            "--- a/auth.py\n"
            "+++ b/auth.py\n"
            "@@ -1,3 +1,5 @@\n"
            "- old\n"
            "+ new\n"
        ),
        changed_files=[ChangedFile(path="auth.py", status="modified")],
    )
    prompt = PromptBuilder(logger=_logger()).build(_full_context(pull_request=pr))
    request = AIRequest.from_prompt_request(prompt)
    assert "Git Diff" in request.user_prompt
    assert "diff --git a/auth.py b/auth.py" in request.user_prompt
    assert request.user_prompt == prompt.user_prompt


def test_backend_template_binds_diff_summary_and_related_context():
    remote = ReviewPrompt(
        name="review",
        version="2.0.0",
        description="backend",
        template=(
            "You are a senior code reviewer for {{repository_name}}.\n"
            "PR #{{pr_number}}\n\n"
            "==================== CONTEXT ====================\n"
            "{{related_context}}\n\n"
            "==================== DIFF ====================\n"
            "{{diff_summary}}\n\n"
            "Return JSON."
        ),
        variables=[
            "repository_name",
            "pr_number",
            "related_context",
            "diff_summary",
        ],
        metadata={},
    )
    pr = _pr(
        diff=(
            "diff --git a/auth.py b/auth.py\n"
            "--- a/auth.py\n"
            "+++ b/auth.py\n"
            "+ new\n"
        ),
        changed_files=[
            ChangedFile(
                path="auth.py",
                status="modified",
                patch=(
                    "diff --git a/auth.py b/auth.py\n"
                    "--- a/auth.py\n"
                    "+++ b/auth.py\n"
                    "+ new\n"
                ),
            )
        ],
    )
    result = PromptBuilder(logger=_logger()).build(
        _full_context(pull_request=pr, prompt_template=remote)
    )
    assert "{{diff_summary}}" not in result.system_prompt
    assert "{{related_context}}" not in result.system_prompt
    assert "diff --git a/auth.py b/auth.py" in result.system_prompt
    assert "====================\nGit Diff\n====================" in result.user_prompt
    assert "diff --git a/auth.py b/auth.py" in result.user_prompt


def test_stale_cache_without_diff_section_is_ignored():
    from refactory.cache.store import DeterministicCache
    from refactory.prompt.budget import ContextBudget

    cache = DeterministicCache(enabled=True, disk_dir=None, namespace="prompt-stale")
    builder = PromptBuilder(
        logger=_logger(),
        default_budget=ContextBudget(),
        cache=cache,
    )
    pr = _pr(
        diff=(
            "diff --git a/auth.py b/auth.py\n"
            "+ new\n"
        ),
        changed_files=[ChangedFile(path="auth.py", status="modified")],
    )
    ctx = _full_context(pull_request=pr)
    # Seed a stale cache entry that omits the Git Diff section.
    key = builder._prompt_key(
        ctx,
        ContextBudget(),
        "2.0.0",
        "local_default",
    )
    cache.set(
        key,
        PromptRequest(
            system_prompt="sys",
            user_prompt="Changed Files\n\nauth.py\n",
            metadata=PromptMetadata(
                template_source="local_default",
                section_keys=["changed_files", "relevant_code"],
            ),
            sections=[],
        ).model_dump(mode="json"),
    )
    result = builder.build(ctx)
    assert "Git Diff" in result.user_prompt
    assert "diff --git" in result.user_prompt


def test_cache_fingerprint_changes_when_diff_changes():
    from refactory.prompt.budget import ContextBudget

    builder = PromptBuilder(logger=_logger())
    budget = ContextBudget()
    base_pr = _pr(
        diff="diff --git a/auth.py b/auth.py\n+ one\n",
        changed_files=[ChangedFile(path="auth.py", status="modified")],
    )
    changed_pr = _pr(
        diff="diff --git a/auth.py b/auth.py\n+ two\n",
        changed_files=[ChangedFile(path="auth.py", status="modified")],
    )
    key_one = builder._prompt_key(
        _full_context(pull_request=base_pr),
        budget,
        "2.0.0",
        "local_default",
    )
    key_two = builder._prompt_key(
        _full_context(pull_request=changed_pr),
        budget,
        "2.0.0",
        "local_default",
    )
    assert key_one != key_two


def test_prompt_builder_preserves_section_ordering():
    result = PromptBuilder(logger=_logger()).build(_full_context())
    assert result.metadata.section_keys == list(SECTION_ORDER)
    titles = [
        "Repository",
        "PR Summary",
        "Changed Files",
        "Git Diff",
        "Relevant Code",
        "Dependency Impact",
        "Review Instructions",
        "Expected JSON Output",
    ]
    positions = [
        result.user_prompt.index(f"====================\n{title}\n====================")
        for title in titles
    ]
    assert positions == sorted(positions)
    # Relevant Code (related context) is present for the model.
    assert "Relevant Code" in result.user_prompt
    assert "validate_token" in result.user_prompt or "`auth.py`" in result.user_prompt


def test_section_bodies_independent():
    renderer = MarkdownRenderer()
    pr_body = renderer.pull_request_metadata(_pr())
    files_body = renderer.changed_files(_pr().changed_files)
    assert "Pull Request" not in files_body
    assert "Changed Files" not in pr_body
    assert "Add token validation" in pr_body
