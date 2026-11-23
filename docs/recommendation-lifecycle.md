# Recommendation & Review Suggestion Lifecycle

## States

| Status | Meaning |
|--------|---------|
| **pending** | Open work — not addressed yet. |
| **applied** | AI patch applied; awaiting verification. |
| **resolved** | Verified fixed. |
| **ignored** | Intentionally dismissed. |

## State machine

```
pending
  ├─→ applied  (AI patch applied)
  │     └─→ resolved  (verified fixed, or auto after issue gone)
  ├─→ resolved  (manual Mark Resolved / review suggestion resolve)
  └─→ ignored
```

`rolled_back` counts with **pending** (open again).

## Persisted recommendation fields

`reasoning`, `affected_files`, `impact`, `effort` (XS–XL), `confidence`,
`resolution_notes`, `verification_status`, lifecycle timestamps, `updated_by`.

Patch history lives in `db_patches` (shown as Patch v1…vn in the UI).

## Severity tiles (Critical / High / Medium / Low)

Count **pending-only** recommendations (plus `rolled_back`).

Resolved, applied, and ignored rows do **not** contribute to severity tiles.

## Lifecycle tiles

Pending / Applied / Resolved / Ignored are status totals across the repository.

## APIs

- `PATCH /recommendations/{id}` — status / notes / priority; refreshes stats + Branch Surgeon; Activity + History
- `PATCH /reviews/{review_id}/suggestions/{suggestion_id}` — suggestion lifecycle + recommendation sync
