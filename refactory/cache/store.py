"""Process-local deterministic cache (optional disk persistence)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Protocol


class CacheStore(Protocol):
    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any) -> None: ...
    def clear(self) -> None: ...
    def has(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def keys(self) -> list[str]: ...
    def stats(self) -> dict[str, int]: ...


class NullCache:
    """No-op cache — preserves uncached behavior."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None

    def clear(self) -> None:
        return None

    def has(self, key: str) -> bool:
        return False

    def delete(self, key: str) -> None:
        return None

    def keys(self) -> list[str]:
        return []

    def stats(self) -> dict[str, int]:
        return {"entries": 0, "hits": 0, "misses": 0}


class DeterministicCache:
    """In-memory cache with optional JSON disk backend under ``.refactory/cache``.

    Values must be JSON-serializable (dicts/lists/scalars) when disk is enabled.
    In-memory path may hold arbitrary Python objects for the process lifetime.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        disk_dir: Path | None = None,
        namespace: str = "default",
    ) -> None:
        self._enabled = enabled
        self._namespace = namespace
        self._memory: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._disk_dir = Path(disk_dir) if disk_dir is not None else None
        if self._disk_dir is not None:
            self._disk_dir.mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def has(self, key: str) -> bool:
        if not self._enabled:
            return False
        full = self._full_key(key)
        with self._lock:
            if full in self._memory:
                return True
        path = self._disk_path(full)
        return path is not None and path.is_file()

    def delete(self, key: str) -> None:
        full = self._full_key(key)
        with self._lock:
            self._memory.pop(full, None)
        path = self._disk_path(full)
        if path is not None and path.is_file():
            try:
                path.unlink()
            except OSError:
                pass

    def keys(self) -> list[str]:
        with self._lock:
            prefix = f"{self._namespace}:"
            return [k.removeprefix(prefix) for k in self._memory if k.startswith(prefix)]

    def stats(self) -> dict[str, int]:
        with self._lock:
            entries = len(self._memory)
        disk = 0
        if self._disk_dir is not None and self._disk_dir.exists():
            disk = sum(1 for _ in self._disk_dir.glob(f"{self._namespace}_*.json"))
        return {"memory_entries": entries, "disk_entries": disk}

    def get(self, key: str) -> Any | None:
        if not self._enabled:
            return None
        full = self._full_key(key)
        with self._lock:
            if full in self._memory:
                return self._memory[full]
            loaded = self._load_disk(full)
            if loaded is not None:
                self._memory[full] = loaded
            return loaded

    def set(self, key: str, value: Any) -> None:
        if not self._enabled:
            return
        full = self._full_key(key)
        with self._lock:
            self._memory[full] = value
            self._store_disk(full, value)

    def clear(self) -> None:
        with self._lock:
            self._memory.clear()
            if self._disk_dir is not None and self._disk_dir.exists():
                for path in self._disk_dir.glob(f"{self._namespace}_*.json"):
                    try:
                        path.unlink()
                    except OSError:
                        pass

    def _full_key(self, key: str) -> str:
        return f"{self._namespace}:{key}"

    def _disk_path(self, full_key: str) -> Path | None:
        if self._disk_dir is None:
            return None
        digest = full_key.replace(":", "_").replace("/", "_")
        # Keep filenames bounded
        if len(digest) > 180:
            digest = digest[:140] + "_" + str(abs(hash(digest)))
        return self._disk_dir / f"{digest}.json"

    def _load_disk(self, full_key: str) -> Any | None:
        path = self._disk_path(full_key)
        if path is None or not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return None

    def _store_disk(self, full_key: str, value: Any) -> None:
        path = self._disk_path(full_key)
        if path is None:
            return
        try:
            path.write_text(
                json.dumps(value, sort_keys=True, separators=(",", ":"), default=str),
                encoding="utf-8",
            )
        except (OSError, TypeError, ValueError):
            # Disk is best-effort; memory cache still holds the value.
            return
