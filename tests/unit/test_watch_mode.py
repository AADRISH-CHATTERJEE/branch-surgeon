"""Tests for FileWatcher (watch mode)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from refactory.watch.watcher import FileWatcher, WatchEvent, WatchEventType


@pytest.fixture
def watch_dir(tmp_path: Path) -> Path:
    d = tmp_path / "repo"
    d.mkdir()
    (d / "a.py").write_text("x = 1\n", encoding="utf-8")
    return d


@pytest.fixture
def watcher(watch_dir: Path) -> FileWatcher:
    from loguru import logger
    return FileWatcher(
        watch_dir,
        logger,
        poll_interval=0.1,
    )


class TestFileWatcher:
    def test_start_and_stop(self, watcher: FileWatcher):
        watcher.start()
        assert watcher.is_running is True
        watcher.stop()
        assert watcher.is_running is False

    def test_detect_file_creation(self, watcher: FileWatcher, watch_dir: Path):
        events_received: list[WatchEvent] = []
        watcher.on_change(lambda evts: events_received.extend(evts))
        watcher.start()
        try:
            time.sleep(0.2)
            (watch_dir / "new.py").write_text("y = 2\n", encoding="utf-8")
            time.sleep(0.5)
        finally:
            watcher.stop()
        created = [e for e in events_received if e.event_type == WatchEventType.CREATED]
        assert len(created) >= 1

    def test_detect_file_modification(self, watcher: FileWatcher, watch_dir: Path):
        events_received: list[WatchEvent] = []
        watcher.on_change(lambda evts: events_received.extend(evts))
        watcher.start()
        try:
            time.sleep(0.2)
            (watch_dir / "a.py").write_text("x = 99\n", encoding="utf-8")
            time.sleep(0.5)
        finally:
            watcher.stop()
        modified = [e for e in events_received if e.event_type == WatchEventType.MODIFIED]
        assert len(modified) >= 1

    def test_detect_file_deletion(self, watcher: FileWatcher, watch_dir: Path):
        events_received: list[WatchEvent] = []
        watcher.on_change(lambda evts: events_received.extend(evts))
        watcher.start()
        try:
            time.sleep(0.2)
            (watch_dir / "a.py").unlink()
            time.sleep(0.5)
        finally:
            watcher.stop()
        deleted = [e for e in events_received if e.event_type == WatchEventType.DELETED]
        assert len(deleted) >= 1

    def test_ignore_non_source_files(self, watcher: FileWatcher, watch_dir: Path):
        events_received: list[WatchEvent] = []
        watcher.on_change(lambda evts: events_received.extend(evts))
        watcher.start()
        try:
            time.sleep(0.2)
            (watch_dir / "readme.txt").write_text("hi", encoding="utf-8")
            time.sleep(0.5)
        finally:
            watcher.stop()
        assert len(events_received) == 0

    def test_ignore_pycache_dir(self, watch_dir: Path):
        from loguru import logger
        w = FileWatcher(watch_dir, logger, poll_interval=0.1)
        events_received: list[WatchEvent] = []
        w.on_change(lambda evts: events_received.extend(evts))
        pycache = watch_dir / "__pycache__"
        pycache.mkdir()
        w.start()
        try:
            time.sleep(0.2)
            (pycache / "cache.py").write_text("cached", encoding="utf-8")
            time.sleep(0.5)
        finally:
            w.stop()
        assert len(events_received) == 0

    def test_multiple_callbacks(self, watcher: FileWatcher, watch_dir: Path):
        calls1: list[int] = []
        calls2: list[int] = []
        watcher.on_change(lambda evts: calls1.append(len(evts)))
        watcher.on_change(lambda evts: calls2.append(len(evts)))
        watcher.start()
        try:
            time.sleep(0.2)
            (watch_dir / "b.py").write_text("z = 3\n", encoding="utf-8")
            time.sleep(0.5)
        finally:
            watcher.stop()
        assert len(calls1) >= 1
        assert len(calls2) >= 1

    def test_watch_event_model(self):
        ev = WatchEvent(path="/tmp/a.py", event_type=WatchEventType.CREATED)
        assert ev.path == "/tmp/a.py"
        assert ev.event_type == WatchEventType.CREATED
        assert ev.timestamp > 0

    def test_double_start_noop(self, watcher: FileWatcher):
        watcher.start()
        watcher.start()
        assert watcher.is_running is True
        watcher.stop()

    def test_stop_without_start(self, watcher: FileWatcher):
        watcher.stop()
        assert watcher.is_running is False
