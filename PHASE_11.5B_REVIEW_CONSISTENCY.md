# Phase 11.5B — Review UI Consistency & Polish

Bug-fix and UX consistency only. No ReviewEngine, prompt, or recommendation changes.

## Root cause — Suggestions count mismatch

| Surface | Data source | Result |
|---------|-------------|--------|
| History table | `suggestions?.length ?? 0` | **0** (list payload had no `suggestions`) |
| Detail | `suggestions.length` after `GET /review/{id}` | **3** |

`GET /reviews` returned `_review_to_dict()` without suggestion stats. Suggestions live in `db_review_suggestions` and were only loaded on detail.

**Fix:** Enrich list + detail review DTOs with:

- `suggestion_count`
- `file_count`
- `critical_count`
- `warning_count`

Computed from persisted suggestion rows (no schema migration). History UI reads `suggestion_count` via `reviewSuggestionCount()`.

## Risk card behavior

Category scores (Security / Architecture / Maintainability / Testing) are **not** produced by the persisted review model.

**Option A (implemented):** `RiskSummary` only renders cards with real values. Detail passes `{ overall }` derived from persisted `risk`. Empty `"—"` placeholders are gone.

## Auto-select first file

On detail load, when `changedFiles.length > 0`, the selected file is derived as `changedFiles[0]` (user pick wins when still valid). No effect-driven `setState`; code viewer and suggestion filter activate immediately.

## Empty states

- No changed files → “No changed files were analyzed.”
- No suggestions → “No AI suggestions generated.”
- No findings for file → “No issues detected.”

## Progressive loading

Detail route keeps header / toolbar / metric chrome visible; summary + workspace skeleton while `GET /review/{id}` loads. Uses list preview for title when available.

## Metrics consistency

Shared helpers in `ui/lib/review-metrics.ts` read the same persisted fields for History, Detail, Summary, and metric cards:

| Metric | Source |
|--------|--------|
| Suggestions | `suggestion_count` (fallback: `suggestions.length`) |
| Files | `file_count` (fallback: unique suggestion files) |
| Critical / Warnings | `critical_count` / `warning_count` |
| Overall score | persisted `risk` |
| Confidence | persisted `confidence` |

Backend `RepositoryQueryService.suggestion_stats()` is the single computation path for list and detail DTOs.

## Files modified

| File | Change |
|------|--------|
| `refactory/db/repositories/review_suggestion.py` | `list_by_review_ids` |
| `refactory/db/query_service.py` | `suggestion_stats`, enrich `_review_to_dict` / `get_reviews` / `get_review` |
| `refactory/api/routes/review.py` | Detail response recomputes stats from suggestions |
| `ui/types/domain.ts` | Optional count fields on `PersistedReview` |
| `ui/lib/review-metrics.ts` | Shared count helpers |
| `ui/features/reviews/reviews-view.tsx` | History counts, risk cards, derived auto-select, loading, empties |
| `ui/components/data-display/risk-summary.tsx` | Hide unevaluated categories |
| `ui/components/reviews/file-explorer.tsx` | Empty state |
| `ui/components/reviews/suggestion-panel.tsx` | Empty copy |
| `ui/components/reviews/review-card.tsx` | Use `suggestion_count` |
| `ui/queries/repo-query-gate.ts` | Type cast so gated query satisfies `UseQueryResult` (build) |
| `tests/unit/test_review_suggestion_stats.py` | Stats unit tests |
| `tests/unit/test_query_service.py` | Expect additive count fields on review DTO |

## Validation results

| Check | Result |
|-------|--------|
| `pytest tests/unit/test_review_suggestion_stats.py` | Pass |
| `pytest tests/unit/test_query_service.py -k review` | Pass (14) |
| `pytest tests/unit/test_review_persistence.py` + `test_phase8_review.py` | Pass (41) |
| `npm run lint` (`ui/`) | Pass |
| `npm run build` (`ui/`) | Pass |

## Expected behavior

- History: `PR #1` → **Suggestions: 3** (from persisted stats)
- Detail metrics match History for the same review id
- Risk Assessment shows Overall only (no blank category cards)
- Opening a review selects the first changed file automatically

## Screenshots

Not captured in this environment. Manual check: open Reviews History → confirm Suggestions count → open same review → confirm matching metrics and first file selected.
