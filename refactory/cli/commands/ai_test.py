"""`refactory ai-test` — smoke-test the AI gateway with a small prompt."""

from __future__ import annotations

from refactory.ai.models import AIRequest
from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console
from refactory.cli.ui.panels import section_panel
from refactory.cli.ui.progress import loading
from refactory.cli.ui.style import format_cache_hit, format_cost_usd, format_ms
from refactory.cli.ui.tables import key_value_table
from refactory.github.models import ChangedFile, PullRequest
from refactory.prompt.models import PromptContext
from refactory.review.models import Repository


def ai_test() -> None:
    """Build a tiny PromptRequest, send via AIGateway, print provider/model/latency/text."""
    try:
        container = get_container()
        context = PromptContext(
            pull_request=PullRequest(
                number=1,
                title="AI gateway smoke test",
                body="Synthetic PR used only for `refactory ai-test`.",
                changed_files=[
                    ChangedFile(path="auth.py", status="modified", additions=2, deletions=0),
                ],
            ),
            repository=Repository(
                name="demo-repo",
                root_path=".",
                current_branch="main",
            ),
        )
        with loading("Calling AI gateway…"):
            prompt = container.prompt_builder.build(context)
            request = AIRequest.from_prompt_request(prompt)
            response = container.ai_gateway.generate(request)

        console.print(
            key_value_table(
                "AI Gateway Test",
                {
                    "Provider": response.provider,
                    "Model": response.model,
                    "Cache": format_cache_hit(container.ai_gateway.last_cache_hit),
                    "Latency": format_ms(response.latency_ms),
                    "Finish reason": response.finish_reason or "(none)",
                    "Prompt tokens": response.prompt_tokens
                    if response.prompt_tokens is not None
                    else "(n/a)",
                    "Completion tokens": response.completion_tokens
                    if response.completion_tokens is not None
                    else "(n/a)",
                    "Est. cost": format_cost_usd(response.estimated_cost_usd),
                },
            )
        )
        console.print()
        console.print(section_panel("Response", response.text, border_style="magenta"))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
