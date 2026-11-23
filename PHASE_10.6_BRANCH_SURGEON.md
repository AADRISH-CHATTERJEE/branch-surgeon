# Phase 10.6 — Branch Surgeon Deliverables

**Date**: July 31, 2026  
**Status**: Complete (composed UI workspace; no backend / no Surgeon REST)

---

## 1. Audit Report

### Engines & UI verified

| Area | Status |
|------|--------|
| Repository Graph (10.7) | Interactive workspace + analytics helpers reusable |
| Review Engine | `POST /review`, `GET /reviews`, `GET /review/{id}` |
| Recommendation Engine | `POST /recommend`, `GET /recommendations`, health via `GET /repository/health` |
| Rule Engine | `GET /rules`, `POST /rules/check` |
| Transform Engine | `POST /transform`, apply, rollback |
| Repository Health | `GET /repository/health` |
| Company Rules | Loaded via rules endpoints |
| Branch Surgeon engine | `BranchSurgeonService.analyze` — **CLI only** |
| Local API surgeon routes | **None** (`refactory/api` has no surgeon module) |
| Existing `/surgeon` page | Placeholder “awaiting API” shell |

### Surgeon engine model (CLI) — not on REST

`BranchAnalysis`: branch, base_branch, health (score/grade/merge risk), commits, changed_files, issues, recommendations.

---

## 2. Gap Report

| Required UI surface | Data source today | Gap |
|---------------------|-------------------|-----|
| Commits / insertions / deletions / changed files | Surgeon `BranchAnalysis` | No REST |
| Surgery Score | `BranchHealth.score` | No REST |
| Branch blast radius | Surgeon `_check_blast_radius` | No REST → graph proxy |
| Merge conflict risk | `BranchHealth.merge_conflict_risk` | No REST → rules proxy |
| Surgeon issues / ADD_TESTS plan | Surgeon recommendations | No REST |
| Apply Safe Fixes | Surgeon + transform | No surgeon apply API |
| Git commit timeline | `BranchCommitSummary` | No REST → activity proxy |
| Branch / base / HEAD | `GET /repository` | Available |
| Repo health / graph / reviews / recs | Existing Local API | Available |

---

## 3. Components Added

- `ui/features/surgeon/components/unavailable.tsx`
- `ui/features/surgeon/components/branch-summary.tsx`
- `ui/features/surgeon/components/surgery-score-card.tsx`
- `ui/features/surgeon/components/blast-radius.tsx`
- `ui/features/surgeon/components/dependency-chain.tsx`
- `ui/features/surgeon/components/action-bar.tsx`
- `PHASE_10.6_BRANCH_SURGEON.md`

---

## 4. Components / files Modified

- `ui/features/surgeon/surgeon-view.tsx` — full decision workspace
- `ui/services/surgeon.ts` — availability + composed/missing inventory

Page route unchanged: `ui/app/(shell)/surgeon/page.tsx`

---

## 5. API Endpoints Reused

- `GET /repository`
- `GET /repository/health`
- `GET /graph/full` (+ `POST /graph` rebuild)
- `GET /reviews` · `POST /review`
- `GET /recommendations` · `POST /recommend`
- `GET /rules` · `POST /rules/check`
- `GET /activity`
- Transform via navigation to `/transform` (`POST /transform*`)

**Not used (do not exist):** `/surgeon*`

---

## 6. Backend Limitations

1. No Local REST wrappers for `BranchSurgeonService`
2. Persistence does not store branch analysis snapshots for UI
3. Graph nodes lack `file_path` for precise blast-radius file mapping
4. No apply-safe-fixes / surgeon export endpoints

---

## 7. Graceful Degradation Strategy

| Field | UI behavior |
|-------|-------------|
| Surgery Score / commits / +/- / changed files | `Unavailable` + reason |
| Blast radius | Graph degree / imports labeled **Graph proxy** |
| Merge risk | Unavailable + rule blocker/warning counts |
| Review order | Composed from critical/high recs + graph degree |
| Test plan | Unavailable + soft filter on test-related recs |
| What Might Break | Critical/high recs + blocking rules |
| Timeline | Activity runs (not git commits) |
| Apply Safe Fixes | Disabled button + tooltip |
| Export Report | Client JSON of composed snapshot only |

Never fabricates Surgery Score or branch diffs.

---

## 8–10. Build / Lint / Tests

```
npm run lint   → exit 0
npm run build  → exit 0
pytest tests/unit/test_branch_surgeon.py tests/unit/test_phase9_local_api.py
```

UI has no dedicated Vitest/Jest suite; Python unit tests cover CLI surgeon + Local API (no surgeon routes).
