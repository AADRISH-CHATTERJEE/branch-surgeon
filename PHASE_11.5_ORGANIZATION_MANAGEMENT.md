# Phase 11.5 — Organization Management

Local multi-tenant organization capabilities (no authentication / SSO / billing).

## What shipped

1. **Organizations** — create, switch, settings/metadata, default seed with Backend / Frontend / Platform teams
2. **Multiple repositories** — link filesystem git roots to an org; UI org + repo switchers update `X-Repo-Root` so Dashboard, Reviews, Recommendations, Graph, Surgeon, Docs, and History refresh for the active repo
3. **Team rule sets** — `organization_rules.organization_id` / `team_id`; precedence merge in `CompanyRulesChecker` / `OrganizationRuleService.enabled_as_rules`:
   - Built-in company checks
   - Organization rules (`team_id` null)
   - Team rules
   - Repository `.refactory/rules.yaml`
4. **RBAC** — Owner, Admin, Maintainer, Reviewer, Developer, Viewer with soft permission checks (`refactory/organization/roles.py`). No login.
5. **Organization dashboard** — repositories, developers, teams, open reviews/recommendations, rule violations stubs
6. **Repository selector** — header switcher + Organization → Settings → Repositories
7. **Team management** — members, repos, leads, active rule-scope toggle
8. **User management** — invite profile (email, role, teams); no email send
9. **Organization settings** — General, Branding, Repositories, Rules, Permissions, Audit, API Keys, Integrations (local stubs where Enterprise)
10. **History context** — `organization_id` + `created_by_user` on `analysis_history`

## Architecture (preserved)

- Local REST API + `ServiceContainer` DI
- Global org catalog at `~/.refactory/db/` via `get_catalog_session_factory()`
- Per-repo SQLite unchanged for analysis / review / patch / history pipelines
- Repository pattern + `UnitOfWork`
- No rewrite of recommendation / review / patch pipelines

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/organizations` | List (+ seed default) |
| POST | `/organizations` | Create |
| GET/PATCH/DELETE | `/organizations/{id}` | CRUD |
| GET | `/organizations/{id}/dashboard` | Org metrics |
| GET/POST | `/organizations/{id}/teams` | Teams |
| GET/POST/PATCH/DELETE | `/organizations/{id}/members` | Members / invite |
| GET/POST/DELETE | `/organizations/{id}/repositories` | Link repos |
| GET | `/organizations/roles` | RBAC catalog |

Headers: `X-Repo-Root`, `X-Org-Id`, `X-Team-Id`, `X-Member-Email` (optional).

## Out of scope (Enterprise)

Authentication, SSO, OAuth, Azure AD, Okta, Google Login, billing, Stripe, email delivery, backend auth service.

## UI

- Nav: **Organization** (Overview, Teams, Members, Settings)
- Header: organization + repository switchers
- Switching repository updates all repo-scoped views via existing React Query + `X-Repo-Root`
