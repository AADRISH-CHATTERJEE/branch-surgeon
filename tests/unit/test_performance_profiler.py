"""Tests for PerformanceProfiler."""

from __future__ import annotations

import time

import pytest

from refactory.core.profiler import PerformanceProfiler, ProfileReport, StageMetrics


@pytest.fixture
def profiler() -> PerformanceProfiler:
    from loguru import logger
    return PerformanceProfiler(logger=logger)


class TestPerformanceProfiler:
    def test_start_resets(self, profiler: PerformanceProfiler):
        profiler.start()
        report = profiler.report()
        assert report.stages == []
        assert report.total_elapsed_seconds >= 0

    def test_stage_timing(self, profiler: PerformanceProfiler):
        profiler.start()
        with profiler.stage("parsing") as m:
            time.sleep(0.01)
            m.items_processed = 10
        report = profiler.report()
        assert len(report.stages) == 1
        assert report.stages[0].name == "parsing"
        assert report.stages[0].elapsed_seconds >= 0.01
        assert report.stages[0].items_processed == 10

    def test_multiple_stages(self, profiler: PerformanceProfiler):
        profiler.start()
        with profiler.stage("parsing") as m:
            m.items_processed = 5
        with profiler.stage("graph") as m:
            m.items_processed = 3
        report = profiler.report()
        assert len(report.stages) == 2
        assert report.stages[0].name == "parsing"
        assert report.stages[1].name == "graph"

    def test_cache_metrics(self, profiler: PerformanceProfiler):
        profiler.start()
        with profiler.stage("parsing") as m:
            m.cache_hits = 8
            m.cache_misses = 2
        report = profiler.report()
        assert report.cache_hit_ratio == pytest.approx(0.8, abs=0.01)
        assert report.cache_miss_ratio == pytest.approx(0.2, abs=0.01)

    def test_report_summary(self, profiler: PerformanceProfiler):
        profiler.start()
        with profiler.stage("parsing") as m:
            m.items_processed = 5
            m.items_skipped = 10
            m.cache_hits = 10
            m.cache_misses = 5
        summary = profiler.report().summary()
        assert "total_elapsed_ms" in summary
        assert "files_parsed" in summary
        assert "cache_hit_ratio" in summary
        assert summary["files_parsed"] == 5
        assert summary["files_skipped"] == 10

    def test_record_stage_manual(self, profiler: PerformanceProfiler):
        profiler.start()
        metrics = StageMetrics(
            name="custom",
            elapsed_seconds=1.5,
            items_processed=42,
        )
        profiler.record_stage(metrics)
        report = profiler.report()
        assert len(report.stages) == 1
        assert report.stages[0].items_processed == 42

    def test_stage_metrics_defaults(self):
        m = StageMetrics(name="test")
        assert m.elapsed_seconds == 0.0
        assert m.items_processed == 0
        assert m.items_skipped == 0
        assert m.cache_hits == 0
        assert m.cache_misses == 0
        assert m.errors == 0

    def test_profile_report_defaults(self):
        r = ProfileReport()
        assert r.stages == []
        assert r.total_elapsed_seconds == 0.0
        assert r.graph_rebuild_type == "full"

    def test_empty_report_ratios(self, profiler: PerformanceProfiler):
        profiler.start()
        report = profiler.report()
        assert report.cache_hit_ratio == 0.0
        assert report.cache_miss_ratio == 0.0

    def test_graph_rebuild_type_detection(self, profiler: PerformanceProfiler):
        profiler.start()
        with profiler.stage("graph") as m:
            m.cache_misses = 1
            m.items_skipped = 5
        report = profiler.report()
        assert report.graph_rebuild_type == "incremental"
