"""Watch mode — monitor repository for file changes and auto-update.

Uses watchdog for filesystem monitoring when available, falls back to polling.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from loguru import Logger


class WatchEventType(Enum):
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass
class WatchEvent:
    """A single file change event."""

    path: str
    event_type: WatchEventType
    timestamp: float = field(default_factory=time.time)


class FileWatcher:
    """Watch a directory for file changes and invoke callbacks.

    Uses polling-based approach for maximum compatibility.
    If watchdog is available, uses it for efficient OS-level monitoring.
    """

    def __init__(
        self,
        root: Path,
        logger: "Logger",
        *,
        poll_interval: float = 2.0,
        extensions: set[str] | None = None,
        ignore_dirs: set[str] | None = None,
    ) -> None:
        self._root = root.resolve()
        self._logger = logger
        self._poll_interval = poll_interval
        self._extensions = extensions or {".py", ".ts", ".js", ".java", ".go", ".rs"}
        self._ignore_dirs = ignore_dirs or {
            ".git", "__pycache__", "node_modules", ".venv", "venv",
            ".refactory", ".pytest_cache", ".mypy_cache",
        }
        self._running = False
        self._thread: threading.Thread | None = None
        self._callbacks: list[Callable[[list[WatchEvent]], None]] = []
        self._file_hashes: dict[str, str] = {}
        self._lock = threading.Lock()
        self._observer = None

    @property
    def is_running(self) -> bool:
        return self._running

    def on_change(self, callback: Callable[[list[WatchEvent]], None]) -> None:
        """Register a change callback."""
        self._callbacks.append(callback)

    def start(self) -> None:
        """Start watching for changes."""
        if self._running:
            return
        self._running = True
        self._file_hashes = self._scan_files()
        self._logger.info("Watch mode started: {} ({} files tracked)", self._root, len(self._file_hashes))

        if self._try_watchdog():
            return

        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="file-watcher"
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop watching."""
        self._running = False
        if self._observer:
            try:
                self._observer.stop()
                self._observer.join(timeout=2)
            except Exception:  # noqa: BLE001
                pass
            self._observer = None
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        self._logger.info("Watch mode stopped")

    def _try_watchdog(self) -> bool:
        """Try to use watchdog for efficient OS-level monitoring."""
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer

            watcher = self

            class Handler(FileSystemEventHandler):
                def __init__(self) -> None:
                    self._debounce: dict[str, float] = {}
                    self._lock = threading.Lock()

                def _should_process(self, path: str) -> bool:
                    p = Path(path)
                    if p.suffix not in watcher._extensions:
                        return False
                    parts = p.relative_to(watcher._root).parts if p.is_relative_to(watcher._root) else ()
                    return not any(d in watcher._ignore_dirs for d in parts)

                def _debounced(self, path: str) -> bool:
                    now = time.time()
                    with self._lock:
                        last = self._debounce.get(path, 0)
                        if now - last < 0.5:
                            return False
                        self._debounce[path] = now
                    return True

                def on_created(self, event):
                    if not event.is_directory and self._should_process(event.src_path):
                        if self._debounced(event.src_path):
                            watcher._emit([WatchEvent(event.src_path, WatchEventType.CREATED)])

                def on_modified(self, event):
                    if not event.is_directory and self._should_process(event.src_path):
                        if self._debounced(event.src_path):
                            watcher._emit([WatchEvent(event.src_path, WatchEventType.MODIFIED)])

                def on_deleted(self, event):
                    if not event.is_directory and self._should_process(event.src_path):
                        if self._debounced(event.src_path):
                            watcher._emit([WatchEvent(event.src_path, WatchEventType.DELETED)])

            observer = Observer()
            observer.schedule(Handler(), str(self._root), recursive=True)
            observer.daemon = True
            observer.start()
            self._observer = observer
            self._logger.info("Using watchdog for filesystem monitoring")
            return True
        except ImportError:
            self._logger.debug("watchdog not available; using polling")
            return False

    def _poll_loop(self) -> None:
        """Polling fallback for filesystem monitoring."""
        while self._running:
            time.sleep(self._poll_interval)
            if not self._running:
                break
            try:
                events = self._detect_changes()
                if events:
                    self._emit(events)
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("Watch poll error: {}", exc)

    def _detect_changes(self) -> list[WatchEvent]:
        """Compare current file state against cached hashes."""
        current = self._scan_files()
        events: list[WatchEvent] = []

        for path, h in current.items():
            if path not in self._file_hashes:
                events.append(WatchEvent(path, WatchEventType.CREATED))
            elif self._file_hashes[path] != h:
                events.append(WatchEvent(path, WatchEventType.MODIFIED))

        for path in self._file_hashes:
            if path not in current:
                events.append(WatchEvent(path, WatchEventType.DELETED))

        with self._lock:
            self._file_hashes = current
        return events

    def _scan_files(self) -> dict[str, str]:
        """Scan all tracked files and compute hashes."""
        hashes: dict[str, str] = {}
        try:
            for fp in self._root.rglob("*"):
                if not fp.is_file():
                    continue
                if fp.suffix not in self._extensions:
                    continue
                try:
                    rel_parts = fp.relative_to(self._root).parts
                except ValueError:
                    continue
                if any(d in self._ignore_dirs for d in rel_parts):
                    continue
                try:
                    h = hashlib.md5(fp.read_bytes()).hexdigest()  # noqa: S324
                    hashes[str(fp)] = h
                except OSError:
                    pass
        except OSError:
            pass
        return hashes

    def _emit(self, events: list[WatchEvent]) -> None:
        """Notify all registered callbacks."""
        self._logger.debug("Watch events: {}", [(e.event_type.value, e.path) for e in events])
        for cb in self._callbacks:
            try:
                cb(events)
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("Watch callback error: {}", exc)
