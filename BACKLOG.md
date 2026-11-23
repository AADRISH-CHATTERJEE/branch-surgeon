# Refactory Backlog

> Items below are organized by subsystem, prioritized P0–P3, and ordered by
> recommended implementation sequence. Completed legacy items are archived at
> the bottom.

---

## Recommended Implementation Order

| Phase | Items | Rationale |
|-------|-------|-----------|
| 1 | PS-1, PS-7 | Database persistence and deterministic IDs are foundations for everything else |
| 2 | PS-2, PS-6 | Health scoring depends on persistence (Phase 1) |
| 3 | CT-4, CT-1, CT-7 | Fix patch generation so transformations produce valid output |
| 4 | CT-6, CT-5 | Validation and rollback depend on working patches (Phase 3) |
| 5 | CT-2, CT-3 | Real AST transformations depend on validated pipeline (Phase 4) |
| 6 | PS-3, PS-5 | Trends and enriched recommendations depend on persisted history (Phase 1) |
| 7 | PS-4 | Bootstrap command ties together rules, policies, prompts, and storage |
| 8 | PR-1 | AI review enrichment is independent; lower urgency |
| 9 | PS-8 | Fix init-generated rules.yaml so RuleEngine can parse it (depends on PS-4) |

### Dependency Graph

```
PS-1 ──► PS-2, PS-3, PS-6, CT-5
PS-7 ──► CT-5 (stable IDs needed for history tracking)
CT-4 ──► CT-1, CT-7 (valid Python required before patch generation)
CT-1 ──► CT-2, CT-3, CT-5, CT-7
CT-6 ──► CT-2, CT-3 (validation before real transformations)
PS-1 ──► PS-4 (database must exist before bootstrap creates it)
PS-4 ──► PS-8 (rules.yaml must exist before it can be fixed)
```

---

## Platform Stabilization

### PS-1 — Persistent SQLite database creation

Priority: **P0**

Status: **Completed** (Phase 1)

Dependencies: None

StorageService creates a persistent SQLite database at `.refactory/storage/refactory.db`
relative to the repository root. Data persists across CLI sessions.

---

### PS-2 — Repository Health must reflect actual analysis

Priority: **P0**

Status: **Completed** (Phase 2)

Dependencies: PS-1

Health scores are now derived from real analysis including RecommendationEngine
findings, RuleEngine violations, Technical Debt, Security, Testing, and
Documentation findings. Severity-weighted penalties replace static defaults.

---

### PS-3 — Historical metrics and trend persistence

Priority: **P1**

Status: **Completed** (Phase 6)

Dependencies: PS-1

Trends now track all health dimensions (architecture, security, testing,
documentation, maintainability, performance, technical debt) and transformation
activity. Degrading and improving modules are identified.

---

### PS-4 — Repository bootstrap (`refactory init`)

Priority: **P1**

Status: **Completed** (Phase 7)

Dependencies: PS-1

`refactory init` generates `.refactory/rules.yaml`, `architecture.yaml`,
`company.yaml`, `prompts.yaml`, and `storage/refactory.db`. Supports `--force`
to overwrite existing files. Idempotent.

---

### PS-5 — Recommendation Engine enrichment

Priority: **P1**

Status: **Completed** (Phase 6)

Dependencies: PS-1

Scoring now includes severity weights and transformation opportunity bonuses.
Explanations indicate auto-fixable items and estimated patch sizes.
Documentation and rule violation categories have enriched explanations.

---

### PS-6 — Health Dashboard dynamic scoring

Priority: **P0**

Status: **Completed** (Phase 2)

Dependencies: PS-1, PS-2

Health Dashboard aggregates RecommendationEngine, RuleEngine,
ArchitecturePolicyService, Technical Debt, Security, Documentation, and
Testing findings. Per-dimension metrics are persisted for trend tracking.

---

### PS-7 — Deterministic recommendation IDs

Priority: **P0**

Status: **Completed** (Phase 1)

Dependencies: None

IDs are now generated via `sha256(repository|file|category|symbol_or_title)`.
Same analysis input produces stable IDs for history tracking and dismissal.

---

### PS-8 — Fix generated rules.yaml

Priority: **P0**

Status: Open

Dependencies: PS-4

The `refactory init` command generates a `rules.yaml` that cannot be parsed by
the RuleEngine.

Problems:

- `conditions` is a flat dict (`max_lines: 50`) but `_parse_rules_data` expects
  a list of `RuleCondition` objects with `field`/`operator`/`value`/`pattern`.
- Categories `complexity` and `best_practices` are not valid `RuleCategory`
  enum values. Valid categories include `max_function_size`, `max_file_size`,
  `forbidden_import`, `custom`, etc.

Acceptance criteria:

- `refactory init` generates a valid YAML schema matching the `RuleCondition`
  and `RuleCategory` models.
- `refactory recommend` loads rules successfully from the generated file.
- No `RuleCondition` parsing exceptions.
- At least one sample rule is evaluated during `recommend`.

---

## Code Transformation

### CT-1 — PatchGenerator must produce real unified diffs

Priority: **P0**

Status: **Completed** (Phase 3)

Dependencies: CT-4

PatchGenerator now reads original content from disk when not provided in the
step, and always produces proper unified diffs compatible with `git apply`.

---

### CT-2 — Real AST-based Rename Symbol transformation

Priority: **P0**

Status: **Completed** (Phase 5)

Dependencies: CT-1, CT-6

Rename uses AST analysis to find all symbol references (Names, FunctionDefs,
ClassDefs, Attributes, args, aliases). Produces safe, scoped replacements
instead of naive string replacement.

---

### CT-3 — Real Extract Method transformation

Priority: **P1**

Status: **Completed** (Phase 5)

Dependencies: CT-1, CT-6

Extract Method uses AST to detect variables used in the extracted block that
are defined outside. Generates a new function with the right parameters,
places the call at the extraction site, and inserts the definition at the
correct scope level.

---

### CT-4 — Fix Generate Docstrings output

Priority: **P0**

Status: **Completed** (Phase 3)

Dependencies: None

Docstring generation now uses proper indentation detection. Module-level
functions get 4-space indent docstrings, methods get 8-space. Output always
parses as valid Python.

---

### CT-5 — Persist transformation history for rollback

Priority: **P0**

Status: **Completed** (Phase 4)

Dependencies: PS-1, CT-1

Transformation history (plan, patch, rollback patch, file contents) is
persisted via StorageService. History is loaded on service restart so rollback
works across CLI sessions.

---

### CT-6 — Validate transformation types

Priority: **P0**

Status: **Completed** (Phase 4)

Dependencies: None

Unsupported transformation types are rejected with clear error messages listing
supported types. Both `transform` (preview) and `apply` validate before proceeding.

---

### CT-7 — Preview and Transform must generate real diffs

Priority: **P0**

Status: **Completed** (Phase 3)

Dependencies: CT-1, CT-4

Preview and Transform commands now generate proper unified diffs with
`--- a/` and `+++ b/` headers, showing additions and deletions.

---

## PR Intelligence

### PR-1 — Improve AI Review Generation

Priority: **P2**

Status: **Completed** (Phase 8)

Dependencies: None

ReviewComment now includes Severity, Category, File, Line, Explanation,
Suggested Fix, Confidence, and Estimated Impact. Heuristic review detects
eval/exec, bare except, wildcard imports, hardcoded secrets, and more.
AI prompt requests structured output matching the ReviewComment schema.

---

## Completed (Archive)

<details>
<summary>Backlog 1–9 and Issue 7 note (all implemented)</summary>

### Backlog 1 — Fully hybrid `refactory related`

Status: Implemented

### Backlog 2 — Validate semantic retrieval quality after embeddings

Status: Implemented

### Backlog 3 — Improve complexity estimation heuristics

Status: Implemented

### Backlog 4 — Prioritize production code over tests/demos in candidate ranking

Status: Implemented

### Backlog 5 — Exclude demo/example files from implementation planning

Status: Implemented

### Backlog 6 — Prevent test files from receiving HIGH impact by default

Status: Implemented

### Backlog 7 — Display original requirement text in CLI output

Status: Implemented

### Backlog 8 — Sanitize pasted control characters before parsing

Status: Implemented

### Backlog 9 — Batch semantic retrieval queries to reduce analysis time

Status: Implemented

### Issue 7 note — Search / docstring behavior

Investigated, no code change required.

</details>
