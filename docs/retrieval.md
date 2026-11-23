# Retrieval

`RetrievalService` reads `.refactory/embeddings.json` only.

## APIs

- `search(query, top_k=…)`
- `search_symbol(name, …)`
- `related_files(path, …)`
- Used by `HybridRanker` for review context

## Notes

- Never regenerates embeddings
- Query embedding lookup is deterministically cached
- Search results may be cached by repo fingerprint + model + query
