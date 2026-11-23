"""Project-root .env discovery is independent of process cwd."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

import refactory.core.config as config_module
from refactory.core.config import (
    Settings,
    _dotenv_values,
    _environ_map,
    find_project_root,
    get_settings,
)


def _write_project(root: Path, *, ai_provider: str = "openai") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "dotenv-fixture"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    (root / ".env").write_text(
        f"AI_PROVIDER={ai_provider}\nOPENAI_API_KEY=sk-test-from-project-env\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    return _write_project(tmp_path / "repo")


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    config_module._dotenv_debug_logged = False
    yield
    get_settings.cache_clear()
    config_module._dotenv_debug_logged = False


def test_find_project_root_from_config_module_location():
    root = find_project_root()
    assert (root / "pyproject.toml").is_file() or (root / ".git").exists()
    assert root == find_project_root(start=Path(config_module.__file__))


def test_find_project_root_walks_up_from_nested(project_root: Path):
    nested = project_root / "backend" / "refactory_backend" / "services"
    nested.mkdir(parents=True)
    assert find_project_root(start=nested) == project_root.resolve()
    assert find_project_root(start=nested / "config.py") == project_root.resolve()


def test_settings_from_project_root_cwd(project_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config_module, "find_project_root", lambda start=None: project_root.resolve())
    monkeypatch.chdir(project_root)
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    settings = Settings()
    assert settings.ai.provider == "openai"
    assert settings.ai.openai_api_key == "sk-test-from-project-env"


def test_settings_from_backend_cwd(project_root: Path, monkeypatch: pytest.MonkeyPatch):
    backend = project_root / "backend"
    backend.mkdir()
    (backend / ".env").write_text(
        "AI_PROVIDER=mock\nOPENAI_API_KEY=\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "find_project_root", lambda start=None: project_root.resolve())
    monkeypatch.chdir(backend)
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    settings = Settings()
    assert settings.ai.provider == "openai"
    assert bool(settings.ai.openai_api_key) is True
    assert settings.ai.openai_api_key == "sk-test-from-project-env"


def test_settings_from_deeply_nested_cwd(project_root: Path, monkeypatch: pytest.MonkeyPatch):
    nested = project_root / "backend" / "refactory_backend" / "api"
    nested.mkdir(parents=True)
    (nested / ".env").write_text("AI_PROVIDER=mock\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "find_project_root", lambda start=None: project_root.resolve())
    monkeypatch.chdir(nested)
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    settings = Settings()
    assert settings.ai.provider == "openai"
    assert bool(settings.ai.openai_api_key) is True


def test_os_environ_overrides_dotenv(project_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config_module, "find_project_root", lambda start=None: project_root.resolve())
    backend = project_root / "backend"
    backend.mkdir(exist_ok=True)
    monkeypatch.chdir(backend)
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    settings = Settings()
    assert settings.ai.provider == "gemini"
    # Key still comes from project .env when not set in OS env
    assert settings.ai.openai_api_key == "sk-test-from-project-env"


def test_dotenv_values_missing_file_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    (empty_root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "find_project_root", lambda start=None: empty_root.resolve())
    assert _dotenv_values() == {}


def test_environ_map_os_wins_over_dotenv(project_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config_module, "find_project_root", lambda start=None: project_root.resolve())
    monkeypatch.setenv("AI_PROVIDER", "mock")
    merged = _environ_map()
    assert merged["AI_PROVIDER"] == "mock"
    assert merged["OPENAI_API_KEY"] == "sk-test-from-project-env"


def test_debug_logs_resolution_once(
    project_root: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.setattr(config_module, "find_project_root", lambda start=None: project_root.resolve())
    with caplog.at_level(logging.DEBUG, logger="refactory.core.config"):
        _dotenv_values()
        _dotenv_values()
    messages = [record.getMessage() for record in caplog.records]
    assert any(m.startswith("Resolved project root: ") for m in messages)
    assert any(m.startswith("Loaded dotenv: ") for m in messages)
    assert any(m == "Dotenv exists: True" for m in messages)
    assert sum(1 for m in messages if m.startswith("Resolved project root: ")) == 1
    assert not any("sk-test" in m for m in messages)
