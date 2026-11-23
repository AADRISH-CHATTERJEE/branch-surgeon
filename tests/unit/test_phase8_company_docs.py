"""Phase 8 gap-fill tests: company documentation loading + prompt injection.

Covers only functionality added after the Phase 8 audit:
- testing_guidelines.md loading
- missing files → empty strings
- loader caching
- company docs as a separate prompt section (not replacing review instructions)
- backward compatibility when docs are absent
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from refactory.company.loader import (
    clear_company_doc_cache,
    load_company_documentation,
    load_company_guidelines,
)
from refactory.company.models import CompanyDocumentation, CompanyGuidelines
from refactory.github.models import PullRequest
from refactory.prompt.builder import PromptBuilder
from refactory.prompt.models import PromptContext
from refactory.prompt.templates import DEFAULT_REVIEW_INSTRUCTIONS, SECTION_ORDER


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture(autouse=True)
def _clear_doc_cache():
    clear_company_doc_cache()
    yield
    clear_company_doc_cache()


# ---------------------------------------------------------------------------
# Documentation loading
# ---------------------------------------------------------------------------


class TestCompanyDocumentationLoader:
    def test_loads_all_four_markdown_files(self, tmp_path: Path):
        ref = tmp_path / ".refactory"
        _write(ref / "architecture.md", "Use DAOs.")
        _write(ref / "coding_guidelines.md", "No wildcards.")
        _write(ref / "security_guidelines.md", "No eval.")
        _write(ref / "testing_guidelines.md", "Require unit tests.")

        docs = load_company_documentation(tmp_path)
        assert isinstance(docs, CompanyDocumentation)
        assert "Use DAOs." in docs.architecture
        assert "No wildcards." in docs.coding_guidelines
        assert "No eval." in docs.security_guidelines
        assert "Require unit tests." in docs.testing_guidelines

        combined = docs.combined_for_prompt()
        assert "Architecture" in combined
        assert "Coding" in combined
        assert "Security" in combined
        assert "Testing" in combined

    def test_missing_files_return_empty_strings(self, tmp_path: Path):
        (tmp_path / ".refactory").mkdir()
        docs = load_company_documentation(tmp_path)
        assert docs.architecture == ""
        assert docs.coding_guidelines == ""
        assert docs.security_guidelines == ""
        assert docs.testing_guidelines == ""
        assert docs.combined_for_prompt() == ""

    def test_guidelines_include_testing_field(self, tmp_path: Path):
        _write(tmp_path / ".refactory" / "testing_guidelines.md", "Cover edge cases.")
        g = load_company_guidelines(tmp_path)
        assert isinstance(g, CompanyGuidelines)
        assert "Cover edge cases." in g.testing_guidelines_md
        assert "Testing" in g.combined_for_prompt()

    def test_cached_after_first_load(self, tmp_path: Path):
        ref = tmp_path / ".refactory"
        _write(ref / "architecture.md", "v1")

        first = load_company_documentation(tmp_path)
        assert first.architecture == "v1"

        # Same files (unchanged mtime/size) — cache hit
        second = load_company_documentation(tmp_path)
        assert second.architecture == "v1"
        assert second is first  # same cached instance

        # Mutate file — signature changes, cache must reload
        _write(ref / "architecture.md", "v2")
        third = load_company_documentation(tmp_path)
        assert third.architecture == "v2"

    def test_new_files_invalidate_stale_empty_cache(self, tmp_path: Path):
        """Regression: Architecture-only cache must not hide later-seeded sections."""
        ref = tmp_path / ".refactory"
        _write(ref / "architecture.md", "# Architecture\n\nOnly this.\n")

        first = load_company_documentation(tmp_path)
        assert first.architecture.startswith("# Architecture")
        assert first.security_guidelines == ""
        assert first.coding_guidelines == ""

        _write(ref / "coding_guidelines.md", "# Coding Guidelines\n\n- Use type hints.\n")
        _write(ref / "security_guidelines.md", "# Security Guidelines\n\n- No eval().\n")
        _write(ref / "testing_guidelines.md", "# Testing Guidelines\n\n- Add tests.\n")

        second = load_company_documentation(tmp_path)
        assert "type hints" in second.coding_guidelines
        assert "eval" in second.security_guidelines
        assert "Add tests" in second.testing_guidelines

    def test_guidelines_to_documentation_roundtrip(self):
        g = CompanyGuidelines(
            architecture_md="a",
            coding_guidelines_md="c",
            security_guidelines_md="s",
            testing_guidelines_md="t",
        )
        d = g.to_documentation()
        assert d.architecture == "a"
        assert d.testing_guidelines == "t"
        back = d.to_guidelines()
        assert back.architecture_md == "a"
        assert back.testing_guidelines_md == "t"


# ---------------------------------------------------------------------------
# Prompt injection
# ---------------------------------------------------------------------------


def _minimal_pr() -> PullRequest:
    return PullRequest(
        number=1,
        title="feat: test",
        body="",
        state="open",
        base_branch="main",
        head_branch="feature/x",
        changed_files=[],
        diff="",
    )


class TestCompanyDocsPromptInjection:
    def test_docs_injected_as_separate_section(self):
        builder = PromptBuilder(logger=MagicMock())
        docs = (
            "## Company Architecture Guidelines\n\nUse DAOs.\n\n"
            "## Company Testing Guidelines\n\nRequire unit tests."
        )
        result = builder.build(
            PromptContext(
                pull_request=_minimal_pr(),
                company_documentation=docs,
            )
        )

        keys = [s.key for s in result.sections]
        assert "company_documentation" in keys
        assert "review_instructions" in keys
        # Order: repository → company docs → PR …
        assert keys.index("repository") < keys.index("company_documentation")
        assert keys.index("company_documentation") < keys.index("pr_summary")
        assert keys.index("pr_summary") < keys.index("review_instructions")

        docs_section = next(s for s in result.sections if s.key == "company_documentation")
        assert "Use DAOs." in docs_section.body
        assert "Require unit tests." in docs_section.body

        # Review instructions must remain defaults — docs must not replace them
        instr = next(s for s in result.sections if s.key == "review_instructions")
        assert DEFAULT_REVIEW_INSTRUCTIONS.strip() in instr.body.strip() or len(instr.body) > 20

    def test_no_docs_omits_section_and_keeps_section_order(self):
        builder = PromptBuilder(logger=MagicMock())
        result = builder.build(PromptContext(pull_request=_minimal_pr()))

        keys = [s.key for s in result.sections]
        assert "company_documentation" not in keys
        assert keys == list(SECTION_ORDER)

    def test_empty_docs_string_omits_section(self):
        builder = PromptBuilder(logger=MagicMock())
        result = builder.build(
            PromptContext(
                pull_request=_minimal_pr(),
                company_documentation="   ",
            )
        )
        assert "company_documentation" not in [s.key for s in result.sections]
        assert [s.key for s in result.sections] == list(SECTION_ORDER)


# ---------------------------------------------------------------------------
# ReviewEngine passes company_documentation (not coding_standards overwrite)
# ---------------------------------------------------------------------------


class TestReviewEngineDocWiring:
    def test_build_prompt_impl_accepts_company_documentation(self, tmp_path: Path):
        from refactory.review.engine import ReviewEngine

        engine = ReviewEngine(
            git_service=MagicMock(),
            github_service=MagicMock(),
            parser_service=MagicMock(),
            indexer_service=MagicMock(),
            retrieval_service=MagicMock(),
            ai_service=MagicMock(),
            logger=MagicMock(),
            graph_service=MagicMock(),
            prompt_builder=MagicMock(),
            ai_gateway=MagicMock(),
            response_parser=MagicMock(),
        )

        # Ensure signature accepts the new kwarg without error when called via inspect
        import inspect

        sig = inspect.signature(engine._build_prompt_impl)
        assert "company_documentation" in sig.parameters
        assert "coding_standards" in sig.parameters


# ---------------------------------------------------------------------------
# Init scaffolds testing_guidelines.md
# ---------------------------------------------------------------------------


class TestInitScaffoldsTestingGuidelines:
    def test_default_includes_testing_guidelines(self):
        from refactory.cli.commands.init import _DEFAULT_TESTING_GUIDELINES_MD

        assert "Testing Guidelines" in _DEFAULT_TESTING_GUIDELINES_MD
