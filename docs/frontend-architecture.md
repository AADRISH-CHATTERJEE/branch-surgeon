# Phase 10 — Frontend Architecture & UI Design

**Status:** Approved — Phase 10.1 Foundation complete; next is Dashboard (10.2)  
**Audience:** Product + engineering  
**Scope:** Local-first Refactory UI against the existing Local REST API  
**Non-goals:** Backend changes, job queues, WebSockets, inventing file-content APIs

This document is the single source of truth for Phase 10 frontend work. Screens are implemented **one at a time** on top of the shared foundation.

### Approved decisions (2026-07-31)

| Topic | Decision |
|-------|----------|
| Project structure | `ui/` at repo root (separate from Python package and control plane) |
| Default theme | **System**; also support Light and Dark |
| Graph routing | Phase 10 builds **`/repository/graph` only**. `/graph` reserved for a future advanced workspace |
| File preview | Build preview UI now; show metadata + content placeholder; no new content API |
| Branch Surgeon | Ship **UI shell now** (hero, placeholders, empty/API-gated states); wire data when API exists |
| Implementation order | **10.1 Foundation** (shell + design system + API client) before Dashboard |

---

## 0. Product thesis

Refactory UI is a **local engineering platform** that surfaces engines you already run via CLI:

- Review, recommend, transform, rules, graph, index, documentation, activity
- Branch Surgeon is a **flagship product surface** even though its Local API is not yet exposed (see §13 and §20)

It should feel like **GitHub + Linear + Sourcegraph + SonarQube**, not an admin CRUD template:

| Inspiration | What we borrow |
|-------------|----------------|
| GitHub | Repo-centric IA, file tree, PR-like review detail |
| Linear | Keyboard-first, dense but calm lists, command palette |
| Vercel | Status clarity, fast empty→value path, restrained chrome |
| Datadog | Metric tiles, time-aware activity, severity color language |
| Cursor | Local-first, engine-adjacent UX, no cloud theater |
| Sourcegraph | Code navigation, graph/explore mental model |
| SonarQube | Health, rules, violations, gate outcomes |

**Hard product rules**

1. UI talks **only** to Local REST API (`127.0.0.1:8741` by default).
2. No business logic in the frontend — orchestration, presentation, and navigation only.
3. No engine duplication (no second graph builder, no second rules evaluator).
4. Backend / Local API is not modified unless a genuine gap blocks an approved screen.
5. Sync request/response for v1 — no polling infrastructure until a measured need exists.

---

## 1. Folder structure

Package root: **`ui/`** at the repository root (approved). All paths below are relative to that root.

```text
ui/
├── app/                          # Next.js App Router — routes & layouts only
│   ├── (shell)/                  # Authenticated/local app chrome group
│   │   ├── layout.tsx            # AppShell (sidebar + top bar)
│   │   ├── page.tsx              # → redirect or dashboard
│   │   ├── dashboard/page.tsx
│   │   ├── repository/
│   │   │   ├── page.tsx          # Overview
│   │   │   ├── files/page.tsx
│   │   │   ├── symbols/page.tsx
│   │   │   ├── imports/page.tsx
│   │   │   ├── health/page.tsx
│   │   │   └── graph/page.tsx
│   │   ├── reviews/
│   │   │   ├── page.tsx
│   │   │   └── [id]/page.tsx
│   │   ├── recommendations/page.tsx
│   │   ├── transform/page.tsx
│   │   ├── surgeon/page.tsx      # Flagship; API-gated until exposed
│   │   ├── rules/page.tsx
│   │   ├── activity/page.tsx
│   │   ├── documentation/
│   │   │   ├── page.tsx
│   │   │   └── [...slug]/page.tsx
│   │   └── settings/page.tsx
│   ├── layout.tsx                # Root: fonts, providers, theme
│   ├── not-found.tsx
│   ├── error.tsx
│   └── globals.css               # Tailwind entry + CSS variables
│
├── components/                   # Shared, domain-agnostic UI primitives
│   ├── ui/                       # shadcn primitives (button, dialog, …)
│   ├── layout/                   # Sidebar, TopNav, Breadcrumbs, AppShell
│   ├── feedback/                 # EmptyState, ErrorState, Skeletons, Toasts
│   ├── data-display/             # MetricTile, StatusBadge, DataTable shell
│   ├── editors/                  # Monaco wrappers (diff / patch / code)
│   ├── markdown/                 # React Markdown + code highlighting
│   └── graph/                    # React Flow canvas shell (generic)
│
├── features/                     # Domain slices — compose screens
│   ├── dashboard/
│   ├── repository/
│   ├── reviews/
│   ├── recommendations/
│   ├── transform/
│   ├── surgeon/
│   ├── graph/
│   ├── rules/
│   ├── activity/
│   ├── documentation/
│   ├── settings/
│   └── command-palette/
│
├── hooks/                        # Cross-feature React hooks (non-API)
│   ├── use-media-query.ts
│   ├── use-keyboard-shortcut.ts
│   ├── use-debounce.ts
│   └── use-copy-to-clipboard.ts
│
├── lib/                          # Pure utilities (no React, no fetch)
│   ├── cn.ts                     # className merge
│   ├── format.ts                 # dates, risk, scores
│   ├── severity.ts               # status → color/token mapping
│   ├── url-state.ts              # parsers for searchParams
│   └── constants.ts
│
├── services/                     # HTTP boundary — Local API only
│   ├── client.ts                 # fetch wrapper + envelope unwrap
│   ├── errors.ts                 # ApiError, network/timeout mapping
│   ├── endpoints.ts              # path constants
│   ├── repository.ts
│   ├── reviews.ts
│   ├── recommendations.ts
│   ├── transform.ts
│   ├── rules.ts
│   ├── graph.ts
│   ├── activity.ts
│   ├── documentation.ts
│   ├── index.ts                  # health/index status helpers
│   └── surgeon.ts                # stubs / typed gaps until API exists
│
├── queries/                      # TanStack Query keys + hooks
│   ├── keys.ts                   # hierarchical queryKey factory
│   ├── use-repository.ts
│   ├── use-reviews.ts
│   ├── use-recommendations.ts
│   ├── use-graph.ts
│   ├── use-rules.ts
│   ├── use-activity.ts
│   ├── use-documentation.ts
│   ├── use-transform.ts
│   └── use-mutations.ts          # review/recommend/transform/rules
│
├── types/                        # Shared TS types mirroring API data
│   ├── api.ts                    # ApiResponse envelope
│   ├── repository.ts
│   ├── review.ts
│   ├── recommendation.ts
│   ├── graph.ts
│   ├── rules.ts
│   ├── activity.ts
│   └── documentation.ts
│
├── providers/                    # React context providers
│   ├── app-providers.tsx         # composition root
│   ├── query-provider.tsx
│   ├── theme-provider.tsx
│   ├── repo-context.tsx          # active repo root for X-Repo-Root
│   └── ui-preferences.tsx        # sidebar collapsed, density
│
├── layouts/                      # Named layout compositions (non-route)
│   ├── app-shell.tsx
│   ├── split-pane.tsx            # list/detail, tree/preview
│   ├── inspector-layout.tsx      # main + right inspector
│   └── full-bleed.tsx            # graph / monaco focus modes
│
├── styles/
│   ├── tokens.css                # design tokens (color, space, type)
│   └── prose.css                 # markdown typography
│
├── public/
│   └── ...
│
├── package.json
├── next.config.ts
├── tailwind.config.ts
├── components.json               # shadcn
└── tsconfig.json
```

### Why each folder exists

| Folder | Responsibility | Must not contain |
|--------|----------------|------------------|
| `app/` | Routing, layouts, suspense boundaries, SEO metadata | Business rules, raw `fetch` sprawl |
| `components/` | Reusable visual building blocks | Feature-specific API wiring |
| `features/` | Screen sections that know a domain | Cross-cutting primitives that belong in `components/` |
| `hooks/` | Generic React behavior | Query hooks (those live in `queries/`) |
| `lib/` | Pure helpers | Network I/O |
| `services/` | Typed Local API calls | UI markup |
| `queries/` | Cache keys, `useQuery` / `useMutation` | Presentational JSX |
| `types/` | Contracts shared by services + UI | Runtime logic |
| `providers/` | App-wide wiring | Page layouts |
| `layouts/` | Structural compositions reused by features | Route definitions |
| `styles/` | Tokens & prose — complements Tailwind | One-off component hacks |

**Dependency direction (enforced by convention / lint):**

```text
app → features → components → lib
app → queries → services → types
features → queries / hooks / layouts
components ↛ services   (except tiny presentational exceptions)
services ↛ React
```

---

## 2. Routing

Base URL: local Next.js (`http://localhost:3000`).  
API base: `NEXT_PUBLIC_REFACTORY_API_URL` → default `http://127.0.0.1:8741`.

| Route | Responsibility |
|-------|----------------|
| `/` | Redirect to `/dashboard` (or last-visited route from preferences) |
| `/dashboard` | Operational home: health, recent work, quick actions |
| `/repository` | Repo identity, branch, remote, index/graph snapshot |
| `/repository/files` | Indexed file explorer + optional preview pane |
| `/repository/symbols` | Symbol browser (filter by file/path/language) |
| `/repository/imports` | Import graph-ish table (module → consumers later) |
| `/repository/health` | Health scores deep dive |
| `/repository/graph` | Interactive knowledge graph (React Flow) |
| `/reviews` | Persisted review list + run-review CTA |
| `/reviews/[id]` | Full review detail (suggestions, risk, related gate context) |
| `/recommendations` | Recommendation workspace (filter/group/sort) |
| `/transform` | Preview → apply → rollback workflow |
| `/surgeon` | Branch Surgeon flagship experience (API-gated; see §13) |
| `/rules` | Company + built-in rules, gate check, violations |
| `/activity` | Chronological analysis runs timeline |
| `/documentation` | Company docs index |
| `/documentation/[...slug]` | Single doc (architecture, coding, security, testing) |
| `/settings` | API URL, repo root, theme, density, keyboard help |

### Route groups & URL state

- Route group `(shell)` shares AppShell; no URL segment.
- Filters live in **search params** (`?priority=high&q=`, `?path=src/…`, `?node=`), not opaque global stores.
- Deep links are first-class: `/reviews/rev-1`, `/repository/graph?node=…`, `/documentation/architecture`.

### Out of scope for v1 routes

- Auth pages, org/team switchers, multi-project hubs, job detail pages, AI chat routes.

---

## 3. Global layout (application shell)

### Shell anatomy

```text
┌────────────────────────────────────────────────────────────────────┐
│ TopNav: Logo · Breadcrumbs · Search · ⌘K · Status · Theme · Menu  │
├──────────────┬─────────────────────────────────────────────────────┤
│ Sidebar      │  Main content (page)                                │
│              │                                                     │
│ Dashboard    │  Optional right Inspector (context-sensitive)       │
│ Repository ▸ │                                                     │
│ Reviews      │                                                     │
│ Recommend.   │                                                     │
│ Surgeon ★    │                                                     │
│ Transform    │                                                     │
│ Graph        │                                                     │
│ Rules        │                                                     │
│ Activity     │                                                     │
│ Docs         │                                                     │
│ ─────────    │                                                     │
│ Settings     │                                                     │
│ API ● local  │                                                     │
└──────────────┴─────────────────────────────────────────────────────┘
```

### Shell elements

| Element | Behavior |
|---------|----------|
| **Sidebar** | Primary nav; collapsible to icons; remembers preference; Surgeon visually emphasized (flagship) |
| **Top navigation** | Thin utility bar; never competes with page H1 |
| **Search** | Global “jump to”: files, reviews, recommendations, docs sections, nav destinations |
| **Command palette (⌘K / Ctrl+K)** | Linear-style: navigate, run actions (`Run review`, `Check rules`, `Rebuild graph`, `Open settings`) |
| **Notifications** | v1: toast only for mutation outcomes; no notification center until jobs exist |
| **Profile menu** | v1: local identity placeholder (“Local workspace”) + settings + docs link — no auth |
| **Theme switch** | Light / Dark / System; persisted |
| **Status indicators** | API health (from `GET /health`), index staleness, last gate outcome (PASS/WARN/BLOCK) |
| **Breadcrumbs** | Route-derived + entity name when available (`Reviews / #42`) |

### UX flow (happy path)

1. Open UI → shell loads → `GET /health` + `GET /repository` + `GET /repository/status`.
2. If API unreachable → full-page connection state with retry (not a blank dashboard).
3. User lands on Dashboard → scans health + recent reviews/recs → jumps via sidebar or ⌘K.
4. Heavy surfaces (Graph, Monaco) use **full-bleed** layout mode (sidebar auto-collapses or overlays).

---

## 4. Navigation hierarchy

**Primary (sidebar)**

1. Dashboard  
2. Repository (nested: Overview, Files, Symbols, Imports, Health, Graph)  
3. Reviews  
4. Recommendations  
5. Branch Surgeon  
6. Transformations  
7. Repository Graph *(also nested under Repository — dual entry is OK; Graph is both explore and destination)*  
8. Rules  
9. Activity  
10. Documentation  
11. Settings  

**Secondary (contextual)**

- From a review suggestion → file in Repository / Graph node  
- From a recommendation → Transform preview prefilled  
- From a rule BLOCK → Reviews (blocked) + Rules detail  
- From Activity row → originating entity page  

**Tertiary (command palette only)**

- Force rebuild index/graph, open API docs (`/docs` on Local API), copy repo root, toggle density  

**Navigation principles**

- One primary place for each noun (Reviews list, not three competing lists).
- Verbs live in page headers + palette (`Run review`), not as top-level nav items.
- Never require more than **two clicks** from Dashboard to any primary surface.

---

## 5. Component library

### Design layers

1. **Primitives** (`components/ui`) — shadcn: Button, Input, Select, Dialog, Sheet, Tabs, Tooltip, Dropdown, Checkbox, ScrollArea, Separator, Badge  
2. **Patterns** (`components/*`) — composed, still domain-light  
3. **Feature cards** (`features/*/components`) — domain-specific compositions  

### Reusable catalog

| Component | Purpose | Reused on |
|-----------|---------|-----------|
| **RepositoryCard** | Name, branch, remote, head | Dashboard, Repository overview |
| **HealthScoreCard** | Overall + dimension scores | Dashboard, Repository health |
| **RecommendationCard** | Title, priority, status, effort cues | Dashboard, Recommendations |
| **ReviewSummaryCard** | PR/id, risk, confidence, summary | Dashboard, Reviews list |
| **SuggestionCard** | File/line/severity/message | Review detail |
| **RuleViolationCard** | Rule id, severity, blocking | Rules, Review (gate), Dashboard |
| **GraphViewer** | React Flow host + controls | Graph page, optional Dashboard widget (thumbnail) |
| **DiffViewer** | Monaco diff | Transform preview, future Surgeon patches |
| **PatchViewer** | Unified patch / hunk list | Transform, Surgeon |
| **MarkdownViewer** | GFM + code blocks + anchors | Documentation, review summary prose |
| **MetricTile** | Single KPI + spark/caption | Dashboard, Health, Index status |
| **ActivityTimeline** | Vertical time stream | Activity, Dashboard “Latest” |
| **SearchBar** | Debounced query input | Lists, Graph node search, Docs |
| **FilterPanel** | Facets (priority, status, severity) | Recommendations, Reviews, Rules |
| **StatusBadge** | risk / gate / run status | Everywhere |
| **LoadingSkeleton** | Route-aware placeholders | All data pages |
| **EmptyState** | Illustration-free, one CTA | All list pages |
| **ErrorState** | Message + retry | Query failures |
| **ConnectionBanner** | API down / wrong origin | Shell |
| **Inspector** | Right drawer for node/file/rule detail | Graph, Files, Rules |
| **FileTree** | Hierarchical paths from flat file list | Repository files |
| **QuickActionBar** | Primary/secondary actions | Dashboard, page headers |
| **PageHeader** | Title, description, actions | All pages |
| **ConfirmDialog** | Destructive apply/rollback | Transform, Surgeon |

**Composition rule:** Cards are for **interactive list items and KPI clusters**, not decorative wrappers. Prefer open sections with clear hierarchy (Linear/Vercel) over nested card walls.

---

## 6. API layer

### Shared client

- Single `apiClient` in `services/client.ts`.
- Always send `X-Repo-Root` from `RepoContext` (and optional `?root=` for debuggability).
- Parse **ApiResponse** envelope:

```text
{ status: "success" | "error", message, data, errors[], meta }
```

- On `status === "error"` or non-2xx → throw typed `ApiError` with `errors[]`, HTTP status, `message`.
- JSON only; no engine-specific parsing beyond types.

### React Query structure

**Query key factory** (`queries/keys.ts`):

```text
refactory
  └─ repoRoot
       ├─ health
       ├─ repository / status / health / files / symbols / imports
       ├─ reviews / review(id)
       ├─ recommendations (filters)
       ├─ graph / summary / full / node(id)
       ├─ rules / check
       ├─ activity (filters)
       ├─ documentation
       └─ indexStatus
```

Including `repoRoot` in every key ensures cache isolation when the user switches roots.

### Query hooks (reads)

| Hook | Endpoint | Notes |
|------|----------|-------|
| `useApiHealth` | `GET /health` | Short staleTime; drives ConnectionBanner |
| `useRepository` | `GET /repository` | |
| `useRepositoryStatus` | `GET /repository/status` | Index staleness |
| `useRepositoryHealth` | `GET /repository/health` | Heavier — stale longer |
| `useRepositoryFiles` | `GET /repository/files` | |
| `useRepositorySymbols` | `GET /repository/symbols` | keyed by path/file_id |
| `useRepositoryImports` | `GET /repository/imports` | |
| `useGraphSummary` | `GET /graph` | counts/stats |
| `useGraphFull` | `GET /graph/full` | large; careful caching |
| `useGraphNode` | `GET /graph/nodes/{id}` | inspector |
| `useReviews` | `GET /reviews` | |
| `useReview` | `GET /review/{id}` | includes suggestions |
| `useRecommendations` | `GET /recommendations` | filter in queryKey |
| `useRules` | `GET /rules` | |
| `useActivity` | `GET /activity` | |
| `useDocumentation` | `GET /documentation` | |

### Mutation hooks (writes / engine runs)

| Hook | Endpoint | Invalidates |
|------|----------|-------------|
| `useCreateReview` | `POST /review` | reviews, activity, (rules if gated) |
| `useGenerateRecommendations` | `POST /recommend` | recommendations, activity |
| `usePreviewTransform` | `POST /transform` | local mutation cache only |
| `useApplyTransform` | `POST /transform/apply` | files/symbols, activity, recommendations |
| `useRollbackTransform` | `POST /transform/rollback` | same as apply |
| `useRulesCheck` | `POST /rules/check` | rules snapshot, activity |
| `useBuildGraph` | `POST /graph` | graph summary/full |
| `useBuildIndex` | `POST /index` | index status, files |

### Error handling

| Layer | Behavior |
|-------|----------|
| Network / CORS / offline | ConnectionBanner + ErrorState; no toast spam |
| 404 entity | Page-level “not found” with back link |
| 422 validation | Inline form errors from `errors[]` |
| 5xx / engine failure | ErrorState + toast with `message` |
| Envelope error on 200 | Treat as failure (`ApiError`) |

### Retry strategy

- **Queries:** retry 1× for network; **no retry** on 4xx; retry 2× on 5xx with exponential backoff.
- **Mutations:** **no automatic retry** (review/transform are not idempotent from UX view).
- User-triggered **Retry** buttons always available.

### Cache strategy

| Data | `staleTime` | `gcTime` | Notes |
|------|-------------|----------|-------|
| Health / status | 15–30s | 5m | Operational |
| Repository metadata | 60s | 30m | Rarely changes |
| Reviews / recs lists | 30s | 30m | Invalidate on mutations |
| Review detail | 60s | 30m | |
| Graph full | 5m | 30m | Expensive; manual refresh |
| Documentation | 10m | 60m | Disk-backed, stable |
| Activity | 30s | 15m | |

Prefer **explicit invalidation** after mutations over aggressive refetch intervals.  
**No polling** in v1.

### Optimistic updates

Appropriate only where rollback is trivial and conflict risk is low:

- **UI preferences** (sidebar, theme) — local, instant  
- **Recommendation status** — only if/when API supports status patch (today: **not optimistic**)  
- **Transform apply** — **not optimistic**; wait for server, then invalidate  

v1 default: **pessimistic mutations + skeleton/pending buttons**.

---

## 7. State management

| Concern | Home | Examples |
|---------|------|----------|
| Server state | **TanStack Query** | All Local API data |
| Cross-route workspace | **RepoContext** | `repoRoot`, API base override |
| Theme / density / sidebar | **UI preferences** (context + `localStorage`) | |
| Filters, selected tab, selected node | **URL search params** | `?priority=`, `?node=`, `?q=` |
| Ephemeral UI | **Component state** | dialog open, hover, monaco mount |
| Transform preview payload | **Component / feature state** or mutation `data` | Cleared on leave |
| Global client store (Redux/Zustand) | **Avoid** | Not needed for v1 |

**Anti-patterns to reject**

- Duplicating React Query data into Context  
- Storing review lists in Redux  
- Encoding transient hover state in the URL  

---

## 8. Screen designs (cross-cutting contract)

Every screen must specify the following (detailed per surface in §§9–17):

| Dimension | Standard |
|-----------|----------|
| **Purpose** | One job statement |
| **Major components** | From §5 |
| **Layout** | Shell region usage (main / split / inspector / full-bleed) |
| **Interactions** | Primary + secondary actions |
| **Data fetched** | Exact endpoints |
| **Loading** | Skeleton matching final layout (no layout jump) |
| **Empty** | Why empty + one CTA |
| **Error** | Retry + link to Settings/connection |
| **Responsive** | Desktop-first; tablet collapses sidebar; mobile: usable lists, graph limited |

**Responsive policy**

- **≥1280px:** full shell + optional inspector  
- **768–1279px:** collapsed sidebar, inspector becomes Sheet  
- **&lt;768px:** bottom nav or hamburger; Graph in “simplified list of nodes” fallback; Monaco stacked  

---

## 9. Dashboard

### Purpose

Answer in five seconds: *Is this repo healthy, what’s recent, what should I do next?*

### Layout

- PageHeader: repo name + branch + QuickActionBar  
- **Row 1:** HealthScoreCard · Gate StatusBadge · Index MetricTile · Graph MetricTile  
- **Row 2:** Recent Reviews (3) · Recent Recommendations (3)  
- **Row 3:** Latest ActivityTimeline (8) · Rules snapshot  

### Data fetched

- `GET /repository`, `/repository/status`, `/repository/health`
- `GET /reviews?limit=5`, `/recommendations`, `/activity?limit=10`
- `GET /rules` (or last check from activity), `GET /graph` (summary)
- `GET /health`

### Interactions

- Quick actions: Run review · Check rules · Generate recommendations · Open graph  
- Click any card → deep link  

### States

- **Loading:** metric skeletons + list skeletons  
- **Empty:** “No reviews yet” → Run review  
- **Error:** per-widget error (don’t fail entire dashboard if one query fails — **query isolation**)

---

## 10. Repository screen

### Purpose

Understand what’s indexed: identity, structure, and health — the Sourcegraph-lite home for the repo.

### Information architecture

| Subroute | Content |
|----------|---------|
| Overview | Metadata, status, health summary, docs teaser, nav to children |
| Files | FileTree + table; select → optional Monaco preview (read-only if content not in API — **path/metadata only until content API exists**) |
| Symbols | Searchable table; filter by path/type |
| Imports | Module/symbol table; filter by file |
| Health | Full health report |
| Graph | See §14 |

### Layout

- Left: section subnav (or tabs)  
- Main: content  
- Optional inspector for selected file/symbol  

### Data fetched

- Overview: `/repository`, `/status`, `/health`, `/documentation` (titles only)  
- Files/Symbols/Imports: corresponding GET endpoints  
- Health: `/repository/health`

### Interactions

- Language filter on files  
- Jump from symbol → file row  
- “Open in graph” when node mapping is available  

### States

- Empty index: CTA to build index (`POST /index`) from status panel  
- Missing persistence repo: explain need to index/review once so DB row exists  

### Navigation tree

Derived client-side from `GET /repository/files` paths (folder segments). No separate tree API required.

---

## 11. Review screen

### List (`/reviews`)

- Purpose: browse persisted reviews; start new review  
- Components: ReviewSummaryCard list, FilterPanel (risk), SearchBar  
- Data: `GET /reviews`; mutation `POST /review`  
- Empty: run first review  

### Detail (`/reviews/[id]`)

### Purpose

PR-review workspace: risk, narrative, actionable suggestions, gate context.

### Layout (inspector layout)

```text
┌─────────────────────────────┬──────────────────────┐
│ Summary · Risk · Confidence │  Meta / PR / model   │
│ Markdown summary            │  Status badges       │
├─────────────────────────────┤──────────────────────┤
│ Suggestions (list)          │  Related files       │
│ SuggestionCard…             │  Jump to graph/file  │
├─────────────────────────────┴──────────────────────┤
│ Company rule results (if present on activity/gate) │
└────────────────────────────────────────────────────┘
```

### Data fetched

- `GET /review/{id}` (includes `suggestions`)  
- Supporting: `GET /activity?command=rules-check`, `GET /rules` for vocabulary  
- Optional parallel: file metadata for suggestion paths  

### Interactions

- Click suggestion → scroll/highlight file path; open Repository Files with `?path=`  
- “Run again” → `POST /review` with same PR number when known  
- One-click to Rules if BLOCK historically associated  

### States

- Missing id → 404 ErrorState  
- Review with zero suggestions → empty suggestions panel with positive copy  

**Note:** “Comments” in product language maps to **suggestions** in the API. No separate comments resource in v1.

---

## 12. Recommendation screen

### Purpose

Prioritized engineering backlog generated by the Recommendation Engine.

### Layout

- Header + Generate CTA (`POST /recommend`)  
- FilterPanel + SearchBar + sort control  
- Responsive card grid or dense table toggle (preference)

### Card fields (map to API + progressive enhancement)

| UI field | Source |
|----------|--------|
| Title / description | recommendation payload |
| Priority / status / type | payload |
| Confidence | show when present; hide if absent |
| Files | show when present; else “—” |
| Effort | show when present; else omit |
| Reason | description / rationale fields |

### Filtering / grouping / sorting / search

- **Filter:** priority, status, type  
- **Group:** by priority or type (client-side)  
- **Sort:** priority → created_at → title  
- **Search:** title + description client-side on fetched page  

Server-side filter params used when `GET /recommendations` supports them; otherwise client filter with clear “filtered locally” affordance.

### States

- Empty: Generate recommendations  
- Generating: disable CTA, progress toast  
- Error: show engine message  

---

## 13. Branch Surgeon (flagship experience)

### Purpose

Make branch risk legible and remediation **safe, reversible, and explainable** — the product moment that differentiates Refactory.

### Honest API status

Local REST API **does not yet expose** Branch Surgeon. CLI/engine exists. UI architecture still designs the full experience so implementation can proceed in two tracks:

1. **Track A (now):** UI shell + empty/disabled states + contract types in `services/surgeon.ts`  
2. **Track B (later, separate API approval):** thin Local API wrappers — out of this doc’s implementation phase unless explicitly approved  

Do **not** block the rest of Phase 10 on Surgeon API.

### Experience map

| Zone | User question | UI |
|------|---------------|----|
| **Branch Analysis** | What’s wrong with this branch vs base? | Summary scores, commit range, changed file set, risk themes |
| **Suggested Fixes** | What should I do? | Ordered fix cards with rationale + confidence |
| **Safe Operations** | What can I run without fear? | Explicit allowlist ops; confirm dialogs; dry-run default |
| **Impact Summary** | What breaks if I apply this? | Blast radius: files, symbols, tests touched |
| **Branch Visualization** | How did we get here? | Lightweight commit/lane visualization (not full git GUI) |
| **Rollback** | Can I undo? | Rollback panel tied to last Surgeon/transform operation |

### Layout (flagship)

```text
┌────────────────────────────────────────────────────────────┐
│ Branch · base..HEAD · Analyze CTA · Safe mode toggle       │
├──────────────────────────┬─────────────────────────────────┤
│ Visualization            │ Impact Summary                  │
├──────────────────────────┼─────────────────────────────────┤
│ Suggested Fixes (main)   │ Operation Inspector + Diff      │
│                          │ Apply / Rollback                │
└──────────────────────────┴─────────────────────────────────┘
```

### Interactions

- Analyze (mutation when API exists)  
- Select fix → show patch in DiffViewer  
- Apply only after confirm; prefer preview  
- Rollback always visible after successful apply  

### States

- **API missing:** FeatureUnavailable panel — “Available in CLI today; Local API not exposed yet” + link to docs/CLI  
- **Loading analysis:** skeleton + cancel (cancel = client abort only until jobs exist)  
- **Empty clean branch:** success empty state  

### Why flagship

- Combines graph + diff + safety + narrative — highest “platform” density  
- Natural destination from Recommendations and Reviews  

---

## 14. Repository Graph

### Purpose

Interactive exploration of persisted knowledge graph — Sourcegraph-meets-dependency-map.

### Layout

**Full-bleed:** GraphViewer fills main; left search/filter rail; right Inspector.

### Capabilities

| Capability | UX |
|------------|----|
| Zoom / pan | React Flow controls + trackpad |
| Node search | SearchBar filters/focuses nodes |
| Node details | `GET /graph/nodes/{id}` in Inspector |
| Expand/collapse | Client clustering by type / directory prefix for large graphs |
| Relationship types | Legend + edge filter (imports, calls, … from edge.relationship) |
| Highlight dependencies | Select node → emphasize incoming/outgoing |
| File preview | Inspector shows path metadata; preview when file content available |

### Data fetched

- `GET /graph/full` for canvas  
- `GET /graph/nodes/{id}` on selection  
- `GET /graph` for header counts  
- `POST /graph` for rebuild action  

### Performance notes (architecture)

- Virtualize / cluster when `node_count` exceeds threshold (e.g. 1k)  
- Do not refetch full graph on every focus; use staleTime 5m + manual Refresh  
- Selection state in URL: `?node=`

### States

- Empty graph: CTA rebuild  
- Partial load error: ErrorState over canvas  

---

## 15. Rules

### Purpose

Make company gate + rule catalog visible before/after AI review.

### Layout

- Tabs: **Company rules** · **Built-in / standards** · **Violations**  
- Header CTA: Check rules (`POST /rules/check`)  
- Outcome banner: PASS / WARN / BLOCK  

### Display

| Concept | Presentation |
|---------|--------------|
| Company rules | From `GET /rules` + docs cross-links |
| Built-in rules | Listed standards from same payload |
| Violations | RuleViolationCards from last check result |
| Pass/Fail | StatusBadge + summary counts |
| Blocking status | BLOCK emphasized; disables “happy path” CTAs elsewhere via banner |
| Categories | Group by category field when present |

### Data

- `GET /rules`  
- `POST /rules/check`  
- Activity history for prior checks  

### Interactions

- Re-run check with optional base/branch overrides (advanced panel)  
- Click violation → file path in Repository  

---

## 16. Activity

### Purpose

Single timeline of engine runs — Datadog-lite for local ops.

### Event types (from `GET /activity` `command` + status)

- Reviews  
- Recommendations  
- Transforms  
- Rule checks  
- Indexing  
- Graph builds  

### Layout

- Filter chips by command/status  
- ActivityTimeline full width  
- Row click → deep link when entity id present in metadata  

### States

- Empty: “No analysis runs yet”  
- Loading: timeline skeleton  

---

## 17. Documentation

### Purpose

Render company Markdown (architecture, coding, security, testing) as a small internal docs site.

### Layout

```text
┌──────────────┬─────────────────────────────────────┐
│ Doc nav      │  MarkdownViewer                     │
│ + search     │  headings as TOC (right, desktop)   │
└──────────────┴─────────────────────────────────────┘
```

### Capabilities

- Navigation between doc keys  
- In-doc search (client text filter / highlight)  
- Markdown rendering (GFM)  
- Code blocks with copy  
- Anchors from headings; TOC sync on scroll  

### Data

- `GET /documentation` → four markdown strings  
- Client splits routes: `/documentation/architecture`, etc.

### States

- All empty strings → EmptyState “Add company docs under `.refactory/`”  

---

## 18. Design system

### Brand posture

Professional engineering tool: **neutral base, sharp accent, dark-first optional but not mandatory**. Avoid purple-glow SaaS clichés and newspaper/cream template looks.

### Typography

| Role | Guidance |
|------|----------|
| UI sans | Distinctive but readable (e.g. **IBM Plex Sans** or **Geist** — pick one; not Inter-by-default inertia if Geist is chosen intentionally as product font) |
| Code / mono | **IBM Plex Mono** or **Geist Mono** |
| Scale | 12 / 13 / 14 body · 16 section · 20 page title · 24 rare hero (Dashboard only) |
| Weight | Regular + Medium; Semibold for titles; avoid heavy black |

### Spacing

- 4px base grid  
- Page padding: 24px desktop / 16px compact  
- Stack gaps: 8 / 12 / 16 / 24  
- Dense lists (Reviews): 8px row gap  

### Surfaces

- Background: subtle layered neutrals (not flat pure white / pure black only)  
- Cards: 1px border, **no** heavy shadow; radius 6–8px  
- Tables: hairline rows, hover wash  
- Dividers: low-contrast strokes  

### Buttons

| Kind | Use |
|------|-----|
| Primary | One per view (Run review, Analyze) |
| Secondary | Alternate actions |
| Ghost | Table row actions |
| Destructive | Apply dangerous transform / rollback confirm |

### Icons

- Lucide (consistent with shadcn)  
- Stroke icons only; no emoji status  

### Color & themes

**Semantic status (same in light/dark):**

| Token | Meaning |
|-------|---------|
| `status-success` | PASS, healthy, applied |
| `status-warn` | WARN, medium risk |
| `status-danger` | BLOCK, high risk, failed |
| `status-info` | In progress / neutral info |
| `status-muted` | Unknown / stale |

**Themes**

- Light: cool gray canvas, white panels, ink text  
- Dark: deep zinc canvas, elevated panels, careful saturation on status  
- Charts/graph nodes: limited categorical palette (≤6 hues)  

### Animation (Framer Motion — light)

Use motion for **presence**, not decoration:

1. Page section fade/slide **subtle** (150–200ms)  
2. Command palette / dialog scale+fade  
3. Graph inspector panel enter  

No continuous ambient motion. Prefer `prefers-reduced-motion` hard cut.

---

## 19. UX principles

| Principle | Practice |
|-----------|----------|
| **Consistency** | Same StatusBadge, PageHeader, ErrorState everywhere |
| **Minimal clicks** | Dashboard → entity ≤2 clicks; palette for power users |
| **Keyboard-first** | ⌘K, `g` then key nav (g r reviews, g g graph), Esc closes inspectors |
| **Accessibility** | Focus rings, aria on icon buttons, contrast AA, keyboard graph alternatives |
| **Performance** | Code-split Graph + Monaco; query isolation; don’t block shell on slow health |
| **Discoverability** | Empty states teach next action; Surgeon visible but honest about API |
| **Trust** | Show model/provider from status; never hide BLOCK |
| **Local-first honesty** | Connection + repo root always visible in shell footer/status |

---

## 20. Future-proofing

Architecture seams that allow growth **without** rewriting the shell:

| Future capability | Seam today |
|-------------------|------------|
| **Authentication** | Profile menu stub; `providers/auth` later; routes behind `(shell)` already grouped |
| **Teams / orgs** | Org switcher slot in TopNav; query keys gain `orgId` |
| **Projects** | ProjectContext above RepoContext |
| **Remote backend** | `services/client` base URL already configurable; control plane stays separate from Local API |
| **Background jobs** | Introduce `jobs` query namespace + optional `/jobs` routes; mutations return `jobId` later |
| **Live updates** | Swap toast-only → event source behind `providers/realtime` without changing features |
| **Notifications** | TopNav bell mounts on new provider; v1 has no fake badge |
| **AI Chat** | New route `/chat` + feature module; does not invade Review detail |
| **Multi-repository** | RepoSwitcher in sidebar; `repoRoot` already in query keys and `X-Repo-Root` |
| **Branch Surgeon API** | `services/surgeon.ts` + `/surgeon` route already allocated |
| **Embeddings UI** | Fits under Repository or a future `/search` feature module |

**Compatibility rule:** Features depend on **service modules**, not on fetch URLs inline in components — so new endpoints are additive.

---

## 21. Implementation plan (post-approval)

Ordered so each slice ships usable value and only touches frontend:

1. Scaffold `ui/` + providers + AppShell + Settings (connection)  
2. Dashboard (read-only widgets)  
3. Repository overview + files/symbols/imports  
4. Reviews list + detail  
5. Recommendations  
6. Rules  
7. Activity  
8. Documentation  
9. Graph (React Flow)  
10. Transform (Monaco)  
11. Branch Surgeon shell (API-gated)  
12. Command palette + keyboard nav polish  

**Exit criterion per screen:** matches §8 contract, uses only existing Local API (or explicit FeatureUnavailable), no backend changes.

---

## 22. Resolved review questions

| Question | Resolution |
|----------|------------|
| Package location | `ui/` at repo root |
| Default theme | System (with Light / Dark) |
| Graph routes | Build `/repository/graph` in Phase 10; reserve `/graph` for later advanced workspace |
| File preview | Preview component + metadata + placeholder; no content API yet |
| Branch Surgeon | UI shell in Phase 10; wire API later |

---

## Document control

| Field | Value |
|-------|-------|
| Phase | 10 — Approved; 10.1 Foundation first |
| Depends on | Local REST API (Phase 9 + thin read wrappers) |
| Does not modify | `backend/refactory_backend`, engines, Local API (unless approved gap) |
| Next gate | Complete 10.1 Foundation → Dashboard (10.2) |
