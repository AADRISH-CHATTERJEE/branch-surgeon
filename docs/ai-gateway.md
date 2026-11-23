# AI Gateway

`refactory.ai.gateway.AIGateway` is provider-agnostic.

## Features

- Retries with exponential backoff
- Optional fallback provider
- Health checks + capability discovery
- Usage / cost estimation
- Optional response cache (`CACHE_AI_RESPONSES`)
- `last_cache_hit` for CLI indicators

## Flow

```mermaid
flowchart TD
  Req[AIRequest] --> Cache{Response cache?}
  Cache -->|hit| Out[AIResponse]
  Cache -->|miss| Primary[Primary provider]
  Primary -->|transient / rate limit| Retry[Backoff retry]
  Retry --> Primary
  Primary -->|exhausted| Fallback[Fallback provider]
  Fallback --> Out
  Primary -->|success| Out
```

## Providers

| Name | Env | Module |
|------|-----|--------|
| `mock` | default | `ai.providers.mock` |
| `gemini` | `GEMINI_API_KEY` | `ai.providers.gemini` |
| `openai` | `OPENAI_API_KEY` | `ai.providers.openai` |

Factory: `build_ai_provider` / `build_ai_provider_pair` take `AISettings`.
