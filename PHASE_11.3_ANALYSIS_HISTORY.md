# Phase 11.3 — Analysis History & Timeline

**Date:** 2026-07-31  
**Scope:** Local API + UI — first-class searchable memory of analysis results.  
**Complements:** Activity (`db_analysis_runs`) answers “what happened?”; History answers “what were the results?”

---

## Goal

Persist every completed analysis automatically so users never lose Reviews, Recommendations, Branch Surgeon analyses, Health/Graph snapshots, Patch generate/apply, Rules evaluations, Transform, or Index runs.

---

## Database schema

Table: `analysis_history`

| Column | Type | Notes |
|--------|------|--------|
| `id` | string(36) PK | UUID hex |
| `timestamp` | datetime (tz) | When the analysis finished |
| `analysis_type` | string(50) | Canonical type (see below) |
| `repository_id` | FK → `db_repositories.id` | Cascade delete |
| `repository_name` | string | Denormalized for search/export |
| `branch` | string? | Git branch |
| `commit` | string? | Head SHA (short/full) |
| `status` | string | e.g. completed / failed / pass / warn / block |
| `duration_ms` | float | Wall time |
| `summary` | text | Human-readable one-liner |
| `created_by` | string | Default `local` |
| `metadata` | JSON | Extra inputs / context |
| `result_data` | JSON | Outputs for drawer / export |
| `analysis_run_id` | string? | Optional link to Activity run |

Indexes: `(repository_id, timestamp)`, `analysis_type`, `status`, `branch`.

Migration: `refactory/db/migrations/versions/2026_07_31_0005_analysis_history.py` (revises `0004`).

ORM: `AnalysisHistoryModel` in `refactory/db/models.py`.  
Repository: `refactory/db/repositories/analysis_history.py` on `UnitOfWork.analysis_history`.

---

## Supported analysis types

| Type | Sources |
|------|---------|
| `review` | Review engine / persist_analysis_run |
| `recommendation` | Recommend / persist_analysis_run |
| `repository_health` | GET health route |
| `repository_graph` | Graph build/load |
| `branch_surgeon` | CLI `refactory surgeon` (UI Local Surgeon API still composed) |
| `rules_evaluation` | Rules check / company + org rules |
| `patch_generation` | Patch generate |
| `patch_apply` | Patch apply |
| `transform` | Transform apply / rollback |
| `index` | Index / embed |

Mapping: `refactory/history/types.py` (`COMMAND_TO_ANALYSIS_TYPE`, `RESULT_TYPE_TO_ANALYSIS_TYPE`).

---

## Persistence flow

```
Analysis finishes
  ├─ persist_analysis_run (Activity) ──► AnalysisHistoryService.record_from_analysis_run
  └─ or record_history(...)           ──► AnalysisHistoryService.record
                                              └─ analysis_history row
```

- **Automatic** — no manual save.
- Wired in `ServiceContainer`: `persistence_service.set_history_service(analysis_history_service)`.
- Direct hooks: index, graph, health, patch generate/apply, CLI surgeon.
- Failures to write history are logged and **do not** fail the primary analysis.

Helpers: `refactory/history/helpers.py` (`record_history`, `timed`, `git_context`).

---

## History lifecycle

1. **Create** — on analysis completion (API, CLI, or Activity mirror).
2. **Explore** — `GET /history` (filters) + History page timeline (newest first).
3. **Inspect** — `GET /history/{id}` + DetailDrawer (metadata, result_data, deep links).
4. **Export** — `GET /history/export?format=json|markdown|csv`.
5. **Retain / purge** — `POST /history/retention` with `{ "days": null|0|30|90|365 }`.
6. **Compare** — UI selection of two items; Compare button disabled until backend lands.

---

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/history` | List (type, status, branch, search, since, until, limit, offset) |
| GET | `/history/metrics` | Total, today, week, avg duration, failures, success rate |
| GET | `/history/export` | Download JSON / Markdown / CSV |
| POST | `/history/retention` | Apply retention for current repository |
| GET | `/history/{id}` | Single entry |

All scoped via configured repository (`X-Repo-Root` / resolve helpers).

---

## UI

| Surface | Location |
|---------|----------|
| Sidebar | Dashboard → **History** |
| Page | `/history` — PageHeader, MetricStrip, filters, timeline, DetailDrawer |
| Dashboard | Recent Analyses (latest 5, clickable) |
| Settings | **Data & History** — retention Unlimited / 30 / 90 / 365 + Apply |
| Command palette | Open History |

Deep links (Open Review / Recommendation / Surgeon / Graph / …) from `history-meta.ts` and server `_deep_link`.

Reuse: MetricStrip, DetailDrawer, SearchInput, FilterBar patterns (same family as Activity — not a forked timeline stack).

---

## Retention

| Policy | Behavior |
|--------|----------|
| Unlimited (`0` / `null`) | No deletions |
| 30 / 90 / 365 days | Delete rows with `timestamp` older than cutoff for the current repository |

Client preference: `UiPreferences.historyRetentionDays`. Applying retention calls the Local API; preference alone does not purge until Apply.

---

## Future comparison support

- UI already allows selecting up to two timeline items.
- **Compare** remains disabled with a placeholder until a backend endpoint can diff two `result_data` payloads (same `analysis_type` preferred).
- Suggested future: `POST /history/compare` `{ "left_id", "right_id" }` → structured delta + optional UI side-by-side drawer.

---

## Validation

- `npm run lint` / `npm run build` (UI)
- `pytest` including `tests/unit/test_phase_11_3_analysis_history.py`
- Existing Activity and analysis endpoints unchanged in contract
