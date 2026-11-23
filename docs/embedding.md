# Embedding

`EmbeddingService` embeds indexed entities via `EmbeddingProvider`.

## Persistence

Path: `.refactory/embeddings.json`

Incremental reuse when `IndexedFile.content_hash` matches prior record.
Full rebuild when embedding model changes (unless `force`).

## Settings

- `settings.embedding.model` ← `EMBEDDING_MODEL`
- `settings.embedding.chroma_path` ← `CHROMA_PATH` (Chroma adapter present; review path uses JSON store today)
- `settings.embedding.retrieval_top_k` ← `RETRIEVAL_TOP_K`
