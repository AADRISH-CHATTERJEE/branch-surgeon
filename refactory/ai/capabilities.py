"""Provider capability detection (what a backend can do)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProviderCapabilities(BaseModel):
    """Declarative feature flags for an AIProvider implementation."""

    provider: str
    model: str
    supports_chat: bool = True
    supports_system_prompt: bool = True
    supports_streaming: bool = False
    supports_json_mode: bool = False
    supports_tool_calls: bool = False
    supports_vision: bool = False
    max_context_tokens: int | None = None
    notes: list[str] = Field(default_factory=list)


# Known defaults used when a provider does not override capabilities.
CAPABILITY_DEFAULTS: dict[str, dict[str, object]] = {
    "mock": {
        "supports_streaming": False,
        "supports_json_mode": False,
        "max_context_tokens": 32_000,
        "notes": ["deterministic local stub"],
    },
    "gemini": {
        "supports_streaming": True,
        "supports_json_mode": True,
        "max_context_tokens": 1_000_000,
        "notes": ["Google Generative Language API"],
    },
    "openai": {
        "supports_streaming": True,
        "supports_json_mode": True,
        "supports_tool_calls": True,
        "max_context_tokens": 128_000,
        "notes": ["OpenAI Chat Completions API"],
    },
}


def capabilities_for(provider: str, model: str) -> ProviderCapabilities:
    """Return capability metadata for a known provider name."""
    key = (provider or "").strip().lower()
    defaults = CAPABILITY_DEFAULTS.get(key, {})
    return ProviderCapabilities(
        provider=key or "unknown",
        model=model,
        supports_chat=bool(defaults.get("supports_chat", True)),
        supports_system_prompt=bool(defaults.get("supports_system_prompt", True)),
        supports_streaming=bool(defaults.get("supports_streaming", False)),
        supports_json_mode=bool(defaults.get("supports_json_mode", False)),
        supports_tool_calls=bool(defaults.get("supports_tool_calls", False)),
        supports_vision=bool(defaults.get("supports_vision", False)),
        max_context_tokens=(
            int(defaults["max_context_tokens"])
            if defaults.get("max_context_tokens") is not None
            else None
        ),
        notes=list(defaults.get("notes", [])),  # type: ignore[arg-type]
    )
