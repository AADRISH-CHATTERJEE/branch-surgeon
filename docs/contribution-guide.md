# Contribution Guide

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -e ".[dev]"
copy .env.example .env
```

## Tests

```bash
python -m pytest -q
```

Backend tests live under `backend/tests/` (included when running from repo root if configured; otherwise `pytest backend/tests tests`).

## Conventions

- Preserve dependency direction (no CLI imports from business code).
- Prefer nested settings groups; keep env var names stable.
- CLI commands are presentation adapters only.
- Backend distributes configuration only — never source code.
- Prefer structured Loguru fields (`bind` / `contextualize`).
- Do not break public APIs (`ReviewEngine.review`, `build_prompt`, port protocols).

## Documentation

Update files under `docs/` when behavior or surfaces change. Keep Mermaid diagrams aligned with the pipeline.
