"""Performance profiler for repository operations.

Collects parsing time, graph time, embedding time, cache hit/miss ratios,
files parsed, files skipped, and overall pipeline timing.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loguru import Logger


@dataclass
class StageMetrics:
    """Metrics for a single pipeline stage."""

    name: str
    elapsed_seconds: float = 0.0
    items_processed: int = 0
    items_skipped: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    errors: int = 0


@dataclass
class ProfileReport:
    """Complete performance profile for a pipeline run."""

    stages: list[StageMetrics] = field(default_factory=list)
    total_elapsed_seconds: float = 0.0
    files_parsed: int = 0
    files_skipped: int = 0
    cache_hit_ratio: float = 0.0
    cache_miss_ratio: float = 0.0
    graph_rebuild_type: str = "full"
    started_at: float = 0.0

    def summary(self) -> dict[str, object]:
        return {
            "total_elapsed_ms": round(self.total_elapsed_seconds * 1000, 1),
            "files_parsed": self.files_parsed,
            "files_skipped": self.files_skipped,
            "cache_hit_ratio": f"{self.cache_hit_ratio:.0%}",
            "cache_miss_ratio": f"{self.cache_miss_ratio:.0%}",
            "graph_rebuild": self.graph_rebuild_type,
            "stages": [
                {
                    "name": s.name,
                    "elapsed_ms": round(s.elapsed_seconds * 1000, 1),
                    "processed": s.items_processed,
                    "skipped": s.items_skipped,
                }
                for s in self.stages
            ],
        }


class PerformanceProfiler:
    """Collect and report performance metrics across pipeline stages."""

    def __init__(self, logger: "Logger") -> None:
        self._logger = logger
        self._stages: list[StageMetrics] = []
        self._lock = threading.Lock()
        self._started: float = 0.0
        self._total_hits = 0
        self._total_misses = 0

    def start(self) -> None:
        """Begin profiling a new pipeline run."""
        self._started = time.perf_counter()
        with self._lock:
            self._stages.clear()
            self._total_hits = 0
            self._total_misses = 0

    def stage(self, name: str) -> _StageTimer:
        """Context manager to time a pipeline stage."""
        return _StageTimer(self, name)

    def record_stage(self, metrics: StageMetrics) -> None:
        """Record a completed stage."""
        with self._lock:
            self._stages.append(metrics)
            self._total_hits += metrics.cache_hits
            self._total_misses += metrics.cache_misses
        self._logger.debug(
            "[profiler] {} — {:.3f}s, processed={}, skipped={}, hits={}, misses={}",
            metrics.name,
            metrics.elapsed_seconds,
            metrics.items_processed,
            metrics.items_skipped,
            metrics.cache_hits,
            metrics.cache_misses,
        )

    def report(self) -> ProfileReport:
        """Generate the final profile report."""
        total_elapsed = time.perf_counter() - self._started if self._started else 0.0
        total_req = self._total_hits + self._total_misses
        hit_ratio = self._total_hits / total_req if total_req > 0 else 0.0
        miss_ratio = self._total_misses / total_req if total_req > 0 else 0.0

        files_parsed = sum(s.items_processed for s in self._stages if "pars" in s.name.lower())
        files_skipped = sum(s.items_skipped for s in self._stages if "pars" in s.name.lower())

        rebuild_type = "incremental"
        for s in self._stages:
            if "graph" in s.name.lower() and s.cache_misses > 0:
                rebuild_type = "full" if s.items_skipped == 0 else "incremental"

        return ProfileReport(
            stages=list(self._stages),
            total_elapsed_seconds=total_elapsed,
            files_parsed=files_parsed,
            files_skipped=files_skipped,
            cache_hit_ratio=hit_ratio,
            cache_miss_ratio=miss_ratio,
            graph_rebuild_type=rebuild_type,
            started_at=self._started,
        )


class _StageTimer:
    """Context manager for timing a single pipeline stage."""

    __slots__ = ("_profiler", "_name", "_start", "_metrics")

    def __init__(self, profiler: PerformanceProfiler, name: str) -> None:
        self._profiler = profiler
        self._name = name
        self._start = 0.0
        self._metrics = StageMetrics(name=name)

    def __enter__(self) -> StageMetrics:
        self._start = time.perf_counter()
        return self._metrics

    def __exit__(self, *_: object) -> None:
        self._metrics.elapsed_seconds = time.perf_counter() - self._start
        self._profiler.record_stage(self._metrics)
