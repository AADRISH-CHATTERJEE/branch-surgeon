# Review Pipeline

## Sequence

```mermaid
sequenceDiagram
  participant CLI
  participant Engine as ReviewEngine
  participant Git as GitService
  participant Idx as IndexerService
  participant Graph as RepositoryGraphService
  participant Ret as RetrievalService
  participant Prompt as PromptBuilder
  participant AI as AIGateway
  participant Parse as ResponseParser

  CLI->>Engine: review(pr_number)
  Engine->>Git: require_repository()
  Engine->>Idx: ensure_index / load_index
  Engine->>Graph: build_graph(index)
  Engine->>Ret: hybrid rank / search
  Engine->>Prompt: build(PromptContext)
  Engine->>AI: generate(AIRequest)
  AI-->>Engine: AIResponse
  Engine->>Parse: parse_response(AIResponse)
  Parse-->>Engine: ParsedReview
  Engine-->>CLI: ReviewResult (+ telemetry)
  CLI->>CLI: Rich report (timings, tokens, warnings)
```

## Stages

1. Resolve repository + PR (GitHub or local synthesis)
2. Ensure deterministic index
3. Build repository graph
4. Gather retrieval / hybrid context
5. Build prompt (no AI)
6. Generate via AIGateway
7. Parse response (never crashes on malformed AI text)
8. Map to engine `ReviewResult` with optional telemetry

`build_prompt()` runs stages 1–5 only (used by `refactory prompt`).
