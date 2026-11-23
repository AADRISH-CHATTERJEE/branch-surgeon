# Provider Guide

## Contract

Implement `AIProvider` (`refactory.ai.interfaces`):

- `name: str`
- `model: str`
- `generate(request: AIRequest) -> AIResponse`
- Optional: `stream`, `capabilities()`, `health_check()`

## Register

1. Add module under `refactory/ai/providers/`.
2. Extend `build_ai_provider()` in `refactory/ai/providers/__init__.py`.
3. Accept configuration from `AISettings` only (not full `Settings`).
4. Map provider errors to `AIProviderError` / `TransientAIProviderError` / `RateLimitAIProviderError`.
5. Add unit tests with mocked HTTP if needed.

## Configuration

```bash
AI_PROVIDER=openai
AI_MODEL=gpt-4o-mini
AI_FALLBACK_PROVIDER=mock
AI_TIMEOUT_SECONDS=60
AI_MAX_RETRIES=2
OPENAI_API_KEY=...
```
