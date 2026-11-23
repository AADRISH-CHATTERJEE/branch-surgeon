# Refactory

Local-first AI repository intelligence CLI with an optional FastAPI control plane.

## Dependency direction

```
CLI (Typer + Rich)
  ↓
Core (settings groups, DI, logging)
  ↓
ReviewEngine
  ↓
Services (Git, Parser, Indexer, Graph, Embedding, Retrieval, Prompt, AI, Response)
  ↓
Infrastructure adapters
```

- CLI is presentation only.
- Business modules must never import `refactory.cli`.
- Backend distributes configuration only — never repository source code.

## Documentation

See **[docs/README.md](docs/README.md)** for architecture, pipeline diagrams, API, extension, and contribution guides.

Frontend (Phase 10): **[ui/README.md](ui/README.md)** · blueprint **[docs/frontend-architecture.md](docs/frontend-architecture.md)**

## Setup

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env
```

## CLI

```bash
refactory status
refactory login --email cli@refactory.dev --password refactory-dev
refactory index
refactory search "auth middleware"
refactory review 25
refactory prompt 25
refactory ai-test
```

When authenticated, the CLI optionally downloads `GET /config` at startup and overlays preferences. If unavailable, local settings are used unchanged.

## Configuration

Nested settings, flat env vars (unchanged names):

| Access path | Env var |
|-------------|---------|
| `settings.ai.provider` | `AI_PROVIDER` |
| `settings.ai.model` | `AI_MODEL` |
| `settings.backend.url` | `REFACTORY_BACKEND_URL` |
| `settings.cache.enabled` | `CACHE_ENABLED` |
| `settings.prompt.max_tokens` | `PROMPT_MAX_TOKENS` |
| `settings.embedding.model` | `EMBEDDING_MODEL` |
| `settings.logging.level` | `LOG_LEVEL` |

## Backend control plane

```bash
cd backend
uvicorn refactory_backend.main:app --reload
```

OpenAPI: `/docs` · Compact config: `GET /config`

## Tests

```bash
python -m pytest -q
```
