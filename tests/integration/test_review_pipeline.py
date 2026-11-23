"""End-to-end review pipeline with MockProvider (no network / real LLMs)."""

from __future__ import annotations

from pathlib import Path

import pytest
from git import Repo

from refactory.core.config import Settings
from refactory.core.container import build_container
from refactory.review.models import ReviewResult


def _init_repo(root: Path) -> None:
    repo = Repo.init(root)
    # Identity for commits in ephemeral repos
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Refactory Test")
        cw.set_value("user", "email", "test@refactory.dev")

    sample = root / "auth.py"
    sample.write_text(
        "def login(user: str, password: str) -> bool:\n"
        "    # TODO: hash password\n"
        "    return password == 'secret'\n",
        encoding="utf-8",
    )
    repo.index.add(["auth.py"])
    repo.index.commit("Initial auth module")

    # Feature branch with a change vs main
    repo.git.checkout("-b", "feature/review")
    sample.write_text(
        "def login(user: str, password: str) -> bool:\n"
        "    if not user:\n"
        "        return False\n"
        "    return password == 'secret'\n",
        encoding="utf-8",
    )
    repo.index.add(["auth.py"])
    repo.index.commit("Harden login null check")


@pytest.fixture()
def review_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "demo-repo"
    root.mkdir()
    _init_repo(root)
    monkeypatch.chdir(root)
    # Force mock provider — no API keys / network
    monkeypatch.setenv("AI_PROVIDER", "mock")
    return root


def test_review_pipeline_end_to_end_with_mock_provider(review_repo: Path):
    settings = Settings().model_copy(update={"ai_provider": "mock"})
    container = build_container(settings=settings, repo_root=review_repo)

    assert container.ai_gateway.provider_name == "mock"

    result = container.review_engine.review(1)

    assert isinstance(result, ReviewResult)
    assert result.pull_request_number == 1
    assert result.summary  # mock provider yields a non-empty summary line
    assert result.risk_level in {"low", "medium", "high", "critical", "unknown", "info"}
    assert 0.0 <= result.confidence <= 1.0
    # Index was created as part of orchestration
    assert (review_repo / ".refactory").exists()


def test_review_cli_prints_parsed_result(review_repo: Path, monkeypatch: pytest.MonkeyPatch):
    from typer.testing import CliRunner

    from refactory.cli.app import app

    settings = Settings().model_copy(update={"ai_provider": "mock"})
    container = build_container(settings=settings, repo_root=review_repo)
    monkeypatch.setattr(
        "refactory.cli.commands.review.get_container", lambda: container
    )

    runner = CliRunner()
    outcome = runner.invoke(app, ["review", "9"])

    assert outcome.exit_code == 0, outcome.output
    assert "Review PR #9" in outcome.output or "PR #9" in outcome.output
    assert "Summary" in outcome.output
