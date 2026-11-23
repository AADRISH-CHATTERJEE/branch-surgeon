# Prompt Builder

`PromptBuilder` assembles `PromptRequest` from index/graph/retrieval context.

## Inputs (`PromptContext`)

- Pull request + repository
- Repository index + graph
- Retrieval / hybrid ranked context
- Optional backend template + workflow
- `ContextBudget` (from `PromptSettings`)

## Outputs

- `system_prompt` / `user_prompt`
- Ordered sections
- `PromptMetadata` (template source/version, token estimate, counts)

## Rules

- Never calls an LLM
- Deterministic section order (`SECTION_ORDER`)
- Token budget trims optional sections first
- Optional deterministic cache keyed by repo hashes + prompt version + context fingerprint
