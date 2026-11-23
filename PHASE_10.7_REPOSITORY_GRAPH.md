# Phase 10.7 — Repository Graph Deliverables

**Date**: July 31, 2026  
**Status**: Complete (UI only; no backend changes)

---

## 1. Audit Report

### Existing endpoints (reused)

| Endpoint | Role |
|----------|------|
| `GET /graph/full` | Persisted nodes + edges (`RepositoryQueryService.get_graph`) |
| `GET /graph/nodes/{id}` | Node + incoming/outgoing edges |
| `GET /graph` | Summary + engine `GraphStatistics` |
| `POST /graph` | Build/rebuild via `RepositoryGraphService` |

### Returned node fields (`GET /graph/full`)

`id`, `repository_id`, `name`, `type`

Persisted `type` values from engine kinds: `file`, `module`, `package`, `class`, `function`, `method`, `nested_function`.

### Returned edge fields

`id`, `source_node`, `target_node`, `relationship`

Relationships include imports, calls, inherits, contains, references (and related definition edges).

### Missing metadata (backend / persistence)

- `file_path`, symbol counts, line ranges (exist on engine models, **not** persisted)
- Distinct “repository” / “external dependency” node kinds in API rows
- Hotspot / LCC / ranking endpoints (engine has helpers; not on Local REST)
- Graph mutation APIs (intentionally out of scope)

### Prior UI limitations

- Grid-only layout, untyped nodes/edges, no legend
- Search filtered list only (no center/highlight)
- No neighborhood mode, type filters, path highlight, or metrics sidebar
- Cap at 400 nodes without hop focusing

---

## 2. Backend APIs Reused

- `GET /graph/full` — primary canvas data
- `GET /graph/nodes/{id}` — inspector
- `GET /graph` — optional richer counts
- `POST /graph` — rebuild

No new endpoints. No changes to ReviewEngine, GraphBuilder, QueryService, or RepositoryGraphService.

---

## 3. Components Added

| Path | Purpose |
|------|---------|
| `ui/features/graph/lib/graph-styles.ts` | Node/edge colors, legend, filter groups |
| `ui/features/graph/lib/graph-analytics.ts` | Stats, hops, degree, search (client-side) |
| `ui/features/graph/lib/graph-layout.ts` | Dagre TB/LR, force, grid |
| `ui/features/graph/components/graph-node.tsx` | Typed React Flow node |
| `ui/features/graph/components/graph-legend.tsx` | Node + edge legend |
| `ui/features/graph/components/graph-stats-bar.tsx` | Summary metric cards |
| `ui/features/graph/components/node-inspector.tsx` | Right inspector panel |
| `ui/features/graph/components/metrics-sidebar.tsx` | Degree / import rankings |

Dependency: `@dagrejs/dagre` (+ `@types/dagre`)

---

## 4. Components / files Modified

| Path | Change |
|------|--------|
| `ui/features/graph/graph-view.tsx` | Full workspace (filters, layout, hops, highlight, search) |
| `ui/queries/use-graph.ts` | Invalidate full/summary/activity after build |
| `ui/components/search-input.tsx` | Optional `id` for keyboard focus |

Reused: React Flow, PageHeader, MetricCard, StatusBadge, Empty/Error/Skeleton, SearchInput, Select, Button, Kbd, React Query hooks.

---

## 5. Build Status

```
npm run lint   → exit 0 (warnings only if any; clean after memo fix)
npm run build  → exit 0 (19 routes)
```

---

## 6. Screenshots Summary

Not captured in this session. Expected UI:

1. Stats strip: Nodes / Edges / Files / Classes / Functions / Dependencies / Largest component  
2. Canvas: typed colored nodes, styled edges, minimap, controls, grid, bottom-left legend  
3. Toolbar: search chips, layout select, neighborhood, type filter toggles  
4. Right rail: Inspector (edges/imports) or Metrics (most connected / imported)

---

## 7. Remaining Backend Gaps

1. Persist / expose `file_path` (and optional symbol_count) on graph nodes  
2. Optional external-dependency node typing if product wants it  
3. Thin wrappers for engine rankings (`most_connected_files`, cycles) if server-side metrics preferred  
4. File content / preview deep-link from inspector (separate API)

---

## 8. Suggested improvements for Branch Surgeon reuse

- Reuse hop neighborhood + path highlight for “impact of change” views  
- Reuse MetricsSidebar degree rankings as surgeon risk signals  
- Reuse NodeInspector edge lists for “who imports / calls this”  
- Layout (LR hierarchical) works well for branch→file→symbol drill-down  
- Do **not** invent surgeon APIs until graph persistence metadata (paths) is richer
