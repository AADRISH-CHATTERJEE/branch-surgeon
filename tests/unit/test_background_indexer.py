"""Tests for BackgroundIndexer."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from refactory.indexer.background import BackgroundIndexer, IndexProgress, IndexStatus


@pytest.fixture
def mock_indexer():
    indexer = MagicMock()
    mock_index = MagicMock()
    mock_index.files = [MagicMock()] * 5
    indexer.build_index.return_value = mock_index
    return indexer


@pytest.fixture
def bg_indexer(mock_indexer) -> BackgroundIndexer:
    from loguru import logger
    return BackgroundIndexer(mock_indexer, logger=logger, max_workers=1)


class TestBackgroundIndexer:
    def test_initial_state(self, bg_indexer: BackgroundIndexer):
        assert bg_indexer.is_running is False
        assert bg_indexer.progress.status == IndexStatus.IDLE

    def test_index_async_starts(self, bg_indexer: BackgroundIndexer, tmp_path: Path):
        bg_indexer.index_async(tmp_path)
        time.sleep(0.5)
        assert bg_indexer.progress.status in (IndexStatus.RUNNING, IndexStatus.COMPLETED)

    def test_index_async_completes(self, bg_indexer: BackgroundIndexer, tmp_path: Path):
        bg_indexer.index_async(tmp_path)
        progress = bg_indexer.wait(timeout=5)
        assert progress.status == IndexStatus.COMPLETED
        assert progress.files_total == 5

    def test_on_complete_callback(self, bg_indexer: BackgroundIndexer, tmp_path: Path):
        results = []
        bg_indexer.index_async(tmp_path, on_complete=lambda idx: results.append(idx))
        bg_indexer.wait(timeout=5)
        assert len(results) == 1

    def test_progress_callback(self, bg_indexer: BackgroundIndexer, tmp_path: Path):
        progress_reports = []
        bg_indexer.on_progress(lambda p: progress_reports.append(p))
        bg_indexer.index_async(tmp_path)
        bg_indexer.wait(timeout=5)
        assert len(progress_reports) >= 1

    def test_failed_indexing(self, tmp_path: Path):
        from loguru import logger
        bad_indexer = MagicMock()
        bad_indexer.build_index.side_effect = RuntimeError("boom")
        bg = BackgroundIndexer(bad_indexer, logger=logger, max_workers=1)
        bg.index_async(tmp_path)
        progress = bg.wait(timeout=5)
        assert progress.status == IndexStatus.FAILED
        assert "boom" in progress.error

    def test_double_start_warning(self, bg_indexer: BackgroundIndexer, tmp_path: Path):
        bg_indexer.index_async(tmp_path)
        bg_indexer.index_async(tmp_path)
        bg_indexer.wait(timeout=5)

    def test_elapsed_time(self, bg_indexer: BackgroundIndexer, tmp_path: Path):
        bg_indexer.index_async(tmp_path)
        bg_indexer.wait(timeout=5)
        assert bg_indexer.progress.elapsed_seconds > 0

    def test_shutdown(self, bg_indexer: BackgroundIndexer):
        bg_indexer.shutdown()

    def test_progress_pct(self):
        p = IndexProgress(files_total=10, files_processed=5)
        assert p.progress_pct == 50.0

    def test_progress_pct_zero(self):
        p = IndexProgress(files_total=0)
        assert p.progress_pct == 0.0
