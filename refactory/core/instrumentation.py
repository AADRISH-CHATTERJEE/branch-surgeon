"""Performance instrumentation for service operations.

Provides timing, cache tracking, and item counting for major services.
Thread-safe and deterministic.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loguru import Logger


@dataclass
class OperationMetrics:
    """Metrics for a single service operation."""

    operation: str
    elapsed_seconds: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    items_processed: int = 0
    errors: int = 0
    extra: dict[str, object] = field(default_factory=dict)


class ServiceInstrumentation:
    """Collect and report timing/cache metrics for a service."""

    def __init__(self, service_name: str, logger: "Logger") -> None:
        self._service_name = service_name
        self._logger = logger
        self._metrics: list[OperationMetrics] = []
        self._lock = threading.Lock()

    @property
    def service_name(self) -> str:
        return self._service_name

    @property
    def metrics(self) -> list[OperationMetrics]:
        with self._lock:
            return list(self._metrics)

    def record(self, metrics: OperationMetrics) -> None:
        with self._lock:
            self._metrics.append(metrics)
        self._logger.debug(
            "[{}] {} — {:.3f}s, processed={}, cache_hit={}, cache_miss={}",
            self._service_name,
            metrics.operation,
            metrics.elapsed_seconds,
            metrics.items_processed,
            metrics.cache_hits,
            metrics.cache_misses,
        )

    def timed(self, operation: str) -> _TimedContext:
        """Context manager that records elapsed time automatically."""
        return _TimedContext(self, operation)

    def clear(self) -> None:
        with self._lock:
            self._metrics.clear()

    def summary(self) -> dict[str, object]:
        """Aggregate summary of all recorded metrics."""
        with self._lock:
            if not self._metrics:
                return {"service": self._service_name, "operations": 0}
            total_elapsed = sum(m.elapsed_seconds for m in self._metrics)
            total_hits = sum(m.cache_hits for m in self._metrics)
            total_misses = sum(m.cache_misses for m in self._metrics)
            total_items = sum(m.items_processed for m in self._metrics)
            total_errors = sum(m.errors for m in self._metrics)
            return {
                "service": self._service_name,
                "operations": len(self._metrics),
                "total_elapsed_seconds": round(total_elapsed, 4),
                "total_cache_hits": total_hits,
                "total_cache_misses": total_misses,
                "total_items_processed": total_items,
                "total_errors": total_errors,
            }


class _TimedContext:
    """Context manager for auto-recording elapsed time."""

    __slots__ = ("_instrumentation", "_operation", "_start", "_metrics")

    def __init__(self, inst: ServiceInstrumentation, operation: str) -> None:
        self._instrumentation = inst
        self._operation = operation
        self._start: float = 0.0
        self._metrics = OperationMetrics(operation=operation)

    def __enter__(self) -> OperationMetrics:
        self._start = time.perf_counter()
        return self._metrics

    def __exit__(self, *_: object) -> None:
        self._metrics.elapsed_seconds = time.perf_counter() - self._start
        self._instrumentation.record(self._metrics)
