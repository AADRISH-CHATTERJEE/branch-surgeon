# Phase 11.5A — Repository Context Initialization & Query Gating

Frontend-only fix for the repository-root initialization race that omitted
`X-Repo-Root` on the first Local API requests.

## Root cause

1. `RepoProvider` initialized `repoRoot` to `null` (SSR-safe).
2. `localStorage` was read later in `useEffect`.
3. Repository React Query hooks ran immediately with `enabled` always true.
4. `apiRequest()` only sets `X-Repo-Root` when `repoRoot` is truthy
   (`ui/services/client.ts`).
5. First `GET /repository` / `GET /repository/health` requests had no header;
   the Local API fell back to `Path.cwd()` (`D:\refactory`) → 404 / wrong repo.
6. Settings Save called `repo.refetch()` in the same tick as `setRepoRoot()`,
   so refetch used a stale `repoRoot` closure.

## Before / after lifecycle

### Before

```
boot → repoRoot=null
     → useRepository() fetches (no X-Repo-Root) → 404 / cwd
     → useEffect hydrates localStorage → repoRoot=demo-repo
     → (maybe) second fetch with header
```

### After

```
boot → repoRoot=null, hydrated=false
     → repo queries enabled=false (isLoading treated as true → skeletons)
     → useEffect reads localStorage → repoRoot set, hydrated=true
     → first network request includes X-Repo-Root
```

Settings Save:

```
setRepoRoot(next)
invalidateQueries(["refactory","repo"])
→ React Query runs with the new query key + fresh opts
```

No manual `repo.refetch()` / `status.refetch()` after Save.

## Files modified

| File | Change |
|------|--------|
| `ui/providers/repo-context.tsx` | Expose `hydrated` after one-shot localStorage read |
| `ui/hooks/use-api-options.ts` | Pass `hydrated` with API options |
| `ui/queries/repo-query-gate.ts` | Helper: while `!hydrated`, force `isLoading`/`isPending` |
| `ui/queries/use-repository.ts` | Gate all repository hooks |
| `ui/queries/use-graph.ts` | Gate graph queries |
| `ui/queries/use-reviews.ts` | Gate reviews |
| `ui/queries/use-recommendations.ts` | Gate recommendations / patches |
| `ui/queries/use-rules.ts` | Gate rules list |
| `ui/queries/use-organization-rules.ts` | Gate org rules list |
| `ui/queries/use-activity.ts` | Gate activity |
| `ui/queries/use-history.ts` | Gate history |
| `ui/queries/use-documentation.ts` | Gate documentation |
| `ui/providers/org-context.tsx` | Gate org catalog queries until hydrated |
| `ui/hooks/use-nav-prefetch.ts` | Skip prefetch until hydrated |
| `ui/features/settings/settings-view.tsx` | Invalidate repo keys; sync drafts after hydrate |
| `ui/features/organization/*` | Gate ad-hoc org page queries |

**Unchanged (by design)**

- `ui/services/client.ts` — still sets `X-Repo-Root` when truthy
- `ui/queries/use-health.ts` — `GET /health` remains ungated (global)
- Backend / Local API — no changes

## Validation performed

- Static confirmation: every repo-scoped `useQuery` uses `enabled: opts.hydrated` (and optional extra conditions).
- `gateRepoQuery` keeps existing `isLoading && !data` skeletons during the hydrate wait (TanStack Query v5: disabled queries have `isLoading === false`).
- Settings Save invalidates `[...queryKeys.all, "repo"]` instead of stale `refetch()`.
- Lint/typecheck: run `npm run lint` / `npm run build` in `ui/` after pulling.

## Expected behavior

After restart with `refactory.repoRoot` set in localStorage:

1. Open app → Repository → first `GET /repository` **includes** `X-Repo-Root`.
2. Open Health → first `GET /repository/health` **includes** `X-Repo-Root`.
3. No repository-scoped request fires while `repoRoot` is still the pre-hydrate `null` from boot.
4. Repository / Health show loading skeletons until hydrate completes (no empty flash).
5. Saving Settings workspace updates root and reloads repo queries via invalidation with the new key.
