# Phase 11.5C — Branch Surgeon Backend Orchestrator API

## Architecture summary

`GET /branch-surgeon` is a gather-only orchestration layer. It does **not** invent new analysis engines.

`BranchSurgeonService.compose_workspace()` calls existing services and returns one `BranchSurgeonWorkspace` DTO for the UI.

```
BranchSurgeonService.compose_workspace()
  ├── GitService (+ CommitService stats)
  ├── RecommendationEngine.calculate_health
  ├── RepositoryQueryService (graph, reviews, recommendations, activity)
  └── CompanyRulesChecker (+ resolve_gate_context)
```

Existing `analyze()` (CLI full BranchAnalysis) is unchanged.

## Surgery Score formula (deterministic, no AI)

```
score = clamp(0, 100,
  health.overall
  - min(40, critical_recs * 8)
  - min(21, high_recs * 3)
  - min(10, pending_reviews * 2)
  - min(30, rule_failures * 10)
  - min(10, rule_warnings * 2)
)

grade:
  >= 85 → Healthy
  >= 70 → Stable
  >= 50 → Caution
  else  → At Risk
```

## API contract

`GET /branch-surgeon`  
Headers: `X-Repo-Root` (same as other repo endpoints)

### Example JSON

```json
{
  "status": "success",
  "data": {
    "branch": {
      "name": "feature/login",
      "base_branch": "master",
      "head_sha": "8ea41d5…",
      "repository": "demo-repo",
      "commits": 3,
      "changed_files": 7,
      "insertions": 92,
      "deletions": 18
    },
    "health": {
      "overall": 86,
      "architecture": 100,
      "security": 100,
      "testing": 20,
      "maintainability": 80
    },
    "surgery": {
      "score": 54,
      "grade": "Caution",
      "formula": "clamp(0,100, health.overall - …)"
    },
    "blast_radius": {
      "node_count": 42,
      "edge_count": 100,
      "critical_files": ["auth.py", "login.py"],
      "most_connected": ["auth.py"]
    },
    "recommendations": { "total": 12, "critical": 2, "high": 4 },
    "reviews": { "completed": 5, "pending": 0, "latest": { "id": "…", "summary": "…" } },
    "rules": { "passed": 1, "failed": 0, "warning_count": 1, "outcome": "warn" },
    "timeline": []
  }
}
```

Empty sections return zeros / `[]` — never `"Unavailable"`.

## How services are reused

| Field | Source |
|-------|--------|
| branch.* | `GitService` commits/changed files + `CommitService` insertions/deletions |
| health.* | `RecommendationEngine.calculate_health` |
| recommendations.* | `RepositoryQueryService.get_recommendations` (counts only) |
| reviews.* | `get_reviews` + pending from `get_analyses` |
| rules.* | `CompanyRulesChecker.check` via `resolve_gate_context` |
| blast_radius.* | Persisted graph via `get_graph` (degree ranking) |
| timeline | `get_analyses` + `get_reviews` |
| surgery.* | Deterministic formula above |

## Frontend

Replaced multi-endpoint fan-out with one hook: `useBranchSurgeon()` → `GET /branch-surgeon`.

UI layout/design preserved; cards now bind workspace fields instead of `Unavailable` placeholders.

## Performance vs previous fan-out

| Before | After |
|--------|-------|
| ~8 parallel browser requests (repo, health, graph, reviews, recs, activity, rules, rules/check) | **1** browser request |
| Graph + health computed/loaded on client composition | Backend orchestrates; reuses persisted graph/recs/reviews where available |
| Rules check often a separate POST | Included in workspace (still uses existing checker) |

Trade-off: backend work is sequential inside one request; UI waits on a single round-trip instead of many.

## Files modified

| File | Why |
|------|-----|
| `refactory/surgeon/models.py` | `BranchSurgeonWorkspace` DTO |
| `refactory/surgeon/service.py` | `compose_workspace()` + helpers |
| `refactory/core/container.py` | Inject query/health/rules deps; construct after they exist |
| `refactory/api/routes/branch_surgeon.py` | `GET /branch-surgeon` |
| `refactory/api/routes/__init__.py` | Register router |
| `ui/services/surgeon.ts` | Fetch + types |
| `ui/queries/use-branch-surgeon.ts` | React Query hook |
| `ui/features/surgeon/**` | Bind workspace data |
| `tests/unit/test_branch_surgeon_api.py` | Orchestration + route tests |
