"""ReviewEngine unit tests — orchestration wiring (mocked collaborators)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from refactory.ai.models import AIResponse
from refactory.core.logger import get_service_logger
from refactory.github.models import ChangedFile, PullRequest
from refactory.graph.models import GraphStatistics, RepositoryGraph
from refactory.indexer.models import (
    RepositoryIndex,
    RepositoryStatistics,
    RepositorySummary as IndexSummary,
)
from refactory.prompt.models import PromptMetadata, PromptRequest
from refactory.response.models import ReviewMetadata, ReviewResult as ParsedReviewResult
from refactory.response.models import ReviewSuggestion as ParsedSuggestion
from refactory.review.engine import ReviewEngine
from refactory.review.models import Repository, ReviewResult


def _index(root: Path) -> RepositoryIndex:
    return RepositoryIndex(
        summary=IndexSummary(
            repository_name=root.name,
            repository_root=str(root),
            total_indexed_files=0,
            timestamp=datetime(2026, 7, 23, tzinfo=timezone.utc),
        ),
        statistics=RepositoryStatistics(),
        files=[],
    )


def _graph() -> RepositoryGraph:
    return RepositoryGraph(
        repository_name="demo",
        repository_root=".",
        nodes={},
        edges=[],
        statistics=GraphStatistics(),
    )


def _engine(**overrides: object) -> ReviewEngine:
    defaults: dict[str, object] = {
        "git_service": MagicMock(),
        "github_service": MagicMock(),
        "parser_service": MagicMock(),
        "indexer_service": MagicMock(),
        "retrieval_service": MagicMock(),
        "ai_service": MagicMock(),
        "logger": get_service_logger("test.review"),
        "graph_service": MagicMock(),
        "prompt_builder": MagicMock(),
        "ai_gateway": MagicMock(),
        "response_parser": MagicMock(),
    }
    defaults.update(overrides)
    return ReviewEngine(**defaults)  # type: ignore[arg-type]


def test_review_engine_can_be_instantiated_with_mocks():
    engine = _engine()
    assert isinstance(engine, ReviewEngine)


def test_review_orchestrates_full_pipeline(tmp_path: Path):
    repo = Repository(
        name=tmp_path.name,
        root_path=str(tmp_path),
        current_branch="feature",
        default_branch="main",
    )
    pr = PullRequest(
        number=7,
        title="Add auth",
        body="Secure login",
        changed_files=[ChangedFile(path="auth.py", status="modified")],
    )
    index = _index(tmp_path)

    git = MagicMock()
    git.require_repository.return_value = repo
    github = MagicMock()
    github.fetch_pull_request.return_value = pr
    indexer = MagicMock()
    indexer.ensure_index.return_value = 1
    indexer.load_index.return_value = index
    indexer.get_last_index.return_value = index
    graph_service = MagicMock()
    graph_service.build_graph.return_value = _graph()
    graph_service.affected_files.return_value = ["app.py"]
    retrieval = MagicMock()
    retrieval.search.return_value = MagicMock(hits=[])
    retrieval.retrieve_related_context.return_value = ["helpers.py"]
    retrieval.related_files.return_value = []
    prompt_builder = MagicMock()
    prompt_builder.build.return_value = PromptRequest(
        system_prompt="sys",
        user_prompt="user",
        metadata=PromptMetadata(template_source="local_default", pr_number=7),
    )
    gateway = MagicMock()
    gateway.generate.return_value = AIResponse(
        text="summary: looks good\nrisk_level: low\nconfidence: 0.6\nfindings: []\n",
        provider="mock",
        model="mock-review-1",
        latency_ms=1.0,
    )
    parser = MagicMock()
    parser.parse_response.return_value = ParsedReviewResult(
        summary="looks good",
        overall_risk="low",
        suggestions=[
            ParsedSuggestion(
                title="Check edge case",
                explanation="None handled",
                recommendation="Add test",
                severity="medium",
                file="auth.py",
            )
        ],
        confidence=0.6,
        metadata=ReviewMetadata(source_format="key_value"),
    )

    engine = _engine(
        git_service=git,
        github_service=github,
        indexer_service=indexer,
        graph_service=graph_service,
        retrieval_service=retrieval,
        prompt_builder=prompt_builder,
        ai_gateway=gateway,
        response_parser=parser,
    )

    built = engine.build_prompt(7)
    assert built.system_prompt == "sys"
    gateway.generate.assert_not_called()
    parser.parse_response.assert_not_called()

    result = engine.review(7)

    assert isinstance(result, ReviewResult)
    assert result.pull_request_number == 7
    assert result.summary == "looks good"
    assert result.risk_level == "low"
    assert result.confidence == 0.6
    assert len(result.suggestions) == 1
    assert result.suggestions[0].file_path == "auth.py"
    assert "None handled" in result.suggestions[0].detail

    indexer.ensure_index.assert_called()
    graph_service.build_graph.assert_called()
    assert prompt_builder.build.call_count == 2
    gateway.generate.assert_called_once()
    parser.parse_response.assert_called_once()


def test_synthesize_local_pull_request_sets_diff_and_patches():
    from refactory.git.models import ChangeKind, ChangedPath

    repo = Repository(
        name="demo",
        root_path=".",
        current_branch="feature",
        default_branch="main",
    )
    unified = (
        "diff --git a/auth.py b/auth.py\n"
        "--- a/auth.py\n"
        "+++ b/auth.py\n"
        "@@ -1,3 +1,5 @@\n"
        "- old\n"
        "+ new\n"
    )
    git = MagicMock()
    git.get_default_branch.return_value = "main"
    git.resolve_diff_base_ref.return_value = "origin/main"
    git.get_changed_files_three_dot.return_value = [
        ChangedPath(path="auth.py", kind=ChangeKind.MODIFIED),
    ]
    git.get_unified_diff_three_dot.return_value = unified
    git.get_current_commit.return_value = MagicMock(message="fix auth")
    git.get_head_sha.return_value = "abc"
    git._open_repo.return_value.commit.return_value.hexsha = "base"

    engine = _engine(git_service=git)
    pr = engine._synthesize_local_pull_request(repo, 1)
    assert pr.diff == unified
    assert pr.changed_files[0].path == "auth.py"
    assert pr.changed_files[0].patch is not None
    assert "diff --git a/auth.py b/auth.py" in pr.changed_files[0].patch
    assert "+ new" in pr.changed_files[0].patch
    git.get_working_tree_status.assert_not_called()


def test_review_empty_local_pr_does_not_use_working_tree(tmp_path: Path):
    """Regression: empty base...head must NOT fall back to untracked files."""
    repo = Repository(
        name=tmp_path.name,
        root_path=str(tmp_path),
        current_branch="main",
        default_branch="main",
    )
    index = _index(tmp_path)

    git = MagicMock()
    git.require_repository.return_value = repo
    git.get_default_branch.return_value = "main"
    git.resolve_diff_base_ref.return_value = "main"
    git.get_changed_files_three_dot.return_value = []
    git.get_unified_diff_three_dot.return_value = ""
    git.get_changed_files_vs_default_branch.return_value = []
    git.get_unified_diff_vs_default_branch.return_value = ""
    status = MagicMock()
    status.staged_files = []
    status.modified_files = []
    status.deleted_files = []
    status.renamed_files = []
    status.untracked_files = ["new_mod.py"]
    git.get_working_tree_status.return_value = status
    git.get_current_commit.return_value = MagicMock(message="wip: local changes\n\nbody")
    git.get_head_sha.return_value = "deadbeef"
    git._open_repo.return_value.commit.return_value.hexsha = "base"

    github = MagicMock()
    github.fetch_pull_request.side_effect = NotImplementedError("no github")

    indexer = MagicMock()
    indexer.ensure_index.return_value = 0
    indexer.load_index.return_value = index
    indexer.get_last_index.return_value = index

    graph_service = MagicMock()
    graph_service.build_graph.return_value = _graph()
    graph_service.affected_files.return_value = []

    retrieval = MagicMock()
    retrieval.search.return_value = MagicMock(hits=[])
    retrieval.retrieve_related_context.return_value = []
    retrieval.related_files.return_value = []

    prompt_builder = MagicMock()
    gateway = MagicMock()
    parser = MagicMock()

    engine = _engine(
        git_service=git,
        github_service=github,
        indexer_service=indexer,
        graph_service=graph_service,
        retrieval_service=retrieval,
        prompt_builder=prompt_builder,
        ai_gateway=gateway,
        response_parser=parser,
    )

    result = engine.review(3)
    assert result.summary == "No changes to review"
    assert result.suggestions == []
    assert result.metadata["empty_pr"] is True
    gateway.generate.assert_not_called()
    prompt_builder.build.assert_not_called()
    git.get_working_tree_status.assert_not_called()
