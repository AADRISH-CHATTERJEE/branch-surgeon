"""Unit tests for prompt document formatting (CLI presentation helper)."""

from __future__ import annotations

from refactory.cli.commands.prompt import format_prompt_document
from refactory.prompt.models import PromptMetadata, PromptRequest


def test_format_prompt_document_layout():
    prompt = PromptRequest(
        system_prompt="Be concise.\n",
        user_prompt="## Changed Files\n\n- auth.py\n",
        metadata=PromptMetadata(
            template_source="local_default",
            template_name="review",
            repository_name="demo",
            pr_number=9,
            section_keys=["changed_files"],
        ),
    )
    text = format_prompt_document(prompt)

    assert text.startswith("====================================\nSYSTEM PROMPT\n")
    assert "Be concise." in text
    assert "====================================\nUSER PROMPT\n" in text
    assert "## Changed Files" in text
    assert "====================================\nMETADATA\n" in text
    assert '"pr_number": 9' in text
    assert '"template_source": "local_default"' in text
