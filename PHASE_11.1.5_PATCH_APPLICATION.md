# Phase 11.1.5 — Patch Application (One-Click Code Change)

**Date:** 2026-07-31  
**Scope:** Safely apply stored AI patches to the local repository working tree (Local API + UI).  
**Constraint:** Extends Phase 11.1 without breaking existing Recommendation, Patch Generation, or Transform APIs. No auto-commit, stage, push, or PR.

---

## Workflow

```
Generate Patch (Phase 11.1)
        │
        ▼
Preview (unified diff + Monaco)
        │
        ▼
POST /patches/{patch_id}/apply
        │
        ├─ load stored patch
        ├─ locate repository root
        ├─ verify current file == stored original (conflict → 409)
        ├─ write modified content into repo root
        ├─ parser / syntax validation
        │     └─ on failure → rollback writes → 422
        ├─ refresh repository index
        └─ refresh graph (best-effort)
        │
        ▼
UI success actions
  Open File · Run Review Again · Generate New Recommendation
```

---

## Endpoint

### `POST /patches/{patch_id}/apply`

Chosen over `POST /recommendations/{id}/apply` because patches are first-class persisted entities with their own ids; recommendations may have multiple stored patches.

**Success (`status: success`):**

```json
{
  "status": "success",
  "message": "Applied patch to 1 file(s).",
  "data": {
    "status": "applied",
    "applied": true,
    "patch_id": "<uuid>",
    "recommendation_id": "<uuid>",
    "changed_files": ["path/to/file.py"],
    "validation": {
      "ok": true,
      "checked_files": ["path/to/file.py"],
      "errors": [],
      "rolled_back": false
    },
    "repository_updated": true,
    "index_updated": true,
    "graph_updated": true,
    "message": "Applied patch to 1 file(s)."
  },
  "meta": {
    "repo_root": "...",
    "index_updated": true,
    "graph_updated": true
  }
}
```

**Conflict (`409`):** working-tree content no longer matches the stored `original` baseline.

**Validation / IO failure (`422` / `403` / `404`):** actionable `errors[]`; on validation failure files are rolled back before the response.

Existing endpoints unchanged:

- `POST /recommendations/{id}/patch`
- `GET /recommendations/{id}/patches`
- `POST /recommend`, Transform, Review routes

Generate/list responses now advertise `apply_available: true`.

---

## Patch lifecycle

| Stage | State |
|-------|--------|
| Generated | Persisted in `db_patches` with `original` / `modified` per file + unified diff |
| Previewed | UI loads latest stored patch or freshly generated payload |
| Applied | Working tree written; index/graph refreshed; not staged/committed |
| Stale | Disk ≠ stored original → apply refused (409); user must Generate Patch again |
| Invalid apply | Parser/syntax fail → rollback to originals; patch row retained |

---

## Conflict handling

Before any write:

1. Resolve each `file_path` under the configured repository root (path traversal rejected).
2. Require the file to exist and be readable.
3. Compare normalized current content to stored `original` (newline-normalized equality — hash-equivalent check).
4. On mismatch → `PatchConflictError` → HTTP **409** with conflicting file paths in `meta.files`.

Newer local edits are never overwritten.

---

## Rollback strategy

1. Capture originals while writing.
2. After all writes, run `ParserService` for supported extensions (`has_syntax_errors` / parse exceptions).
3. If validation fails:
   - restore every written file from captured originals
   - set `validation.rolled_back = true`
   - return failure without reindexing
4. Permission / OS write errors also trigger rollback of any partial writes.

Unsupported languages skip parser checks but still participate in conflict detection and write/rollback.

---

## UI

**Recommendation Drawer → Patch Preview**

- **Apply Patch** (enabled when `apply_available` and patch id present)
- Confirmation dialog (explicit write warning; no git commit)
- Applying… state
- Success panel:
  - **Open File** → `/repository?file=…`
  - **Run Review Again** → existing `RunReviewDialog` / `POST /review`
  - **Generate New Recommendation** → existing `POST /recommend`

**React Query invalidation** after success: repository-scoped caches (recommendations, repository, graph, reviews, activity) and health.

Failure toasts cover conflict (409), permission (403), missing API (404), and validation messages.

---

## Known limitations

- Conflict detection uses stored original content equality, not git blob SHAs.
- Graph refresh is best-effort; index failure is logged and does not undo a successful write.
- Multi-file patches are all-or-nothing for validation rollback, but not transactional across OS crashes mid-write.
- Apply does not update git index, create commits, or open PRs.
- Languages outside `ParserService.supported_extensions()` are not syntax-validated.

---

## Future — Git Commit phase

Out of scope for 11.1.5; planned separately:

- Optional stage + commit after successful apply
- Commit message from patch explanation
- Push / PR creation
- Branch policies and review gates

---

## Validation

- `npm run lint` / `npm run build` (UI)
- `pytest` including:
  - patch applies successfully
  - patch conflict
  - validation rollback
  - repository refresh (indexer + graph)
