# Refactory UI

Local-first Next.js frontend for the Refactory Local REST API.

## Phase 10.1 — Foundation

Includes:

- App shell (sidebar, header, breadcrumbs)
- Command palette (`⌘K` / `Ctrl+K`)
- Theme provider (Light / Dark / **System** default)
- API client + React Query
- Shared design-system components
- Branch Surgeon UI shell (API-gated placeholders)
- Route stubs for upcoming screens

## Setup

```bash
cd ui
npm install
cp .env.example .env.local
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

Start the Local API separately:

```bash
# from repo root, with API extras installed
uvicorn refactory.api.app:app --host 127.0.0.1 --port 8741
```

## Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Dev server |
| `npm run build` | Production build |
| `npm run start` | Serve production build |
| `npm run lint` | ESLint |

## Architecture

See [docs/frontend-architecture.md](../docs/frontend-architecture.md).
