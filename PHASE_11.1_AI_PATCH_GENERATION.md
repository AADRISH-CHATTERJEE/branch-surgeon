# Phase 11.1 — AI Patch Generation

**Date:** 2026-07-31  
**Scope:** End-to-end AI patch generation for existing recommendations (Local API + UI).  
**Constraint:** No breaking changes to existing Recommendation or Transform APIs.

---

## Architecture

```
Persisted Recommendation (db_recommendations)
        │
        ▼
POST /recommendations/{id}/patch
        │
        ▼
RecommendationPatchService
  ├─ load recommendation (QueryService)
  ├─ enrich from latest recommend analysis snapshot (affected_files)
  ├─ read file contents from repo root (safe path resolve)
  ├─ PromptTemplateService ("recommendation_patch")
  ├─ AIGateway.generate → structured JSON (explanation, confidence, modified files)
  ├─ PatchGenerator.generate_from_content → unified_diff
  └─ PersistenceService.persist_recommendation_patch → db_patches
        │
        ▼
UI Recommendation Drawer
  Generate Patch → loading → PatchPreview (Monaco DiffViewer)
  Copy / Download / Apply(disabled)
```

**Reuse (no duplication):**

| Capability | Reused from |
|------------|-------------|
| LLM calls | `AIGateway` |
| Prompt registry | `PromptTemplateService` (`recommendation_patch`) |
| Unified diffs | `PatchGenerator` (`refactory/transformation/patch.py`) |
| Recommendation reads | `RepositoryQueryService` |
| Persistence / UoW | `PersistenceService` + `UnitOfWork` |
| Monaco display | `ui/components/diff-viewer.tsx` |

Patches are generated **only** for existing persisted recommendations. The service never invents recommendation rows.

---

## Endpoints

### `POST /recommendations/{recommendation_id}/patch`

Generates a new AI patch, persists it, and returns the payload.

**Success (`status: success`):**

```json
{
  "status": "success",
  "message": "Patch generated",
  "data": {
    "id": "<patch-uuid>",
    "recommendation_id": "<rec-uuid>",
    "explanation": "...",
    "confidence": 0.81,
    "changed_files": ["path/to/file.py"],
    "unified_diff": "--- a/...\n+++ b/...\n...",
    "patches": [
      {
        "file_path": "path/to/file.py",
        "original": "...",
        "modified": "..."
      }
    ],
    "prompt_version": "1.0.0",
    "model": "...",
    "provider": "...",
    "created_at": "ISO-8601",
    "apply_available": false
  },
  "meta": {
    "repo_root": "...",
    "apply_available": false,
    "patch_id": "<patch-uuid>"
  }
}
```

**Failure (`422`):** envelope `status: error`, message `Unable to generate patch`, with a concrete reason in `errors[]` (missing files, empty model output, invalid JSON, unknown recommendation, etc.). Never returns fabricated code.

### `GET /recommendations/{recommendation_id}/patches`

Lists previously persisted patches for reuse (newest first).

Existing endpoints unchanged:

- `POST /recommend`
- `GET /recommendations`
- Transform routes

---

## Patch schema

### ORM — `db_patches`

| Column | Purpose |
|--------|---------|
| `id` | Patch primary key |
| `recommendation_id` | FK → `db_recommendations` |
| `repository_id` | FK → `db_repositories` |
| `explanation` | Model explanation |
| `confidence` | 0.0–1.0 |
| `changed_files` | JSON list of paths |
| `unified_diff` | Full unified diff text |
| `patches` | JSON `[{file_path, original, modified}]` |
| `prompt_version` | Prompt template version |
| `model` / `provider` | AI metadata |
| `created_at` | Generation time |

Migration: `refactory/db/migrations/versions/2026_07_31_0003_add_patches.py` (`0003`).  
Dev/runtime also creates tables via `DatabaseManager.create_all()`.

### Pydantic — `RecommendationPatchResult`

`refactory/recommendation/patch_models.py`

---

## UI flow

1. Open Recommendation drawer.
2. Click **Generate Patch**.
3. While pending: skeleton in **Patch Preview**.
4. On success: Monaco DiffViewer shows `unified_diff`, plus explanation, confidence, changed files.
5. Actions:
   - **Copy Patch** — clipboard
   - **Download Patch** — `.patch` file
   - **Apply** — disabled (`apply_available: false`) with honest Unavailable note
6. On failure: **Unable to generate patch** + Retry (no fake code).
7. Prior patches reload via `GET .../patches` when the drawer opens.

---

## Backend changes

| Area | Files |
|------|--------|
| Service | `refactory/recommendation/patch_service.py` |
| Models | `refactory/recommendation/patch_models.py` |
| Routes | `refactory/api/routes/recommend.py` |
| ORM | `refactory/db/models.py` → `PatchModel` |
| Repo | `refactory/db/repositories/patch.py` |
| UoW / Persistence / Query | `uow.py`, `persistence.py`, `query_service.py` |
| DI | `refactory/core/container.py` → `recommendation_patch_service` |
| Prompt | `recommendation_patch` in `refactory/prompts/__init__.py` |
| Migration | `2026_07_31_0003_add_patches.py` |
| Tests | `tests/unit/test_phase_11_1_recommendation_patch.py`, phase9 route coverage |

**Target file resolution order:**

1. `affected_files` from latest `recommend` analysis snapshot (title match)
2. File-path mentions in title/description
3. Only files that exist under the validated repo root

---

## Frontend changes

| Area | Files |
|------|--------|
| Types | `ui/types/domain.ts` → `RecommendationPatch` |
| Endpoints / client | `ui/services/endpoints.ts`, `recommendations.ts` |
| Queries | `ui/queries/use-recommendations.ts` |
| Preview | `ui/components/recommendations/patch-preview.tsx` |
| Drawer | `ui/features/recommendations/recommendations-view.tsx` |

---

## Limitations

- Apply / write-back is **not** implemented (`apply_available: false`).
- Slim `GET /recommendations` rows still lack `affected_files`; patch generation recovers them from analysis snapshots or description paths when possible.
- LLM must return valid JSON with complete `modified` file content; non-JSON / empty patches fail gracefully.
- Multi-file patches are supported when the model returns multiple entries and all paths were provided as context (capped).
- Commit-after-apply is explicitly **future** work.

---

## Future Apply Patch API

Suggested follow-on (Phase 11.x):

```
POST /recommendations/{id}/patches/{patch_id}/apply
```

Behavior:

1. Load persisted patch (`original` / `modified` or `unified_diff`)
2. Verify working-tree content still matches `original` (conflict detection)
3. Write `modified` (or `git apply` unified diff)
4. Optionally stage / commit (future)
5. Mark recommendation status / link applied patch id

Until then, UI keeps Apply disabled and points users to Transform for deterministic writes when applicable.

---

## Validation

```text
npm run lint   → pass (0 errors, 0 warnings)
npm run build  → pass
pytest tests/unit/test_phase_11_1_recommendation_patch.py
               tests/unit/test_phase9_local_api.py
               (+ related persistence/query tests) → pass
```

Full `tests/unit` run: **2346 passed**; 53 pre-existing setup errors for CLI tests missing the `mocker` fixture (`pytest-mock` not installed in this environment) — unrelated to Phase 11.1.

---

## Production readiness notes

- Existing Recommendation list/generate flows unchanged.
- No fake patches on failure.
- Patches are durable and listable for reuse.
- Demo path: configure repo root → Generate Recommendations → open a recommendation that mentions a real file → Generate Patch → preview/copy/download.
