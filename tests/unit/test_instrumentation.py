"""Tests for performance instrumentation."""

from __future__ import annotations

import time

from refactory.core.instrumentation import (
    OperationMetrics,
    ServiceInstrumentation,
    _TimedContext,
)
from refactory.core.logger import get_service_logger


def _logger():
    return get_service_logger("test.instrumentation")


class TestOperationMetrics:
    def test_defaults(self):
        m = OperationMetrics(operation="test_op")
        assert m.operation == "test_op"
        assert m.elapsed_seconds == 0.0
        assert m.cache_hits == 0
        assert m.cache_misses == 0
        assert m.items_processed == 0
        assert m.errors == 0

    def test_custom_values(self):
        m = OperationMetrics(
            operation="parse",
            elapsed_seconds=1.5,
            cache_hits=10,
            items_processed=100,
        )
        assert m.elapsed_seconds == 1.5
        assert m.cache_hits == 10
        assert m.items_processed == 100


class TestServiceInstrumentation:
    def test_record_and_retrieve(self):
        inst = ServiceInstrumentation("parser", _logger())
        m = OperationMetrics(operation="parse_file", items_processed=5)
        inst.record(m)
        assert len(inst.metrics) == 1
        assert inst.metrics[0].items_processed == 5

    def test_service_name(self):
        inst = ServiceInstrumentation("graph", _logger())
        assert inst.service_name == "graph"

    def test_clear(self):
        inst = ServiceInstrumentation("test", _logger())
        inst.record(OperationMetrics(operation="op1"))
        inst.record(OperationMetrics(operation="op2"))
        assert len(inst.metrics) == 2
        inst.clear()
        assert len(inst.metrics) == 0

    def test_summary_empty(self):
        inst = ServiceInstrumentation("test", _logger())
        s = inst.summary()
        assert s["operations"] == 0

    def test_summary_aggregates(self):
        inst = ServiceInstrumentation("test", _logger())
        inst.record(OperationMetrics(
            operation="op1", elapsed_seconds=1.0, cache_hits=2, items_processed=10,
        ))
        inst.record(OperationMetrics(
            operation="op2", elapsed_seconds=0.5, cache_misses=1, items_processed=5,
        ))
        s = inst.summary()
        assert s["operations"] == 2
        assert s["total_elapsed_seconds"] == 1.5
        assert s["total_cache_hits"] == 2
        assert s["total_cache_misses"] == 1
        assert s["total_items_processed"] == 15

    def test_timed_context(self):
        inst = ServiceInstrumentation("test", _logger())
        with inst.timed("slow_op") as m:
            time.sleep(0.01)
            m.items_processed = 42
        metrics = inst.metrics
        assert len(metrics) == 1
        assert metrics[0].operation == "slow_op"
        assert metrics[0].elapsed_seconds >= 0.005
        assert metrics[0].items_processed == 42


class TestTimedContext:
    def test_records_elapsed(self):
        inst = ServiceInstrumentation("test", _logger())
        with inst.timed("op") as m:
            m.cache_hits = 3
        assert inst.metrics[0].cache_hits == 3
        assert inst.metrics[0].elapsed_seconds > 0
