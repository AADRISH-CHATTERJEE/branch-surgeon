"""Persistent repository cache with fingerprinting and automatic invalidation.

Survives across CLI executions. Stores parsed ASTs, graph, embeddings metadata,
and repository fingerprints under .refactory/cache/.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Repository Fingerprint (Task 5)
# ---------------------------------------------------------------------------

class RepositoryFingerprint(BaseModel):
    """Uniquely identifies repository state for cache invalidation."""

    git_head: str = ""
    branch: str = ""
    dirty: bool = False
    file_hashes: dict[str, str] = Field(default_factory=dict)
    file_count: int = 0
    parser_version: str = "1.0"
    graph_version: str = "1.0"
    embedding_version: str = "1.0"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def digest(self) -> str:
        """Stable SHA-256 of the fingerprint for cache key derivation."""
        payload = json.dumps(
            {
                "head": self.git_head,
                "branch": self.branch,
                "file_count": self.file_count,
                "parser_version": self.parser_version,
                "graph_version": self.graph_version,
                "embedding_version": self.embedding_version,
                "files_digest": hashlib.sha256(
                    json.dumps(
                        sorted(self.file_hashes.items()),
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Cache Entry / Metadata
# ---------------------------------------------------------------------------

class CacheMetadata(BaseModel):
    """Metadata about a cache entry."""

    key: str
    entry_type: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    fingerprint_digest: str = ""
    size_bytes: int = 0
    hit_count: int = 0
    last_accessed: datetime | None = None


class CacheEntry(BaseModel):
    """A single cache entry with metadata and payload."""

    metadata: CacheMetadata
    data: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Repository Cache
# ---------------------------------------------------------------------------

CACHE_DIR_NAME = "cache"
METADATA_FILE = "_metadata.json"


class RepositoryCache:
    """Persistent disk-backed cache for repository analysis artifacts.

    Structure:
        .refactory/cache/
            _metadata.json      — cache metadata index
            parsed_<hash>.json  — cached parsed ASTs
            graph_<hash>.json   — cached repository graph
            embed_<hash>.json   — cached embedding metadata
            fingerprint.json    — last known fingerprint
    """

    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._metadata: dict[str, CacheMetadata] = {}
        self._hits = 0
        self._misses = 0
        self._load_metadata()

    @property
    def cache_dir(self) -> Path:
        return self._dir

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    @property
    def hit_ratio(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    # ------------------------------------------------------------------
    # Fingerprint operations
    # ------------------------------------------------------------------

    def save_fingerprint(self, fp: RepositoryFingerprint) -> None:
        """Persist the current repository fingerprint."""
        path = self._dir / "fingerprint.json"
        path.write_text(
            fp.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def load_fingerprint(self) -> RepositoryFingerprint | None:
        """Load the last saved fingerprint, or None if missing."""
        path = self._dir / "fingerprint.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return RepositoryFingerprint.model_validate(data)
        except (json.JSONDecodeError, OSError, ValueError):
            return None

    def is_stale(self, current: RepositoryFingerprint) -> bool:
        """Check if the cache is stale compared to current fingerprint."""
        saved = self.load_fingerprint()
        if saved is None:
            return True
        return saved.digest() != current.digest()

    # ------------------------------------------------------------------
    # Generic cache operations
    # ------------------------------------------------------------------

    def get(self, key: str, entry_type: str = "generic") -> dict[str, Any] | None:
        """Retrieve a cached entry by key."""
        path = self._entry_path(key, entry_type)
        if not path.is_file():
            self._misses += 1
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._hits += 1
            meta = self._metadata.get(key)
            if meta:
                meta.hit_count += 1
                meta.last_accessed = datetime.now(timezone.utc)
            return data
        except (json.JSONDecodeError, OSError):
            self._misses += 1
            return None

    def set(
        self,
        key: str,
        data: dict[str, Any],
        entry_type: str = "generic",
        fingerprint_digest: str = "",
    ) -> None:
        """Store a cache entry."""
        path = self._entry_path(key, entry_type)
        content = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
        try:
            path.write_text(content, encoding="utf-8")
        except OSError:
            return
        self._metadata[key] = CacheMetadata(
            key=key,
            entry_type=entry_type,
            fingerprint_digest=fingerprint_digest,
            size_bytes=len(content),
        )
        self._persist_metadata()

    def has(self, key: str, entry_type: str = "generic") -> bool:
        """Check if an entry exists."""
        return self._entry_path(key, entry_type).is_file()

    def delete(self, key: str, entry_type: str = "generic") -> None:
        """Remove a cache entry."""
        path = self._entry_path(key, entry_type)
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass
        self._metadata.pop(key, None)
        self._persist_metadata()

    def clear(self) -> None:
        """Remove all cache entries."""
        if self._dir.exists():
            for f in self._dir.glob("*.json"):
                try:
                    f.unlink()
                except OSError:
                    pass
        self._metadata.clear()
        self._hits = 0
        self._misses = 0

    def entries(self) -> list[CacheMetadata]:
        """List all cache entries."""
        return list(self._metadata.values())

    def stats(self) -> dict[str, object]:
        """Return cache statistics."""
        total_size = sum(m.size_bytes for m in self._metadata.values())
        return {
            "entries": len(self._metadata),
            "total_size_bytes": total_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_ratio": round(self.hit_ratio, 4),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _entry_path(self, key: str, entry_type: str) -> Path:
        safe_key = key.replace("/", "_").replace(":", "_")
        if len(safe_key) > 120:
            safe_key = safe_key[:80] + "_" + hashlib.sha256(safe_key.encode()).hexdigest()[:16]
        return self._dir / f"{entry_type}_{safe_key}.json"

    def _load_metadata(self) -> None:
        path = self._dir / METADATA_FILE
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key, val in data.items():
                self._metadata[key] = CacheMetadata.model_validate(val)
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    def _persist_metadata(self) -> None:
        path = self._dir / METADATA_FILE
        try:
            data = {k: v.model_dump(mode="json") for k, v in self._metadata.items()}
            path.write_text(
                json.dumps(data, sort_keys=True, indent=2, default=str),
                encoding="utf-8",
            )
        except (OSError, TypeError):
            pass
