"""Tests for extended CacheStore protocol methods."""

from __future__ import annotations

import tempfile
from pathlib import Path

from refactory.cache.store import DeterministicCache, NullCache


class TestNullCacheExtended:
    def test_has_always_false(self):
        cache = NullCache()
        cache.set("key", "value")
        assert not cache.has("key")

    def test_delete_noop(self):
        cache = NullCache()
        cache.delete("key")

    def test_keys_empty(self):
        cache = NullCache()
        assert cache.keys() == []

    def test_stats_zero(self):
        cache = NullCache()
        s = cache.stats()
        assert s["entries"] == 0


class TestDeterministicCacheExtended:
    def test_has_memory(self):
        cache = DeterministicCache()
        assert not cache.has("key")
        cache.set("key", {"data": 1})
        assert cache.has("key")

    def test_delete_memory(self):
        cache = DeterministicCache()
        cache.set("key", "value")
        assert cache.has("key")
        cache.delete("key")
        assert not cache.has("key")

    def test_keys(self):
        cache = DeterministicCache(namespace="test")
        cache.set("a", 1)
        cache.set("b", 2)
        keys = cache.keys()
        assert sorted(keys) == ["a", "b"]

    def test_stats_memory(self):
        cache = DeterministicCache()
        cache.set("a", 1)
        cache.set("b", 2)
        s = cache.stats()
        assert s["memory_entries"] == 2

    def test_has_with_disk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = DeterministicCache(disk_dir=Path(tmpdir), namespace="test")
            cache.set("key", {"x": 1})
            cache2 = DeterministicCache(disk_dir=Path(tmpdir), namespace="test")
            assert cache2.has("key")

    def test_delete_with_disk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = DeterministicCache(disk_dir=Path(tmpdir), namespace="test")
            cache.set("key", {"x": 1})
            cache.delete("key")
            assert not cache.has("key")
            cache2 = DeterministicCache(disk_dir=Path(tmpdir), namespace="test")
            assert cache2.get("key") is None

    def test_stats_with_disk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = DeterministicCache(disk_dir=Path(tmpdir), namespace="ns")
            cache.set("a", 1)
            s = cache.stats()
            assert s["memory_entries"] == 1
            assert s["disk_entries"] == 1

    def test_disabled_cache_has(self):
        cache = DeterministicCache(enabled=False)
        cache.set("key", "value")
        assert not cache.has("key")
