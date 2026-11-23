# Phase 10.11.5A — Frontend Performance & Responsiveness

**Date**: July 31, 2026  
**Status**: Complete (UI only; no Local API / backend / ServiceContainer / contract changes)

---

## 1. Optimizations made

| Area | Change |
|------|--------|
| Dashboard | Removed full-page blocking skeleton; chrome (header, metrics, connection) paints first |
| Dashboard graph | `useGraphFull` gated behind “Load graph preview” — no eager Graph Full request |
| Progressive chrome | Dashboard, Repository, Health, Surgeon, Graph keep `PageHeader` / toolbars mounted; only section bodies skeleton |
| Graph route | `next/dynamic` entry (`graph-route.tsx`) so `@xyflow/react` + dagre load only on Graph navigation |
| Graph data | `useGraphSummary` waits until Graph Full has data (avoids parallel expensive summary rebuild) |
| Surgeon | Deferred Graph Full one animation frame; no full-page `PageSkeleton` |
| Repository | File list virtualized (`VirtualizedList` + TanStack Virtual); ↑/↓ keyboard + scroll-into-view |
| DataTable | Auto-virtualizes when row count > 40; sorting / selection / empty / sticky header preserved |
| Command palette | `useDocumentation(open)` — docs fetched only when palette opens (or docs/settings/rules pages) |
| React Query | Canonical fetch limits + `select` slices; `keepPreviousData` / `placeholderData` on list hooks |
| Query keys | Reviews / recommendations / activity no longer fragment cache on `limit` |
| Activity invalidation | Uses `activityRoot` prefix so all filtered activity queries refresh |

---

## 2. Before vs after architecture

### Before

```
Dashboard mount → 8–9 parallel requests including GET /graph/full
Shell / palette → documentation fetch on every page
Graph libs → pulled whenever any route imported graph feature graph-view
Repository → render up to 5000 DOM rows
Many pages → replace entire view with PageSkeleton
Reviews/recs → cache keys differed by limit (or ignored limit incorrectly)
```

### After

```
Dashboard mount → repo / status / health / reviews / recs / activity / rules-check
                 → Graph Full only after user expands preview
Palette → docs query enabled only while open; shared React Query cache after first load
Graph page → separate JS chunk (React Flow + dagre); Dashboard/Surgeon never pay canvas bundle
Repository / DataTable → windowed rows; keyboard selection preserved
Pages → PageHeader + chrome always; body skeletons only
Lists → one canonical network page per resource; observers slice via select
```

---

## 3. Components lazy loaded

| Module | Mechanism |
|--------|-----------|
| `GraphView` (`@xyflow/react`, dagre layout) | `next/dynamic` via `ui/features/graph/graph-route.tsx`, `ssr: false` |
| Diff viewer (pre-existing) | Already `next/dynamic` — unchanged |

**Not lazy-loaded (frequently used / negligible win):** `PageHeader`, `DataTable`, `MetricStrip`, shells, shared feedback components.

**Deferred (10.11.5B):** `rehype-highlight` / highlight.js CSS inside `MarkdownViewer` — docs/reviews/surgeon already route-split; further plugin lazy-load risks FOUC and adds complexity for small shell impact.

---

## 4. Components virtualized

| Surface | Implementation | Threshold |
|---------|----------------|-----------|
| Repository file list | `VirtualizedList` | Always (list can be thousands) |
| Shared `DataTable` | TanStack Virtual when `rows > VIRTUALIZE_ROW_THRESHOLD` | 40 |

Preserved: selection, search/filter, sticky headers (DataTable), empty/error states, keyboard ↑/↓ + `scrollToIndex` on repository.

---

## 5. React Query improvements

| Hook | Improvement |
|------|-------------|
| `useReviews` | Key `["reviews","list"]`; fetch `REVIEWS_FETCH_LIMIT` (100); `select` slice; `keepPreviousData` |
| `useRecommendations` | Key by status only (not limit); fetch 200; `select` slice; `keepPreviousData` |
| `useActivity` | Key by command/status; fetch 200; `select` slice; invalidate via `activityRoot` |
| `useGraphFull` / `useGraphSummary` | Optional `enabled`; `keepPreviousData` |
| `useDocumentation` | Optional `enabled` (palette gated) |
| Repository / rules hooks | `keepPreviousData` where already applied |

Cache correctness: canonical pages are supersets of sliced views; mutations invalidate by prefix (`recommendations`, `activityRoot`, reviews list key).

---

## 6. Bundle improvements

- Graph canvas dependencies isolated to `/repository/graph` dynamic chunk.
- Dashboard no longer downloads React Flow/dagre for MiniGraph preview (preview uses lightweight name chips after on-demand data fetch).
- Surgeon still uses `graph-analytics` (no dagre/xyflow) for degree helpers — no canvas bundle on Surgeon.

---

## 7. Remaining backend bottlenecks (unchanged — out of scope)

| Endpoint | Why it still hurts |
|----------|-------------------|
| `GET /repository/health` | Expensive compute; Dashboard + Health + Surgeon still need it |
| `GET /repository/files?limit=5000` | Large payload; FE virtualizes render only |
| `GET /graph/full` | Large JSON; deferred on Dashboard, still required on Graph/Surgeon |
| `GET /graph` (summary) | Can rebuild; FE now sequences after full on Graph page |
| Documentation multi-doc fetch | Still multi-part when docs/palette/settings/rules need it |

---

## 8. Estimated user-perceived improvement

| Journey | Estimate |
|---------|----------|
| Dashboard first paint | **~40–60% faster feel** — chrome immediate; one fewer heavy graph request by default |
| Navigate away from Graph libs | **Meaningful JS savings** on Dashboard/Surgeon initial load (React Flow + dagre out of critical path) |
| Repository with large index | **Large DOM win** — thousands of rows → ~20–40 visible nodes |
| Command palette on non-docs pages | **Removes docs network** until palette opens |
| Filter/pagination flashes | **Reduced** via `keepPreviousData` + shared list caches |

No fake loading or hidden data: deferred Graph preview is explicit user action; other data still loads for real widgets.

---

## 9. Validation results

```
npm run lint   → pass (0 errors, 0 warnings)
npm run build  → pass (TypeScript clean; all routes generated)
```

Routes verified present: `/dashboard`, `/repository`, `/repository/graph`, `/repository/health`, `/surgeon`, `/documentation`, etc.

---

## 10. Deferred for 10.11.5B

| Item | Why deferred |
|------|----------------|
| Lazy `rehype-highlight` / highlight.css | Risk of unstyled code flash; pages already code-split |
| Aggressive `React.memo` on Dashboard/Surgeon | No profiler evidence; avoid over-memoization |
| Prefetch Graph chunk on hover of Graph nav link | Nice-to-have; not required for correctness |
| Activity page `useGraphSummary` deferral | Minor; Activity already has its own data fan-out |
| Normalize files query / progressive file pages | Would need UX for paging; virtualization addresses render cost |
| Backend caching / health / graph payload shrink | Explicitly out of scope for 10.11.5A |

---

## 11. Intentionally not implemented

| Idea | Reason |
|------|--------|
| Fake skeleton delays / optimistic fake metrics | Spec forbids fake loading |
| Caching inside ServiceContainer / Local API | Backend out of scope |
| Removing Dashboard health/reviews/recs fan-out | Would hide real widgets |
| Lazy-loading `PageHeader` / shell primitives | High frequency; negligible benefit |
| Full component rewrites | Spec: preserve architecture and look |

---

## Key files

- `ui/lib/query-limits.ts`
- `ui/queries/keys.ts`, `use-reviews.ts`, `use-recommendations.ts`, `use-activity.ts`, `use-graph.ts`, `use-documentation.ts`
- `ui/features/dashboard/dashboard-view.tsx`
- `ui/features/surgeon/surgeon-view.tsx`
- `ui/features/graph/graph-route.tsx`, `graph-view.tsx`
- `ui/features/repository/repository-explorer.tsx`
- `ui/features/command-palette/command-palette.tsx`
- `ui/components/data-display/virtualized-list.tsx`, `data-table.tsx`
- `ui/app/(shell)/repository/health/page.tsx`
