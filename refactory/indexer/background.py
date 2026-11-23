"""Background indexing service — non-blocking async index operations.

Uses ThreadPoolExecutor to avoid blocking the CLI thread.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.indexer.models import RepositoryIndex
    from refactory.indexer.service import IndexerService


class IndexStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class IndexProgress:
    """Progress state for background indexing."""

    status: IndexStatus = IndexStatus.IDLE
    files_total: int = 0
    files_processed: int = 0
    elapsed_seconds: float = 0.0
    error: str | None = None
    started_at: float = 0.0

    @property
    def progress_pct(self) -> float:
        if self.files_total == 0:
            return 0.0
        return min(100.0, (self.files_processed / self.files_total) * 100)


class BackgroundIndexer:
    """Non-blocking background indexing with progress reporting."""

    def __init__(
        self,
        indexer_service: "IndexerService",
        logger: "Logger",
        *,
        max_workers: int = 2,
    ) -> None:
        self._indexer = indexer_service
        self._logger = logger
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="bg-index")
        self._progress = IndexProgress()
        self._lock = threading.Lock()
        self._future: Future | None = None
        self._callbacks: list[Callable[[IndexProgress], None]] = []

    @property
    def progress(self) -> IndexProgress:
        with self._lock:
            elapsed = 0.0
            if self._progress.started_at > 0 and self._progress.status == IndexStatus.RUNNING:
                elapsed = time.perf_counter() - self._progress.started_at
                self._progress.elapsed_seconds = elapsed
            return self._progress

    @property
    def is_running(self) -> bool:
        return self._progress.status == IndexStatus.RUNNING

    def index_async(
        self,
        root: Path | str,
        *,
        on_complete: Callable[["RepositoryIndex"], None] | None = None,
    ) -> None:
        """Start background indexing. Non-blocking."""
        if self.is_running:
            self._logger.warning("Background indexing already in progress")
            return

        with self._lock:
            self._progress = IndexProgress(
                status=IndexStatus.RUNNING,
                started_at=time.perf_counter(),
            )

        self._logger.info("Background indexing started: {}", root)
        self._future = self._pool.submit(self._run_index, Path(root).resolve(), on_complete)

    def on_progress(self, callback: Callable[[IndexProgress], None]) -> None:
        """Register a progress callback."""
        self._callbacks.append(callback)

    def wait(self, timeout: float | None = None) -> IndexProgress:
        """Block until background indexing completes."""
        if self._future is not None:
            self._future.result(timeout=timeout)
        return self.progress

    def shutdown(self) -> None:
        """Shutdown the thread pool."""
        self._pool.shutdown(wait=False)

    def _run_index(
        self,
        root: Path,
        on_complete: Callable[["RepositoryIndex"], None] | None,
    ) -> None:
        try:
            index = self._indexer.build_index(root)
            with self._lock:
                self._progress.status = IndexStatus.COMPLETED
                self._progress.elapsed_seconds = time.perf_counter() - self._progress.started_at
                self._progress.files_total = len(index.files)
                self._progress.files_processed = len(index.files)
            self._logger.info(
                "Background indexing completed — {} files in {:.2f}s",
                len(index.files),
                self._progress.elapsed_seconds,
            )
            if on_complete:
                on_complete(index)
            self._notify()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._progress.status = IndexStatus.FAILED
                self._progress.error = str(exc)
                self._progress.elapsed_seconds = time.perf_counter() - self._progress.started_at
            self._logger.error("Background indexing failed: {}", exc)
            self._notify()

    def _notify(self) -> None:
        for cb in self._callbacks:
            try:
                cb(self._progress)
            except Exception:  # noqa: BLE001
                pass
