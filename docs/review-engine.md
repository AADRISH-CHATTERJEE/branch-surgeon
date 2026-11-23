# ReviewEngine

Orchestrator for repository-aware PR review.

## Public API

```python
build_prompt(review_target: int) -> PromptRequest
review(pr_number: int) -> ReviewResult
```

## Constructor ports

Injected via DI (see `refactory.review.interfaces`):

Git, GitHub, Parser, Indexer, Graph, Retrieval, PromptBuilder, AIGateway, ResponseParser, AIService, Logger, ContextBudget.

## ReviewResult (engine contract)

Core: `pull_request_number`, `summary`, `risk_level`, `suggestions`, `confidence`

Additive telemetry (optional): `provider`, `model`, `latency_ms`, `elapsed_ms`, tokens, cost, `cache_hit`, `warnings`, `metadata`

Orchestration behavior is unchanged when telemetry fields are absent.
