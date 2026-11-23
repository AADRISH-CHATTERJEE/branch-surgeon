"""Context budget limits for prompt assembly (configurable)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ContextBudget(BaseModel):
    """Hard caps applied while assembling review prompts."""

    max_tokens: int = Field(default=6000, ge=256)
    max_retrieved_files: int = Field(default=8, ge=0)
    max_symbols: int = Field(default=16, ge=0)
    max_related_files: int = Field(default=8, ge=0)
    max_graph_depth: int = Field(default=3, ge=0)
    template_version: str = "2.0.0"

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Cheap deterministic token estimate (~4 chars / token)."""
        if not text:
            return 0
        return max(1, (len(text) + 3) // 4)

    @classmethod
    def from_settings(cls, settings: object) -> "ContextBudget":
        """Build from ``PromptSettings`` or a legacy object with prompt_* attrs."""
        prompt = getattr(settings, "prompt", settings)
        return cls(
            max_tokens=int(getattr(prompt, "max_tokens", getattr(settings, "prompt_max_tokens", 6000))),
            max_retrieved_files=int(
                getattr(
                    prompt,
                    "max_retrieved_files",
                    getattr(settings, "prompt_max_retrieved_files", 8),
                )
            ),
            max_symbols=int(
                getattr(prompt, "max_symbols", getattr(settings, "prompt_max_symbols", 16))
            ),
            max_related_files=int(
                getattr(
                    prompt,
                    "max_related_files",
                    getattr(settings, "prompt_max_related_files", 8),
                )
            ),
            max_graph_depth=int(
                getattr(
                    prompt,
                    "max_graph_depth",
                    getattr(settings, "prompt_max_graph_depth", 3),
                )
            ),
            template_version=str(
                getattr(
                    prompt,
                    "template_version",
                    getattr(settings, "prompt_template_version", "2.0.0"),
                )
            ),
        )
