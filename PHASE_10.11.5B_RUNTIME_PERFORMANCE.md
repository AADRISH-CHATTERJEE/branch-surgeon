# Phase 10.11.5B — Runtime Performance & UX Smoothness

**Date**: July 31, 2026  
**Status**: Complete (UI only — no Local API / route / React Query architecture / feature / redesign changes)

---

## 1. Optimizations applied

| # | Area | Change |
|---|------|--------|
| 1 | Markdown highlighting | Removed static `rehype-highlight` + `highlight.js` CSS imports; dynamic `import()` only when fenced code blocks exist |
| 2 | Doc processing | Search corpus built only when search panel is open; `MarkdownViewer` supports `active` to skip hidden parse |
| 3 | Hover prefetch | Sidebar hover/focus prefetches Graph Full, Reviews, Recommendations, Repository (+ status), Activity — once per repo+href |
| 4 | Render hygiene | Stable `useApiOptions()` identity; memo’d Dashboard feeds/actions; memo’d Graph nodes; Surgeon decision strip extracted + memo’d |
| 5 | View splits | Dashboard feeds + quick actions; Surgeon decision strip; Settings `SectionCard` / `ReadOnlyValue` extracted |
| 6 | Query waterfalls | Activity defers `useGraphSummary` until activity query settles; Graph summary still after full (from 5A) |
| 7 | Loading UX | Replaced remaining “Loading…” with skeletons; Dashboard list sections skeleton while streaming |
| 8 | React Flow | `React.memo` nodes; stable `nodeTypes` / `edgeTypes`; fitView only on structure key; animated edges + durations honor Animations pref |
| 9 | Animations OFF | `PreferMotionDiv` renders plain `div` and **does not load** `framer-motion` until animations are ON (dynamic import) |
| 10 | Keyboard | Cmd/Ctrl+K remains a single shell listener; page shortcuts stay mount-scoped (Graph / Docs / Repo) |
| 11 | Bundle inspection | Production chunk inventory after `next build` (Turbopack) — see §6 |
| 12 | Measurement | Before/after comparison documented in §7 |

---

## 2. Profiler / static findings

Interactive React Profiler screenshots were not captured in this agent session (no browser DevTools run). Findings from static review + build artifacts:

| Finding | Evidence | Action |
|---------|----------|--------|
| Dashboard Framer Motion always in graph | Static `import { motion }` | Switched to gated dynamic import |
| highlight.js on non-docs routes via shared MarkdownViewer | Static CSS + rehype import | Lazy only on fenced code |
| Doc search parsed all Markdown on mount | `searchableDocs` useMemo on `data` | Gated on `searchOpen` |
| Graph fitView on selection restyles | deps included node array churn | Structure key only |
| Nav hover cold starts | No prefetch | `useNavPrefetch` |
| Oversized Dashboard / Surgeon JSX trees | 500–600 LOC views | Extracted memo’d sections |

---

## 3. Render reductions (estimated)

| Surface | Change |
|---------|--------|
| Dashboard | Feeds/actions isolated behind `React.memo`; fewer parent re-renders when only health/metrics update |
| Graph | Memoized node component; fewer fitView calls; no CSS `transition-all` on every node |
| Surgeon | Decision strip memo’d; graph still deferred one frame (5A) |
| Documentation | No full-catalog string parse until search opens |
| Global | Stable API options object → fewer query observer identity churns |

Exact React commit counts require browser Profiler; not claimed as measured here.

---

## 4. Bundle reductions (measured from `next build`)

Largest JS chunks after Phase 10.11.5B production build:

| Size | Chunk (hash) | Identified content |
|------|----------------|--------------------|
| ~228 KB | `2rl9r9j5fq8mv.js` | React Flow (`ReactFlow`) — Graph route |
| ~170 KB | `26kwwoqp1u19q.js` | `highlight.js` — **async**, only when markdown has fences |
| ~153 KB | `2t0yffpor5mqn.js` | `react-markdown` — docs/reviews/surgeon consumers |
| ~222 / ~117 KB | other large chunks | Shared vendor / framework (Turbopack hashed) |

**Key wins vs 10.11.5A intent**

- Dashboard users do **not** pull `highlight.js` until a page with fenced markdown renders and lazy-loads it.
- `framer-motion` loads only when Animations preference is ON and `PreferMotionDiv` mounts the dynamic module.
- React Flow remains isolated to Graph (and its dynamic route chunk) — ~228 KB not on Dashboard critical path.

---

## 5. Query improvements

| Improvement | Detail |
|-------------|--------|
| Hover prefetch | Graph Full, reviews list, recommendations list, repository + status, activity list |
| Once-only guard | Module `Set` keyed by `repoRoot:href` — no spam |
| Activity summary | Enabled after activity fetch settles — reduces parallel expensive `/graph` rebuild contention |
| Stable options | `useApiOptions` memoized by `apiBaseUrl` / `repoRoot` |

React Query architecture (keys, hooks, ServiceContainer) unchanged.

---

## 6. Bundle inspection notes

Method: `npm run build` then size-sort `.next/static/chunks` and content-scan for library markers.

**Largest route-associated dependencies**

1. `@xyflow/react` (~228 KB chunk) — Repository Graph  
2. `highlight.js` (~170 KB) — lazy markdown highlighting  
3. `react-markdown` (~153 KB) — documentation / review / surgeon markdown  

**Not optimized blindly**

- Did not add `@next/bundle-analyzer` dependency (Turbopack build; hashed chunks sufficient for this phase).  
- Did not code-split `react-markdown` further (needed as soon as MarkdownViewer mounts).  
- Did not fully file-split Settings (~1k LOC) into 8 section modules — high churn / regression risk for layout-only gain; extracted shared `SectionCard` instead. Deferred full Settings section files.

---

## 7. Before vs after (flagship pages)

| Page | Network (cold, typical) | Bundle impact | Perceived loading |
|------|-------------------------|---------------|-------------------|
| **Dashboard** | Same core fan-out as 5A (no Graph Full); **no** highlight.js; Framer only if animations ON | Smaller critical path | Chrome + skeletons; feeds skeleton while lists load |
| **Repository** | Unchanged payload; hover can warm metadata | Unchanged | Virtualized (5A) + keyboard |
| **Graph** | Hover can prefetch `/graph/full` once | React Flow chunk on navigate | Header kept; fitView less chatty; animations respect pref |
| **Surgeon** | Graph still deferred after paint | Markdown highlight only if fenced summary | Decision strip isolated |

Lighthouse: not run in this environment (no headed browser CI). Recommend local Lighthouse on Dashboard / Graph after merge.

---

## 8. Remaining bottlenecks

| Bottleneck | Layer |
|------------|--------|
| `GET /repository/health` cost | Backend |
| `GET /repository/files?limit=5000` payload | Backend + network |
| `GET /graph/full` size | Backend |
| `GET /graph` rebuild cost | Backend |
| Settings / Rules / Graph view still large source files | FE maintainability |
| Monaco / transform editor (when used) | Route bundle |

---

## 9. Recommended future backend optimizations

1. Paginate or cursor `GET /repository/files` (e.g. 200–500) with search server-side.  
2. Cache / cheap-path `GET /repository/health` for unchanged HEAD.  
3. Persist graph summary so `GET /graph` never rebuilds on read.  
4. Compress or delta `GET /graph/full`.  
5. Split documentation endpoint into per-doc fetches.

---

## 10. Intentionally not done

| Idea | Why |
|------|-----|
| Wrap every component in `React.memo` | Spec: only where benefit is clear |
| Redux / Zustand | Forbidden |
| Fake optimistic metrics | Forbidden |
| Full Settings 8-file section split | Risk > gain this phase; helpers extracted |
| Lighthouse CI gate | Environment lacked headed run |

---

## 11. Validation

```
npm run lint   → pass (0 errors / 0 warnings)
npm run build  → pass (TypeScript clean; all routes generated)
```

---

## Key files

- `ui/components/markdown-viewer.tsx`
- `ui/components/motion/prefer-motion.tsx`, `motion-div.tsx`
- `ui/hooks/use-nav-prefetch.ts`, `use-api-options.ts`
- `ui/components/layout/sidebar.tsx`
- `ui/features/dashboard/dashboard-view.tsx`, `components/dashboard-*.tsx`
- `ui/features/surgeon/components/decision-strip.tsx`
- `ui/features/graph/graph-view.tsx`, `components/graph-node.tsx`
- `ui/features/documentation/documentation-view.tsx`
- `ui/features/activity/activity-view.tsx`
- `ui/features/settings/components/section-card.tsx`
