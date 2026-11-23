# Phase 10.8 & 10.9 Deliverables — Rules Center + Activity Timeline

**Date**: July 31, 2026  
**Status**: Complete (UI only; no backend changes)

---

## 1. Audit Report

### Current UI (before)

| Page | State |
|------|--------|
| Rules | Table + one-shot check result |
| Activity | Vertical list + command filter |
| Shared | MetricCard, StatusBadge, SearchInput, FilterBar, skeletons, sheets |

### Current APIs reused

- `GET /rules` — standards + rule catalog (`name`, `category`, `severity`, `blocking`, `message`)
- `POST /rules/check` — PASS/WARN/BLOCK + violations
- `GET /activity` — analyses (`command`, `status`, `duration_ms`, `branch`, `metadata`, …)
- Enrichment: `GET /repository`, `GET /reviews`, `GET /recommendations`, `GET /graph`, `GET /documentation`

### Gaps

| Type | Gap |
|------|-----|
| Soft | Rule example / docs / recommended fix; enabled flag; client date filter; CSS charts (no chart lib) |
| Hard | No rule execution history API; no rule ownership; catalog lacks config payloads; no chart library in repo |

### Soft / hard summary

- **Soft:** degrade with “Not persisted” / placeholders; derive category buckets + trends client-side  
- **Hard:** cannot show true historical gate evaluations or rich rule config without new APIs  

---

## 2. Implementation Summary

### Files added

- `ui/components/data-display/distribution-chart.tsx` — CSS bar/stack charts (no new chart dependency)
- `ui/features/rules/lib/rule-stats.ts`
- `ui/features/activity/lib/activity-meta.ts`
- `PHASE_10.8_10.9_DELIVERABLES.md`

### Files modified

- `ui/features/rules/rules-view.tsx` — full Rules Center
- `ui/features/activity/activity-view.tsx` — full Activity Timeline
- `ui/types/domain.ts` — `AnalysisRun` aligned with API (`duration_ms`, `branch`, …)
- `ui/queries/use-activity.ts` — `status` filter
- `ui/queries/use-rules.ts` — optional check body

### Components created

- `DistributionChart`
- Rules Center sections (inline in `rules-view`)
- Activity timeline cards / recent tiles / kind icons

### Hooks added

- None new — extended `useActivity` / `useRulesCheck` only

### Services reused

- `rules.ts`, `activity.ts`, `documentation`, `repository`, `reviews`, `recommendations`, `graph`

---

## 3. Backend Limitations

1. Rule catalog omits conditions, examples, docs, ownership, enabled  
2. No dedicated rules-check history endpoint (only activity rows if persisted)  
3. Activity metadata/duration often empty depending on writer  
4. No chart library — CSS distributions used intentionally  

---

## 4. Validation

```
npm run lint   → exit 0
npm run build  → exit 0
Tests          → none added (UI has no test runner)
```

---

## 5. Final Report

| Phase | Status |
|-------|--------|
| **10.8 Rules Center** | Complete — policy summary, catalog, check workspace, drawer, stats, standards |
| **10.9 Activity Timeline** | Complete — filters, expandable cards, stats, trend, recent ops |

### Remaining backend work (optional)

- Persist/expose rule config + documentation fields  
- Rules-check history snapshots  
- Consistent `duration_ms` / metadata on analysis runs  
- Optional chart library only if product requires interactive pie charts  
