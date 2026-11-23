"""Tests for GET /repository/file content preview."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from git import Repo

from refactory.api.app import app
from refactory.api.deps import get_container, resolve_repo_root
from refactory.core.logger import get_service_logger
from refactory.git.service import FILE_PREVIEW_MAX_BYTES, GitService


def _logger():
    return get_service_logger("test.repo.file")


def _init_repo(path: Path) -> Repo:
    repo = Repo.init(path, initial_branch="main")
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test User")
        config.set_value("user", "email", "test@example.com")
    (path / "README.md").write_text("# demo\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("initial")
    return repo


@pytest.fixture
def repo_path(tmp_path: Path) -> Path:
    root = tmp_path / "demo-repo"
    root.mkdir()
    _init_repo(root)
    (root / "auth.py").write_text("def validate_token(token):\n    return True\n", encoding="utf-8")
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_auth.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (root / "blob.bin").write_bytes(b"\x00\x01\x02\xffbinary")
    return root


@pytest.fixture
def git_service(repo_path: Path) -> GitService:
    return GitService(logger=_logger(), path=repo_path)


class TestGitServicePreview:
    def test_existing_file(self, git_service: GitService):
        preview = git_service.preview_working_file("auth.py")
        assert preview.status == "ok"
        assert preview.path == "auth.py"
        assert preview.language == "python"
        assert "validate_token" in (preview.content or "")
        assert preview.sha
        assert preview.size and preview.size > 0

    def test_nested_file(self, git_service: GitService):
        preview = git_service.preview_working_file("tests/test_auth.py")
        assert preview.status == "ok"
        assert preview.path == "tests/test_auth.py"
        assert "test_ok" in (preview.content or "")

    def test_nonexistent_file(self, git_service: GitService):
        preview = git_service.preview_working_file("missing.py")
        assert preview.status == "not_found"

    def test_path_traversal(self, git_service: GitService):
        preview = git_service.preview_working_file("../../etc/passwd")
        assert preview.status in {"unsafe", "not_found"}
        assert preview.content is None

    def test_binary_file(self, git_service: GitService):
        preview = git_service.preview_working_file("blob.bin")
        assert preview.status == "binary"

    def test_oversized_file(self, git_service: GitService, repo_path: Path):
        big = repo_path / "huge.txt"
        big.write_bytes(b"a" * (FILE_PREVIEW_MAX_BYTES + 10))
        preview = git_service.preview_working_file("huge.txt")
        assert preview.status == "too_large"
        assert preview.content is None


@pytest.fixture
def api_client(repo_path: Path):
    container = MagicMock()
    container.git_service = GitService(logger=_logger(), path=repo_path)
    container.query_service.get_repository_by_root.return_value = {
        "id": "repo1",
        "name": "demo-repo",
        "root_path": str(repo_path),
    }
    container.query_service.get_file.return_value = {
        "id": "f-auth",
        "path": "auth.py",
        "language": "python",
        "sha256": "indexed-sha",
        "size": 42,
    }

    def _container():
        return container

    def _root():
        return repo_path.resolve()

    app.dependency_overrides[get_container] = _container
    app.dependency_overrides[resolve_repo_root] = _root
    with TestClient(app) as client:
        yield client, container
    app.dependency_overrides.clear()


class TestRepositoryFileRoute:
    def test_existing_file(self, api_client):
        client, _ = api_client
        resp = client.get("/repository/file", params={"path": "auth.py"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["path"] == "auth.py"
        assert data["language"] == "python"
        assert "validate_token" in data["content"]
        assert data["sha"] == "indexed-sha"
        assert data["size"] == 42

    def test_nested_file(self, api_client):
        client, container = api_client
        container.query_service.get_file.return_value = None
        resp = client.get("/repository/file", params={"path": "tests/test_auth.py"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["path"] == "tests/test_auth.py"
        assert data["language"] == "python"
        assert "test_ok" in data["content"]

    def test_nonexistent_file(self, api_client):
        client, _ = api_client
        resp = client.get("/repository/file", params={"path": "nope.py"})
        assert resp.status_code == 404
        assert resp.json()["status"] == "error"

    def test_path_traversal(self, api_client):
        client, _ = api_client
        resp = client.get("/repository/file", params={"path": "../../etc/passwd"})
        assert resp.status_code in {400, 404}
        assert resp.json()["status"] == "error"
        assert "content" not in (resp.json().get("data") or {})

    def test_binary_file(self, api_client):
        client, container = api_client
        container.query_service.get_file.return_value = None
        resp = client.get("/repository/file", params={"path": "blob.bin"})
        assert resp.status_code == 415
        assert "Binary" in resp.json()["message"]

    def test_oversized_file(self, api_client, repo_path: Path):
        client, container = api_client
        container.query_service.get_file.return_value = None
        (repo_path / "huge.txt").write_bytes(b"a" * (FILE_PREVIEW_MAX_BYTES + 5))
        resp = client.get("/repository/file", params={"path": "huge.txt"})
        assert resp.status_code == 413
        assert "large" in resp.json()["message"].lower()
