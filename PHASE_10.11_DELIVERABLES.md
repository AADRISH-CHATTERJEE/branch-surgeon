# Phase 10.11 Deliverables — Settings & Preferences

**Date**: July 31, 2026  
**Status**: Complete (UI only; no Local API / backend changes)

---

## 1. Audit

### Existing

| Piece | Before |
|-------|--------|
| Settings page | API URL + repo root + “use header for theme” |
| Theme | `next-themes` + header toggle |
| Persistence | `RepoProvider` (`apiBaseUrl`, `repoRoot`, `sidebarCollapsed`) |
| Health | `GET /health` |
| AI display | Dashboard / repo only via `GET /repository/status` |

### Reusable

`PageContainer` · `MetricStrip` · `StatusBadge` · `Unavailable` · `EmptyState` · `SearchInput` · `Select` · `Dialog` · React Query · Documentation/Rules hooks

### Missing (addressed)

Sectioned settings UX · client preferences store · AI/Company read-only panels · Appearance controls · Notifications · Developer tools · About · Import/Export · settings search · unsaved workspace badge

### Backend limitations

| Soft (show honestly) | Hard (no invent) |
|----------------------|------------------|
| AI provider/model from `/repository/status` | Temperature, max tokens, streaming, prompt version writes |
| Company docs/rules presence | Editing `.env` / company.yaml from UI |
| Backend URL read-only | Control-plane `GET /config` (not wired) |
| Client theme/accent/toasts | Notification center API |

---

## 2. Files

### Added

- `ui/lib/preferences.ts`
- `ui/lib/app-toast.ts`
- `ui/providers/preferences-provider.tsx`
- `ui/components/feedback/app-toaster.tsx`
- `ui/features/settings/settings-view.tsx`
- `ui/features/settings/lib/settings-nav.ts`
- `ui/features/settings/components/setting-row.tsx`
- `PHASE_10.11_DELIVERABLES.md`

### Modified

- `ui/app/(shell)/settings/page.tsx`
- `ui/app/page.tsx` — landing page from preferences
- `ui/providers/app-providers.tsx`
- `ui/lib/constants.ts` — `preferences`, `recentRepos` keys
- `ui/app/globals.css` — accent / density / animations / debug badge

### Deleted

- None (settings page content replaced via feature module)

---

## 3. Architecture

```
SettingsView
  ├── MetricStrip (connection / API / AI / UI version)
  ├── sticky category nav + search
  └── sections
        Workspace | AI | Company | Appearance
        Notifications | Developer | About | Import/Export

Persistence flow
  UI control → PreferencesProvider / RepoProvider / next-themes
           → localStorage (STORAGE_KEYS + theme)
  Read-only AI/Company → React Query (status / rules / documentation)
  Never → Local API write/config endpoints (none exist)
```

---

## 4. Validation

```bash
cd ui
npm run lint   # pass
npm run build  # pass
```

No backend or Local API modifications. Unsupported capabilities labeled **Not Available**, **Managed by Backend**, or **Repository files**.
