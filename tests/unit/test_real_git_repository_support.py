"""Real local Git repository support — root validation, metadata, isolation, safety."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from git import Repo

from refactory.api.app import create_app
from refactory.api.deps import clear_container_cache
from refactory.api.repo_root import validate_repository_root
from refactory.core.exceptions import RepositoryNotFound
from refactory.core.logger import get_service_logger
from refactory.git.paths import safe_repo_relative_path
from refactory.git.service import GitService
from refactory.parser.adapters.ecmascript_adapter import javascript_adapter
from refactory.parser.adapters.json_adapter import JsonLanguageAdapter
from refactory.parser.service import ParserService


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = Repo.init(tmp_path)
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.ts").write_text(
        "import { foo } from './foo';\nexport function run() { return foo; }\n",
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        '{"name":"demo","version":"1.0.0"}\n', encoding="utf-8"
    )
    (tmp_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "skip.js").write_text("export default 1;\n", encoding="utf-8")
    (tmp_path / "mystery.xyz").write_text("not indexed\n", encoding="utf-8")
    repo.index.add(
        ["README.md", "app.py", "src/main.ts", "package.json", "mystery.xyz", ".gitignore"]
    )
    repo.index.commit("init")
    return tmp_path


@pytest.fixture()
def second_repo(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("second-repo")
    repo = Repo.init(root)
    (root / "only.txt").write_text("second\n", encoding="utf-8")
    repo.index.add(["only.txt"])
    repo.index.commit("init second")
    return root


class TestValidateRepositoryRoot:
    def test_valid_repository_root(self, git_repo: Path):
        assert validate_repository_root(git_repo) == git_repo.resolve()

    def test_invalid_missing(self, tmp_path: Path):
        with pytest.raises(RepositoryNotFound, match="does not exist"):
            validate_repository_root(tmp_path / "missing")

    def test_non_git_directory(self, tmp_path: Path):
        with pytest.raises(RepositoryNotFound, match="not a Git repository"):
            validate_repository_root(tmp_path)


class TestGitServiceMetadata:
    def test_metadata_branch_head_remote(self, git_repo: Path):
        logger = get_service_logger("git-test", "WARNING")
        svc = GitService(logger=logger, path=git_repo, allow_parent_discovery=False)
        info = svc.get_repository_info()
        assert info.name == git_repo.name
        assert Path(info.root_path).resolve() == git_repo.resolve()
        assert info.current_branch
        assert info.head_sha
        assert info.working_tree.is_dirty is False
        # No origin configured — remote may be None
        assert info.remote_url is None or isinstance(info.remote_url, str)

    def test_remote_detection(self, git_repo: Path):
        repo = Repo(str(git_repo))
        repo.create_remote("origin", "https://github.com/example/demo.git")
        logger = get_service_logger("git-test", "WARNING")
        svc = GitService(logger=logger, path=git_repo, allow_parent_discovery=False)
        info = svc.get_repository_info()
        assert info.remote_url == "https://github.com/example/demo.git"
        assert info.name == "demo"

    def test_dirty_state(self, git_repo: Path):
        (git_repo / "app.py").write_text("def hello():\n    return 2\n", encoding="utf-8")
        logger = get_service_logger("git-test", "WARNING")
        svc = GitService(logger=logger, path=git_repo, allow_parent_discovery=False)
        status = svc.get_working_tree_status()
        assert status.is_dirty is True

    def test_no_parent_walk_when_explicit(self, git_repo: Path):
        nested = git_repo / "nested"
        nested.mkdir()
        logger = get_service_logger("git-test", "WARNING")
        svc = GitService(logger=logger, path=nested, allow_parent_discovery=False)
        with pytest.raises(RepositoryNotFound):
            svc.get_repository_info()


class TestPathSafety:
    def test_rejects_traversal(self, git_repo: Path):
        assert safe_repo_relative_path(git_repo, "../../etc/passwd") is None
        assert safe_repo_relative_path(git_repo, r"..\..\Windows\System32") is None

    def test_allows_in_repo(self, git_repo: Path):
        target = safe_repo_relative_path(git_repo, "src/main.ts")
        assert target is not None
        assert target.is_file()


class TestMultiLanguageIndexing:
    def test_js_ts_json_adapters_parse(self, git_repo: Path):
        js = javascript_adapter().parse(
            git_repo / "src" / "main.ts",
            (git_repo / "src" / "main.ts").read_text(encoding="utf-8"),
            relative_path="src/main.ts",
        )
        assert js.module.imports
        assert any(fn.name == "run" for fn in js.module.functions)

        json_parsed = JsonLanguageAdapter().parse(
            git_repo / "package.json",
            (git_repo / "package.json").read_text(encoding="utf-8"),
            relative_path="package.json",
        )
        assert any(v.name == "name" for v in json_parsed.module.variables)

    def test_unsupported_file_does_not_crash_index(self, git_repo: Path):
        from refactory.indexer.service import IndexerService

        logger = get_service_logger("idx-test", "WARNING")
        parser = ParserService(ignore_dirs=[".git", "node_modules"], logger=logger)
        indexer = IndexerService(
            parser_service=parser,
            ignore_dirs=[".git", "node_modules", "dist", "build", "coverage", ".cache"],
            logger=logger,
        )
        index = indexer.build_index(git_repo, force=True)
        paths = {f.relative_path for f in index.files}
        assert "app.py" in paths
        assert "src/main.ts" in paths
        assert "package.json" in paths
        assert "mystery.xyz" not in paths
        assert "node_modules/skip.js" not in paths
        assert index.statistics.unsupported_file_count >= 1


class TestApiRepositoryIsolation:
    @pytest.fixture(autouse=True)
    def _clear(self):
        clear_container_cache()
        yield
        clear_container_cache()

    def test_repository_metadata_endpoint(self, git_repo: Path):
        client = TestClient(create_app())
        response = client.get(
            "/repository",
            headers={"X-Repo-Root": str(git_repo)},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        data = body["data"]
        assert data["name"] == git_repo.name
        assert Path(data["root"]).resolve() == git_repo.resolve()
        assert data["branch"]
        assert data["head"]
        assert data["working_tree"] in {"clean", "dirty"}

    def test_invalid_root_returns_clear_error(self, tmp_path: Path):
        client = TestClient(create_app())
        response = client.get(
            "/repository",
            headers={"X-Repo-Root": str(tmp_path)},
        )
        assert response.status_code == 404
        payload = response.json()
        text = " ".join(
            [
                str(payload.get("message") or ""),
                " ".join(payload.get("errors") or []),
            ]
        )
        assert "not a Git repository" in text or "Git" in text

    def test_switch_isolation(self, git_repo: Path, second_repo: Path):
        client = TestClient(create_app())
        first = client.get("/repository", headers={"X-Repo-Root": str(git_repo)}).json()[
            "data"
        ]
        second = client.get(
            "/repository", headers={"X-Repo-Root": str(second_repo)}
        ).json()["data"]
        again = client.get("/repository", headers={"X-Repo-Root": str(git_repo)}).json()[
            "data"
        ]
        assert first["name"] == git_repo.name
        assert second["name"] == second_repo.name
        assert again["name"] == git_repo.name
        assert Path(first["root"]).resolve() != Path(second["root"]).resolve()
