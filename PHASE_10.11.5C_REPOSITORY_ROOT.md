# Phase 10.11.5C — Repository Root Resolution

**Date**: July 31, 2026  
**Status**: Complete (Local API only — no UI changes)

---

## 1. Problem

`resolve_repo_root()` fell back to `Path.cwd()` when `X-Repo-Root` was absent. Starting uvicorn from `D:\refactory` caused the API to analyze the monorepo instead of the UI-selected demo repository, producing HEAD errors and long `/repository/status` walks.

## 2. Resolution flow (after)

```
1. X-Repo-Root header          ← UI Settings / client
2. ?root= query parameter
3. REFACTORY_REPO_ROOT         ← Settings / env (optional)
4. Path.cwd()                  ← last resort only
        ↓
validate_repository_root()
  - path exists and is a directory
  - path/.git exists (must be the repo root; no parent walk)
  - Git HEAD resolves to a commit
        ↓
build_container(repo_root=validated)  (cached per root)
```

Invalid roots raise `RepositoryNotFound` → HTTP 404 structured `ApiResponse` (no silent continue).

## 3. Files modified

| File | Change |
|------|--------|
| `refactory/api/repo_root.py` | **New** — choose + validate helpers |
| `refactory/api/deps.py` | Priority resolution + validate before container build |
| `refactory/core/config.py` | `REFACTORY_REPO_ROOT` / `repository_root` setting |
| `refactory/api/routes/repository.py` | Debug timing retained (status path) |
| `tests/unit/test_phase_10_11_5c_repo_root.py` | **New** unit tests |
| `PHASE_10.11.5C_REPOSITORY_ROOT.md` | This deliverable |

No UI / React / Graph / Surgeon / indexer algorithm changes.

## 4. Before vs after

| Scenario | Before | After |
|----------|--------|-------|
| UI sends `X-Repo-Root: …\demo-repo` | Correct repo | Correct repo (unchanged) |
| No header, API cwd = `D:\refactory` | Analyzes monorepo; `/status` hangs | **404** clear error unless `REFACTORY_REPO_ROOT` set |
| `REFACTORY_REPO_ROOT` set, no header | N/A | Uses configured demo root |
| Nested folder without `.git` | Could attach via parent search in GitService | Rejected at validation (must be repo root) |

## 5. Endpoint consistency

All Local API routes that use `ContainerDep` share `get_container` → same validated root:

`/repository`, `/repository/status`, `/repository/health`, `/reviews`, `/recommendations`, `/graph/*`, `/rules`, `/activity`, `/documentation`, …

## 6. Validation performed

- Unit tests: `tests/unit/test_phase_10_11_5c_repo_root.py` + `test_phase9_local_api.py` → **38 passed**
- `npm run lint` (UI unchanged) → pass
- Live probe (uvicorn on `:8742`, process cwd = `D:\refactory`):

| Request | Header | Result | Time |
|---------|--------|--------|------|
| `GET /repository` | `X-Repo-Root=…\demo-repo` | **200** `demo-repo` | ~540ms (cold container) |
| `GET /repository/status` | same | **200** same root | ~203ms |
| `GET /repository/health` | same | **200** same root | ~581ms |
| `GET /repository` | none | **404** (reject cwd) | ~12ms |
| `GET /repository/status` | none | **404** (no hang) | ~6ms |

Before 5C, no-header `/status` **timed out** walking `D:\refactory`.

## 7. Optional server default

```bash
set REFACTORY_REPO_ROOT=C:\Users\ADMIN\Documents\demo-repo
```

Useful when calling Swagger without headers. UI should continue sending `X-Repo-Root`.

## 8. Deferred to 10.11.5D

`assess_staleness()` `rglob` cost on large trees — measure Dashboard/Repo/Health/Surgeon after 5C before optimizing.
