# Phase 11.2.5 — Navigation Polish (Back Navigation)

**Date:** 2026-07-31  
**Scope:** Frontend-only consistent in-app Back navigation.  
**Constraint:** No Local API / backend changes.

---

## Goal

Replace browser-only Back reliance with a first-class, reusable Back control across Refactory.

---

## Architecture

```
AppShell
  └─ BackNavProvider          ← Alt+← shortcut; chromeProvidesBack flag
       └─ Header
            └─ AppBreadcrumbs
                 ← BackButton (before crumbs, hidden on Dashboard)
                 Repository > Graph
       └─ main
            └─ PageHeader     ← BackButton when not provided by chrome
```

| Piece | Path |
|-------|------|
| Back control | `ui/components/navigation/back-button.tsx` |
| Parent map | `ui/lib/navigation-back.ts` |
| Chrome + shortcut | `ui/providers/back-nav-provider.tsx` |
| Breadcrumbs row | `ui/components/layout/app-breadcrumbs.tsx` |
| Page title | `ui/components/page-header.tsx` |
| Drawer focus | `ui/components/shared/detail-drawer.tsx` |

---

## Back behavior

1. If in-app history can go back → `router.back()`
2. Else → navigate to **logical parent**

| Current | Parent |
|---------|--------|
| `/reviews` (+ detail `?id=`) | `/reviews` (strip detail) then `/dashboard` |
| `/recommendations` | `/dashboard` (or list if `?id=`) |
| `/repository/graph` | `/repository` |
| `/surgeon`, `/rules`, `/documentation`, `/settings`, `/activity` | `/dashboard` |
| `/history` (future) | `/dashboard` |
| `/dashboard` | *(no Back)* |

Detail query keys treated as “leave detail, stay on section”: `id`, `file`, `doc`.

---

## PageHeader

- Prop `showBack?: boolean | "auto"` (default `"auto"`)
- Prop `backFallbackHref?` for overrides
- Auto: show on feature pages **unless** shell chrome already renders Back (avoids duplicate)
- Dashboard: never

---

## Keyboard

- **Alt + ←** registered in `BackNavProvider`
- Skipped when focus is in `input` / `textarea` / `select` / `contenteditable`
- Does **not** `preventDefault` — browser Back remains free to run

---

## Breadcrumbs

```
← Back   Repository  >  Graph
```

Back is the first control in the breadcrumb row; crumbs unchanged.

---

## Drawers

- Esc still closes (Radix Sheet)
- On open: remember `document.activeElement`
- On close (`onCloseAutoFocus`): restore focus to that trigger, else `#main-content`

---

## Accessibility

- `aria-label="Go Back"`
- Keyboard-focusable ghost button
- Visible `focus-visible` ring

---

## Validation

- `npm run lint`
- `npm run build`

---

## Known limitations

- `history.length > 1` is a heuristic when the Navigation API is unavailable (may occasionally prefer `router.back()` over parent)
- PageHeader Back is suppressed inside AppShell to avoid two Back buttons; chrome is the primary surface
