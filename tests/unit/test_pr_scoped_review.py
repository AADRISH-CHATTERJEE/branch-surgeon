"""PR-scoped review must use committed base...head only — never working tree."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from git import Repo

from refactory.core.exceptions import RefactoryError
from refactory.core.logger import get_service_logger
from refactory.git.models import ChangeKind, ChangedPath
from refactory.git.service import GitService
from refactory.graph.models import GraphStatistics, RepositoryGraph
from refactory.indexer.models import (
    RepositoryIndex,
    RepositoryStatistics,
    RepositorySummary as IndexSummary,
)
from refactory.prompt.models import PromptMetadata, PromptRequest
from refactory.review.engine import ReviewEngine
from refactory.review.models import Repository


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
        "logger": get_service_logger("test.review.pr_scope", "WARNING"),
        "graph_service": MagicMock(),
        "prompt_builder": MagicMock(),
        "ai_gateway": MagicMock(),
        "response_parser": MagicMock(),
    }
    defaults.update(overrides)
    return ReviewEngine(**defaults)  # type: ignore[arg-type]


def _repo_pair(tmp_path: Path) -> tuple[Path, str, str]:
    """Create a repo with main + feature branch; return (root, base_sha, head_sha)."""
    root = tmp_path / "proj"
    root.mkdir()
    repo = Repo.init(root)
    (root / "README.md").write_text("base\n", encoding="utf-8")
    repo.index.add(["README.md"])
    base = repo.index.commit("init on main")
    # Ensure default branch name is main where possible
    try:
        repo.git.branch("-M", "main")
    except Exception:  # noqa: BLE001
        pass
    repo.git.checkout("-b", "feature/pr")
    (root / "feature.py").write_text("def feature():\n    return 1\n", encoding="utf-8")
    repo.index.add(["feature.py"])
    head = repo.index.commit("add feature")
    return root, base.hexsha, head.hexsha


class TestPrScopedDiffGitService:
    def test_three_dot_one_file(self, tmp_path: Path):
        root, _, _ = _repo_pair(tmp_path)
        git = GitService(
            logger=get_service_logger("git", "WARNING"),
            path=root,
            allow_parent_discovery=False,
        )
        paths = git.get_changed_files_three_dot("main", "HEAD")
        assert [p.path for p in paths] == ["feature.py"]
        diff = git.get_unified_diff_three_dot("main", "HEAD")
        assert "feature.py" in diff

    def test_empty_when_head_equals_base(self, tmp_path: Path):
        root, _, _ = _repo_pair(tmp_path)
        repo = Repo(str(root))
        repo.git.checkout("main")
        git = GitService(
            logger=get_service_logger("git", "WARNING"),
            path=root,
            allow_parent_discovery=False,
        )
        assert git.get_changed_files_three_dot("main", "HEAD") == []
        assert git.get_unified_diff_three_dot("main", "HEAD") == ""

    def test_dirty_working_tree_excluded(self, tmp_path: Path):
        root, _, _ = _repo_pair(tmp_path)
        repo = Repo(str(root))
        repo.git.checkout("main")
        (root / "dirt.py").write_text("x = 1\n", encoding="utf-8")
        (root / ".refactory").mkdir()
        (root / ".refactory" / "cache.bin").write_text("x", encoding="utf-8")
        (root / "README.md").write_text("dirty\n", encoding="utf-8")
        git = GitService(
            logger=get_service_logger("git", "WARNING"),
            path=root,
            allow_parent_discovery=False,
        )
        assert git.get_changed_files_three_dot("main", "HEAD") == []
        status = git.get_working_tree_status()
        assert status.is_dirty is True

    def test_unresolvable_base_errors(self, tmp_path: Path):
        root, _, _ = _repo_pair(tmp_path)
        git = GitService(
            logger=get_service_logger("git", "WARNING"),
            path=root,
            allow_parent_discovery=False,
        )
        with pytest.raises(RefactoryError, match="Unable to resolve PR base"):
            git.resolve_diff_base_ref("does-not-exist-branch")


class TestPrScopedReviewEngine:
    def test_empty_pr_short_circuits_without_ai(self, tmp_path: Path):
        repo = Repository(
            name=tmp_path.name,
            root_path=str(tmp_path),
            current_branch="feature",
            default_branch="main",
            head_sha="abc",
        )
        git = MagicMock()
        git.require_repository.return_value = repo
        git.get_default_branch.return_value = "main"
        git.resolve_diff_base_ref.return_value = "main"
        git.get_changed_files_three_dot.return_value = []
        git.get_unified_diff_three_dot.return_value = ""
        git.get_head_sha.return_value = "abc"
        git.get_current_commit.return_value = MagicMock(message="tip")
        git._open_repo.return_value.commit.return_value.hexsha = "base"

        github = MagicMock()
        github.fetch_pull_request.side_effect = NotImplementedError()
        gateway = MagicMock()
        parser = MagicMock()
        prompt_builder = MagicMock()

        engine = _engine(
            git_service=git,
            github_service=github,
            ai_gateway=gateway,
            response_parser=parser,
            prompt_builder=prompt_builder,
        )
        result = engine.review(19)
        assert result.summary == "No changes to review"
        assert result.suggestions == []
        assert result.metadata["empty_pr"] is True
        assert result.metadata["changed_file_count"] == 0
        gateway.generate.assert_not_called()
        prompt_builder.build.assert_not_called()
        # Dirty working tree must not be consulted
        git.get_working_tree_status.assert_not_called()

    def test_one_changed_file_only(self, tmp_path: Path):
        repo = Repository(
            name=tmp_path.name,
            root_path=str(tmp_path),
            current_branch="feature",
            default_branch="main",
        )
        git = MagicMock()
        git.require_repository.return_value = repo
        git.get_default_branch.return_value = "main"
        git.resolve_diff_base_ref.return_value = "origin/main"
        git.get_changed_files_three_dot.return_value = [
            ChangedPath(path="only.py", kind=ChangeKind.ADDED)
        ]
        git.get_unified_diff_three_dot.return_value = (
            "diff --git a/only.py b/only.py\n+print(1)\n"
        )
        git.get_current_commit.return_value = MagicMock(message="add only")
        github = MagicMock()
        github.fetch_pull_request.side_effect = NotImplementedError()

        from refactory.ai.models import AIResponse
        from refactory.response.models import ReviewMetadata
        from refactory.response.models import ReviewResult as ParsedReviewResult
        from refactory.response.models import ReviewSuggestion as ParsedSuggestion

        indexer = MagicMock()
        indexer.ensure_index.return_value = 1
        indexer.load_index.return_value = _index(tmp_path)
        indexer.get_last_index.return_value = _index(tmp_path)
        graph_service = MagicMock()
        graph_service.build_graph.return_value = _graph()
        graph_service.affected_files.return_value = []
        retrieval = MagicMock()
        retrieval.search.return_value = MagicMock(hits=[])
        retrieval.retrieve_related_context.return_value = []
        retrieval.related_files.return_value = []
        prompt_builder = MagicMock()
        prompt_builder.build.return_value = PromptRequest(
            system_prompt="s",
            user_prompt="u",
            metadata=PromptMetadata(template_source="local_default"),
        )
        gateway = MagicMock()
        gateway.generate.return_value = AIResponse(
            text="ok", provider="mock", model="mock", latency_ms=1.0
        )
        parser = MagicMock()
        parser.parse_response.return_value = ParsedReviewResult(
            summary="looks fine",
            overall_risk="low",
            confidence=0.8,
            suggestions=[
                ParsedSuggestion(
                    title="Fix only",
                    explanation="x",
                    severity="low",
                    file="only.py",
                ),
                ParsedSuggestion(
                    title="Ignore dirt",
                    explanation="should be dropped",
                    severity="low",
                    file=".gitignore",
                ),
            ],
            metadata=ReviewMetadata(),
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
        result = engine.review(7)
        assert len(result.suggestions) == 1
        assert result.suggestions[0].file_path == "only.py"
        ctx = prompt_builder.build.call_args.args[0]
        assert [f.path for f in ctx.pull_request.changed_files] == ["only.py"]
        git.get_working_tree_status.assert_not_called()

    def test_missing_base_raises_structured_error(self, tmp_path: Path):
        repo = Repository(
            name=tmp_path.name,
            root_path=str(tmp_path),
            current_branch="feature",
            default_branch="main",
        )
        git = MagicMock()
        git.require_repository.return_value = repo
        git.get_default_branch.return_value = "main"
        git.resolve_diff_base_ref.side_effect = RefactoryError(
            "Unable to resolve PR base branch 'main'."
        )
        github = MagicMock()
        github.fetch_pull_request.side_effect = NotImplementedError()
        engine = _engine(git_service=git, github_service=github)
        with pytest.raises(RefactoryError, match="Unable to resolve PR base"):
            engine.review(19)
        git.get_working_tree_status.assert_not_called()


class TestKicksPr19Acceptance:
    """Live regression when C:\\Users\\ADMIN\\Documents\\KICKS is present."""

    def test_kicks_pr19_empty_diff(self):
        kicks = Path(r"C:\Users\ADMIN\Documents\KICKS")
        if not (kicks / ".git").is_dir():
            pytest.skip("KICKS clone not available")
        git = GitService(
            logger=get_service_logger("git", "WARNING"),
            path=kicks,
            allow_parent_discovery=False,
        )
        info = git.get_repository_info()
        assert (info.default_branch or "") in {"main", "master"}
        # Prefer origin/main when local main is absent
        base = git.resolve_diff_base_ref("main")
        paths = git.get_changed_files_three_dot(base, "HEAD")
        diff = git.get_unified_diff_three_dot(base, "HEAD")
        assert paths == []
        assert (diff or "").strip() == ""

        github = MagicMock()
        github.fetch_pull_request.side_effect = NotImplementedError()
        gateway = MagicMock()
        engine = _engine(git_service=git, github_service=github, ai_gateway=gateway)
        result = engine.review(19, base_branch="main")
        assert result.summary == "No changes to review"
        assert result.suggestions == []
        assert result.metadata.get("changed_file_count") == 0
        gateway.generate.assert_not_called()
        # Untracked .refactory must not appear
        assert not any(
            ".refactory" in (p or "")
            for p in (result.metadata or {}).get("changed_files", [])
        )
