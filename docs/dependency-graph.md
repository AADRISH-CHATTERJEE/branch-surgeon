# Dependency Graph

## Allowed direction

```mermaid
flowchart BT
  cli[refactory.cli]
  core[refactory.core]
  review[refactory.review]
  services[git parser indexer graph embedding retrieval prompt ai response]
  backend_cli[refactory.backend]
  fastapi[backend.refactory_backend]

  cli --> core
  cli --> review
  cli --> backend_cli
  cli --> services
  review --> services
  review --> core
  services --> core
  backend_cli --> core
  fastapi -.->|HTTP only| cli
```

## Forbidden

- `refactory.*` (non-cli) importing `refactory.cli`
- Backend importing CLI packages
- ReviewEngine importing concrete providers (uses ports / injected gateway)

Enforced in tests by `tests/unit/test_no_cli_imports_in_core.py`.
