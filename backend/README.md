# Refactory Backend (Control Plane)

FastAPI control plane for the Refactory CLI. Authenticates clients and serves centralized configuration: prompt templates, workflow definitions, feature flags, and telemetry.

This service does **not**:

- parse repositories
- generate embeddings
- run AI reviews
- store customer source code

## Layout

```
backend/
├── alembic/                 # Migrations
├── refactory_backend/
│   ├── api/                 # Route handlers
│   ├── auth/                # JWT / password helpers
│   ├── core/                # Settings, security, deps
│   ├── db/                  # Engine / sessions
│   ├── models/              # SQLAlchemy ORM
│   ├── schemas/             # Pydantic request/response models
│   ├── services/            # Auth + telemetry services
│   ├── prompts/             # Static prompt templates
│   ├── workflows/           # Static workflow definitions
│   ├── telemetry/           # Telemetry package surface
│   └── main.py              # FastAPI app
└── tests/
```

## Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/auth/login` | No | Issue access + refresh JWTs |
| POST | `/auth/refresh` | No | Rotate tokens |
| GET | `/auth/me` | Yes | Current user profile |
| GET | `/prompts/review` | Yes | Static review prompt JSON |
| GET | `/workflows/review` | Yes | Static review workflow + feature flags |
| POST | `/telemetry` | Yes | Accept CLI telemetry (metadata only) |
| GET | `/health` | No | Liveness |
| GET | `/docs` | No | OpenAPI UI |

## Run locally

From the repo root (with venv active):

```powershell
pip install -e ".[backend,dev]"
cd backend
uvicorn refactory_backend.main:app --reload --port 8000
```

Open http://127.0.0.1:8000/docs

Default seed user (development):

- email: `cli@refactory.dev`
- password: `refactory-dev`

Override via `REFACTORY_SEED_ADMIN_*` / `REFACTORY_JWT_SECRET` / `REFACTORY_DATABASE_URL`.

## Migrations

```powershell
cd backend
alembic upgrade head
```

## Tests

```powershell
# from repo root
pytest backend/tests -q
```
