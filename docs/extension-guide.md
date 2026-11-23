# Extension Guide

## Add a service behind a port

1. Define a `@runtime_checkable` Protocol in `refactory/review/interfaces.py` if ReviewEngine needs it.
2. Implement the service in its package (`refactory/<domain>/`).
3. Wire it in `build_container()`.
4. Keep the CLI as a thin adapter — call the service, render with Rich.
5. Add unit tests that mock at the container boundary.

## Add a CLI command

1. Create `refactory/cli/commands/<name>.py` with Typer entrypoint.
2. Use `get_container()` + `handle_error()`.
3. Prefer shared UI helpers in `refactory/cli/ui/`.
4. Register in `refactory/cli/app.py`.
5. Never put domain logic in the command module.

## Add control-plane config

1. Extend the catalog in `backend/refactory_backend/config/catalog.py`.
2. Expose via `ConfigService` + FastAPI router.
3. Keep payloads free of source code.
4. Update OpenAPI tests and CLI client models.
