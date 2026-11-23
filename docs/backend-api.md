# Backend API

Control plane for CLI configuration. **Never** accepts repository source code.

Base URL: `REFACTORY_BACKEND_URL` (default `http://127.0.0.1:8000`).

## Auth (unchanged)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/login` | Issue JWT pair |
| POST | `/auth/refresh` | Refresh tokens |
| GET | `/auth/me` | Current user |

## Configuration

| Method | Path | Description |
|--------|------|-------------|
| GET | `/config` | Compact CLI config |
| GET | `/config/bundle` | Full org/repo bundle |
| GET | `/prompts` | Version list |
| GET | `/prompts/review` | Prompt template (`?version=`) |
| GET | `/workflows` | Version list |
| GET | `/workflows/review` | Workflow definition |
| GET | `/organizations/{id}` | Org settings |
| GET | `/repositories/{id}` | Repo settings (metadata only) |

### `GET /config` response

```json
{
  "prompt_version": "2.0.0",
  "workflow_version": "2.0.0",
  "ai_provider": "mock",
  "model": "mock-review-1",
  "feature_flags": {"telemetry_enabled": true},
  "limits": {"max_tokens": 6000, "max_retries": 3}
}
```

CLI fetches this at startup when authenticated; on failure it falls back to local settings.

## Other

| Method | Path | Description |
|--------|------|-------------|
| POST | `/telemetry` | Metadata events (no source keys) |
| GET | `/health` | Liveness |
| GET | `/docs` | OpenAPI UI |
