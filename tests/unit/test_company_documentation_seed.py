"""Seeded company documentation for the Documentation Center."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from refactory.company.defaults import DEFAULT_ARCHITECTURE_MD
from refactory.company.loader import clear_company_doc_cache, load_company_documentation
from refactory.company.models import CompanyDocumentation
from refactory.company.seed import ensure_default_documentation, write_documentation


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_company_doc_cache()
    yield
    clear_company_doc_cache()


def test_ensure_creates_all_four_files(tmp_path: Path):
    result = ensure_default_documentation(tmp_path)
    assert result.seeded is True
    assert len(result.created) == 4
    assert (tmp_path / ".refactory" / "architecture.md").is_file()
    assert (tmp_path / ".refactory" / "coding_guidelines.md").is_file()
    assert (tmp_path / ".refactory" / "security_guidelines.md").is_file()
    assert (tmp_path / ".refactory" / "testing_guidelines.md").is_file()

    docs = load_company_documentation(tmp_path)
    assert "layered architecture" in docs.architecture.lower()
    assert "type hints" in docs.coding_guidelines.lower()
    assert "hardcode credentials" in docs.security_guidelines.lower()
    assert "80% coverage" in docs.testing_guidelines.lower()


def test_ensure_never_overwrites_existing(tmp_path: Path):
    ref = tmp_path / ".refactory"
    ref.mkdir()
    custom = "# Custom Architecture\n\nDo not overwrite me.\n"
    (ref / "architecture.md").write_text(custom, encoding="utf-8")

    result = ensure_default_documentation(tmp_path)
    assert ".refactory/architecture.md" in result.skipped
    assert len(result.created) == 3
    assert (ref / "architecture.md").read_text(encoding="utf-8") == custom
    assert custom != DEFAULT_ARCHITECTURE_MD


def test_ensure_idempotent(tmp_path: Path):
    first = ensure_default_documentation(tmp_path)
    second = ensure_default_documentation(tmp_path)
    assert first.seeded is True
    assert second.seeded is False
    assert second.created == []
    assert len(second.skipped) == 4


def test_write_documentation_updates_and_clears_cache(tmp_path: Path):
    ensure_default_documentation(tmp_path)
    docs = load_company_documentation(tmp_path)
    assert "layered architecture" in docs.architecture.lower()

    updated = CompanyDocumentation(
        architecture="# Architecture\n\nUpdated layer notes.\n",
        coding_guidelines=docs.coding_guidelines,
        security_guidelines=docs.security_guidelines,
        testing_guidelines=docs.testing_guidelines,
    )
    written = write_documentation(tmp_path, updated, fields={"architecture"})
    assert written == [".refactory/architecture.md"]

    reloaded = load_company_documentation(tmp_path)
    assert "Updated layer notes" in reloaded.architecture


def test_get_documentation_seeds_and_records_history(tmp_path: Path):
    from refactory.api.routes.documentation import get_documentation

    container = MagicMock()
    container.git_service.get_root_path.return_value = str(tmp_path)
    container.query_service.get_repository_by_root.return_value = {"id": "repo-1"}
    container.git_service.get_repository_metadata.return_value = MagicMock(
        name="demo", root_path=str(tmp_path)
    )
    container.persistence_service.persist_analysis_run = MagicMock()

    # Patch persist path used inside the route
    response = get_documentation(container, tmp_path)  # type: ignore[arg-type]
    assert response.status == "success"
    assert response.data is not None
    assert "layered architecture" in response.data["architecture"].lower()
    assert response.meta.get("seeded") is True

    container.persistence_service.persist_analysis_run.assert_called()
    call_kwargs = container.persistence_service.persist_analysis_run.call_args.kwargs
    assert call_kwargs["summary"] == "Documentation initialized"


def test_put_documentation_records_update_history(tmp_path: Path):
    from refactory.api.routes.documentation import (
        DocumentationUpdateRequest,
        update_documentation,
    )

    ensure_default_documentation(tmp_path)
    clear_company_doc_cache()

    container = MagicMock()
    container.git_service.get_root_path.return_value = str(tmp_path)
    container.query_service.get_repository_by_root.return_value = {"id": "repo-1"}
    container.git_service.get_repository_metadata.return_value = MagicMock(
        name="demo", root_path=str(tmp_path)
    )
    container.persistence_service.persist_analysis_run = MagicMock()

    body = DocumentationUpdateRequest(
        coding_guidelines="# Coding Guidelines\n\n- Prefer dataclasses.\n"
    )
    response = update_documentation(body, container, tmp_path)  # type: ignore[arg-type]
    assert response.status == "success"
    assert response.message == "Documentation updated"
    assert "Prefer dataclasses" in response.data["coding_guidelines"]

    call_kwargs = container.persistence_service.persist_analysis_run.call_args.kwargs
    assert call_kwargs["summary"] == "Documentation updated"
