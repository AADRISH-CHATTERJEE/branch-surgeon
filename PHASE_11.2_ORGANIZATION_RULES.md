# Phase 11.2 — Organization Rules Engine (Company Policies)

**Date:** 2026-07-31  
**Scope:** Configurable organization policies additive to Refactory built-in rules (Local API + UI).  
**Constraint:** Do not remove or replace built-in rules. Organization rules extend evaluation.

---

## Architecture

```
Repository / Review / Surgeon / Recommend / Patch Apply
        │
        ▼
CompanyRulesChecker.check()
  ├─ company.yaml checks (existing)
  ├─ architecture.yaml (existing)
  └─ RuleEngine (single evaluate pass)
        ├─ OrganizationRuleService.enabled_as_rules()  ← NEW (source=organization)
        └─ .refactory/rules.yaml                       ← built-in (source=builtin)
        │
        ▼
Merged GateResult (violations tagged Built-in | Organization)
```

**Reuse (no duplicated execution):**

| Capability | Reused |
|------------|--------|
| Evaluation | `RuleEngine.evaluate()` |
| Gate facade | `CompanyRulesChecker` |
| Review block | `ReviewEngine._run_company_rules_gate` |
| Recommendations | `RecommendationEngine._rule_recommendations` |
| Rules Center / Activity / Docs / Settings | existing UI shells |

---

## Schema

### `organization_rules`

| Column | Type |
|--------|------|
| id | string PK |
| name | string |
| description | text |
| category | string |
| severity | string |
| enabled | bool |
| rule_type | string |
| conditions | JSON |
| condition_logic | `and` \| `or` |
| message | text |
| documentation_url | string |
| blocking | bool |
| created_at / updated_at | datetime |

### `organization_rule_audits`

| Column | Type |
|--------|------|
| id | string PK |
| rule_id | string |
| action | created / updated / deleted / enabled / disabled / seeded |
| actor | string (default `local`) |
| changes | JSON before/after |
| created_at | datetime |

Migration: `refactory/db/migrations/versions/2026_07_31_0004_organization_rules.py`  
`DatabaseManager.create_all()` also creates tables for fresh installs.

---

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/organization-rules` | List (+ search / enabled filter); seeds defaults when empty |
| POST | `/organization-rules` | Create |
| GET | `/organization-rules/{id}` | Get |
| PUT | `/organization-rules/{id}` | Update |
| DELETE | `/organization-rules/{id}` | Delete |
| POST | `/organization-rules/{id}/duplicate` | Duplicate (disabled copy) |
| POST | `/organization-rules/{id}/enable` | Enable |
| POST | `/organization-rules/{id}/disable` | Disable |
| POST | `/organization-rules/preview` | Run draft/saved rule vs repo |
| GET | `/organization-rules/export` | Export JSON catalog |
| POST | `/organization-rules/import` | Import JSON |
| GET | `/organization-rules/audit` | Audit trail |

Extended (non-breaking):

- `GET /rules` — adds `builtin_rules`, `organization_rules`, counts, conditions/enabled/source
- `POST /rules/check` — merges org rules; persists `rules-check` activity; violations include `source`

---

## Execution flow

1. Load enabled organization rules → `Rule` objects (`source=organization`)
2. Load built-in `.refactory/rules.yaml` → `source=builtin`
3. Build `RuleContext` (branch, commits, changed files, file contents)
4. `RuleEngine.evaluate()` once
5. Map to `CompanyRuleViolation` with source + documentation_url
6. Gate outcome: any blocking → BLOCK; else violations → WARN; else PASS

**Priority:** Blocking / Critical → Error → Warning → Info. Blocking org rules stop patch apply.

---

## Rule evaluation

Operators: `equals`, `contains`, `matches`, `not_matches`, `starts_with`, `ends_with`, `greater_than`, `less_than`, `exists`, `missing`.  
Logic: per-rule `condition_logic` AND / OR.  
Category evaluators reused (`branch_naming`, `commit_message`, `security_policy`, `required_tests`, …).

---

## UI

**Rules Center tabs**

- **Organization Rules** — CRUD, enable/disable, duplicate, import/export, condition builder, Run Rule preview, docs link
- **Built-in Rules** — read-only catalog from `rules.yaml`

**Violations** show Built-in / Organization badges.  
**Settings → Company Policies** entry links to Organization Rules.  
**Branch Surgeon** surfaces org/blocking violations immediately via existing `useRulesCheck`.  
**Documentation Center** company_policies entry points at Rules Center + Settings.

---

## Integrations

| Surface | Behavior |
|---------|----------|
| Review | Existing gate includes org rules |
| Recommendations | Titles/descriptions mention organization policies |
| Patch apply | Refuses when blocking **organization** violations fire |
| Activity | CRUD commands + rules-check persistence |
| Audit | `organization_rule_audits` |

---

## Known limitations

- Local API has no multi-user auth — audit `actor` defaults to `local`
- Organization rules are instance-global (not per-repository rows)
- Implication-style policies use `required_tests` evaluator (prod pattern → require second pattern)
- Seeded branch-naming example is advisory by default (avoid blocking every apply on `main`)
- Control-plane `OrganizationSettings` is not yet synced into this table

---

## Future enterprise extensions

- Sync / pull policies from control-plane organizations
- Per-repository policy packs and inheritance
- Role-based editors (who may change blockers)
- Git commit / merge / Auto-PR hard stops using the same gate
- Policy packs marketplace / templates
