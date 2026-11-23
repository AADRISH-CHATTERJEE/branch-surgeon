# Repository Graph

`RepositoryGraphService` builds a typed knowledge graph from `RepositoryIndex`.

## Node / edge kinds (examples)

- Files, modules, packages, classes, functions/methods
- Imports, definitions, calls, inheritance, containment

## Analysis helpers

- Cycles, orphans, unused symbols, dead-code candidates
- `affected_files(path)` for impact during review

Graph builds are cached by repository file-hash digest.
