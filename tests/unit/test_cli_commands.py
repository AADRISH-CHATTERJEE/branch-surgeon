"""CLI commands must delegate to container services — no business logic."""

from __future__ import annotations

from unittest.mock import MagicMock

from typer.testing import CliRunner

from refactory.cli.app import app
from refactory.review.models import ReviewResult


runner = CliRunner()


def test_review_command_invokes_engine(mocker):
    engine = MagicMock()
    engine.review.return_value = ReviewResult(
        pull_request_number=25,
        summary="stub",
        risk_level="low",
        provider="mock",
        model="mock-review-1",
        latency_ms=12.5,
        elapsed_ms=40.0,
        prompt_tokens=10,
        completion_tokens=4,
        estimated_cost_usd=0.0,
        cache_hit=False,
        warnings=["Confidence estimated at 0.500"],
        metadata={"source_format": "json", "is_partial": False},
    )
    container = MagicMock()
    container.review_engine = engine
    mocker.patch("refactory.cli.commands.review.get_container", return_value=container)

    result = runner.invoke(app, ["review", "25"])

    assert result.exit_code == 0
    engine.review.assert_called_once_with(25)
    assert "mock" in result.stdout
    assert "mock-review-1" in result.stdout
    assert "Warnings" in result.stdout
    assert "Review metadata" in result.stdout


def test_prompt_command_invokes_build_prompt_not_gateway(mocker):
    from refactory.prompt.models import PromptMetadata, PromptRequest

    engine = MagicMock()
    engine.build_prompt.return_value = PromptRequest(
        system_prompt="SYSTEM TEXT",
        user_prompt="USER TEXT",
        metadata=PromptMetadata(
            template_source="local_default",
            repository_name="demo",
            pr_number=1,
            section_keys=["changed_files"],
        ),
    )
    container = MagicMock()
    container.review_engine = engine
    container.git_service.require_repository.return_value = MagicMock(root_path=".")
    mocker.patch("refactory.cli.commands.prompt.get_container", return_value=container)

    result = runner.invoke(app, ["prompt", "1"])

    assert result.exit_code == 0, result.output
    engine.build_prompt.assert_called_once_with(1)
    engine.review.assert_not_called()
    assert "SYSTEM TEXT" in result.output
    assert "USER TEXT" in result.output
    assert "System Prompt" in result.output
    assert "User Prompt" in result.output
    assert "Prompt metadata" in result.output


def test_prompt_command_save_writes_default_path(mocker, tmp_path):
    from refactory.prompt.models import PromptMetadata, PromptRequest

    engine = MagicMock()
    engine.build_prompt.return_value = PromptRequest(
        system_prompt="sys body",
        user_prompt="user body",
        metadata=PromptMetadata(template_source="local_default", pr_number=2),
    )
    container = MagicMock()
    container.review_engine = engine
    container.git_service.require_repository.return_value = MagicMock(
        root_path=str(tmp_path)
    )
    mocker.patch("refactory.cli.commands.prompt.get_container", return_value=container)

    result = runner.invoke(app, ["prompt", "2", "--save"])

    assert result.exit_code == 0, result.output
    saved = tmp_path / ".refactory" / "prompts" / "latest_prompt.md"
    assert saved.is_file()
    text = saved.read_text(encoding="utf-8")
    assert "SYSTEM PROMPT" in text
    assert "sys body" in text
    assert "USER PROMPT" in text
    assert "user body" in text
    assert "METADATA" in text
    assert "local_default" in text
    assert "Saved prompt" in result.output


def test_prompt_command_output_custom_path(mocker, tmp_path):
    from refactory.prompt.models import PromptMetadata, PromptRequest

    engine = MagicMock()
    engine.build_prompt.return_value = PromptRequest(
        system_prompt="S",
        user_prompt="U",
        metadata=PromptMetadata(template_source="local_default"),
    )
    container = MagicMock()
    container.review_engine = engine
    container.git_service.require_repository.return_value = MagicMock(
        root_path=str(tmp_path)
    )
    mocker.patch("refactory.cli.commands.prompt.get_container", return_value=container)

    result = runner.invoke(app, ["prompt", "3", "--output", "latest_prompt.md"])

    assert result.exit_code == 0, result.output
    saved = tmp_path / "latest_prompt.md"
    assert saved.is_file()
    assert "SYSTEM PROMPT" in saved.read_text(encoding="utf-8")


def test_search_command_invokes_code_search(mocker):
    from refactory.codesearch.models import CodeSearchHit, CodeSearchResult

    codesearch = MagicMock()
    codesearch.search.return_value = CodeSearchResult(
        query="jwt auth",
        hits=[
            CodeSearchHit(
                file="auth.py",
                line=3,
                symbol="validate_token",
                type="function",
                snippet="def validate_token():",
                score=0.91,
                confidence=0.91,
            )
        ],
        structural_hits=1,
        semantic_hits=1,
    )
    container = MagicMock()
    container.code_search_service = codesearch
    mocker.patch("refactory.cli.commands.search.get_container", return_value=container)
    mocker.patch("refactory.cli.commands.search.warm_backend_client")

    result = runner.invoke(app, ["search", "jwt auth"])

    assert result.exit_code == 0, result.stdout
    codesearch.search.assert_called_once()
    assert "validate_token" in result.stdout
    assert "auth.py" in result.stdout
    assert "0.9100" in result.stdout


def test_related_command_invokes_codesearch(mocker):
    from refactory.codesearch.models import CodeHitKind, CodeSearchHit, CodeSearchResult

    codesearch = MagicMock()
    codesearch.find_related.return_value = CodeSearchResult(
        query="auth.py",
        hits=[
            CodeSearchHit(
                file="login.py",
                line=1,
                symbol="login",
                type=CodeHitKind.RELATED.value,
                score=0.9,
                reasons=["graph_dependents"],
            )
        ],
        structural_hits=1,
        semantic_hits=0,
        notes=[],
    )
    container = MagicMock()
    container.code_search_service = codesearch
    mocker.patch("refactory.cli.commands.search.get_container", return_value=container)
    mocker.patch("refactory.cli.commands.search.warn_if_index_stale")

    result = runner.invoke(app, ["related", "auth.py"])

    assert result.exit_code == 0, result.stdout
    codesearch.find_related.assert_called_once()
    assert "login.py" in result.stdout
    assert "graph_dependents" in result.stdout


def test_index_command_invokes_indexer(mocker):
    from datetime import datetime, timezone

    from refactory.indexer.models import RepositoryIndex, RepositoryStatistics, RepositorySummary

    git = MagicMock()
    git.get_repository_metadata.return_value = MagicMock(
        name="demo-repo",
        root_path="C:/tmp/demo-repo",
    )
    # Ensure attribute access used by CLI
    git.get_repository_metadata.return_value.name = "demo-repo"
    git.get_repository_metadata.return_value.root_path = "C:/tmp/demo-repo"

    index_result = RepositoryIndex(
        summary=RepositorySummary(
            repository_root="C:/tmp/demo-repo",
            repository_name="demo-repo",
            total_indexed_files=12,
            ignored_file_count=24,
            total_functions=31,
            total_classes=8,
            total_imports=44,
            todo_count=3,
            timestamp=datetime.now(timezone.utc),
        ),
        statistics=RepositoryStatistics(
            files_parsed=0,
            reused_unchanged_files=12,
            newly_added_files=0,
            modified_files=0,
            deleted_files=0,
            ignored_files=24,
            parse_failures=0,
            indexing_duration_seconds=0.41,
        ),
    )
    indexer = MagicMock()
    indexer.build_index.return_value = index_result
    container = MagicMock()
    container.git_service = git
    container.indexer_service = indexer
    mocker.patch("refactory.cli.commands.index.get_container", return_value=container)

    result = runner.invoke(app, ["index", "--force"])

    assert result.exit_code == 0
    indexer.build_index.assert_called_once()
    assert "demo-repo" in result.stdout
    assert "Indexed files" in result.stdout
    assert "12" in result.stdout
    assert "Files parsed" in result.stdout
    assert "Cache reused" in result.stdout
    assert "This run" in result.stdout


def test_login_command_invokes_backend_client(mocker):
    client = MagicMock()
    client.token_store.path = "C:/Users/test/.refactory/auth.json"
    client.get_current_user.return_value = MagicMock(email="cli@refactory.dev")
    container = MagicMock()
    container.require_backend_client.return_value = client
    mocker.patch("refactory.cli.commands.login.get_container", return_value=container)

    result = runner.invoke(
        app,
        ["login", "--email", "cli@refactory.dev", "--password", "secret"],
    )

    assert result.exit_code == 0, result.stdout
    client.login.assert_called_once_with("cli@refactory.dev", "secret")


def test_status_command_runs(mocker):
    container = MagicMock()
    settings = MagicMock()
    settings.embedding.model = "BAAI/bge-small-en-v1.5"
    settings.embedding.chroma_path = ".refactory/chroma"
    settings.logging.level = "INFO"
    settings.backend.url = "http://127.0.0.1:8000"
    settings.ai.provider = "mock"
    settings.github.token = None
    settings.ai.gemini_api_key = None
    settings.ai.openai_api_key = None
    settings.ignore_dirs = [".git"]
    container.settings = settings
    container.review_engine = MagicMock()
    container.ai_gateway = MagicMock(model="mock-review-1")
    container.get_backend_client.return_value = None
    mocker.patch("refactory.cli.commands.status.get_container", return_value=container)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
