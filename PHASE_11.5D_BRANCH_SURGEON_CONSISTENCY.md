# Phase 11.5D — Branch Surgeon Consistency & UI Bug Fixes

Polish only. No new endpoints, no merge-risk, no AI/schema changes.

## Root causes & fixes

| Bug | Root cause | Fix |
|-----|------------|-----|
| **1 Rec count = 200** | `total=len(rows)` with `limit=200` truncated DB (204) | `count_recommendations()` — true persisted totals |
| **2 Confidence 0%** | UI `confidence: 0` + `?? 0` when field missing; blocked reviews have no confidence | Pass through null; show **Not recorded**; optional rec confidence fallback |
| **3 Duplicate graph labels** | Module + file nodes both listed (`auth` / `auth.py`) | Presentation normalize → prefer `*.py` |
| **4 Health consistency** | Scores already from `calculate_health` (matched 80.2) | No change to scores; keep single health call |
| **5 Surgery Score** | Formula already documented on `surgery.formula` | Documented below |
| **6 Timeline** | Activity+reviews merged; ties unsorted; possible id dupes | Sort `at` desc, then `id`; dedupe keys |
| **7 Labels** | Ambiguous "Recommendations" / "Critical" | "Total Recommendations" / "Critical Recommendations" |

## Surgery Score formula

```
score = clamp(0, 100,
  health.overall
  - min(40, critical_recs * 8)
  - min(21, high_recs * 3)
  - min(10, pending_reviews * 2)
  - min(30, rule_failures * 10)
  - min(10, rule_warnings * 2)
)
```

Inputs: Repository Health overall, rule blockers/warnings, critical/high recommendation counts, pending review analyses.

## Files modified

- `refactory/db/repositories/recommendation.py` — `count_by_repository`
- `refactory/db/query_service.py` — `count_recommendations`
- `refactory/surgeon/service.py` — counts, confidence, label normalize, timeline
- `ui/features/surgeon/components/decision-strip.tsx` — confidence + labels
- `ui/features/surgeon/surgeon-view.tsx` — stop hardcoding confidence 0
- `ui/services/surgeon.ts` — optional confidence
- `tests/unit/test_branch_surgeon_api.py` — regression coverage

## Architecture

Unchanged. Still `GET /branch-surgeon` orchestration only.
