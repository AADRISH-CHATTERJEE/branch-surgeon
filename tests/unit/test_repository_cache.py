"""Tests for RepositoryCache and RepositoryFingerprint."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from refactory.cache.repository_cache import (
    CacheEntry,
    CacheMetadata,
    RepositoryCache,
    RepositoryFingerprint,
)


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    d = tmp_path / "cache"
    d.mkdir()
    return d


@pytest.fixture
def cache(cache_dir: Path) -> RepositoryCache:
    return RepositoryCache(cache_dir)


# ---------------------------------------------------------------------------
# RepositoryFingerprint tests
# ---------------------------------------------------------------------------


class TestRepositoryFingerprint:
    def test_default_fingerprint(self):
        fp = RepositoryFingerprint()
        assert fp.git_head == ""
        assert fp.branch == ""
        assert fp.dirty is False
        assert fp.file_hashes == {}
        assert fp.parser_version == "1.0"
        assert fp.graph_version == "1.0"
        assert fp.embedding_version == "1.0"

    def test_digest_is_stable(self):
        fp = RepositoryFingerprint(
            git_head="abc123",
            branch="main",
            file_hashes={"a.py": "h1", "b.py": "h2"},
        )
        d1 = fp.digest()
        d2 = fp.digest()
        assert d1 == d2
        assert len(d1) == 32

    def test_digest_changes_on_file_change(self):
        fp1 = RepositoryFingerprint(file_hashes={"a.py": "h1"})
        fp2 = RepositoryFingerprint(file_hashes={"a.py": "h2"})
        assert fp1.digest() != fp2.digest()

    def test_digest_changes_on_head_change(self):
        fp1 = RepositoryFingerprint(git_head="abc")
        fp2 = RepositoryFingerprint(git_head="def")
        assert fp1.digest() != fp2.digest()

    def test_digest_changes_on_version_change(self):
        fp1 = RepositoryFingerprint(parser_version="1.0")
        fp2 = RepositoryFingerprint(parser_version="2.0")
        assert fp1.digest() != fp2.digest()


# ---------------------------------------------------------------------------
# RepositoryCache tests
# ---------------------------------------------------------------------------


class TestRepositoryCache:
    def test_set_and_get(self, cache: RepositoryCache):
        cache.set("key1", {"value": 42}, "test")
        result = cache.get("key1", "test")
        assert result == {"value": 42}

    def test_get_missing_returns_none(self, cache: RepositoryCache):
        assert cache.get("nonexistent", "test") is None

    def test_has_existing_key(self, cache: RepositoryCache):
        cache.set("k", {"a": 1}, "test")
        assert cache.has("k", "test") is True

    def test_has_missing_key(self, cache: RepositoryCache):
        assert cache.has("k", "test") is False

    def test_delete(self, cache: RepositoryCache):
        cache.set("k", {"a": 1}, "test")
        cache.delete("k", "test")
        assert cache.get("k", "test") is None
        assert cache.has("k", "test") is False

    def test_clear(self, cache: RepositoryCache):
        cache.set("k1", {"a": 1}, "test")
        cache.set("k2", {"b": 2}, "test")
        cache.clear()
        assert cache.get("k1", "test") is None
        assert cache.get("k2", "test") is None

    def test_entries_lists_all(self, cache: RepositoryCache):
        cache.set("k1", {"a": 1}, "test")
        cache.set("k2", {"b": 2}, "test")
        entries = cache.entries()
        assert len(entries) == 2

    def test_stats(self, cache: RepositoryCache):
        cache.set("k1", {"a": 1}, "test")
        cache.get("k1", "test")
        cache.get("missing", "test")
        stats = cache.stats()
        assert stats["entries"] == 1
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_ratio"] == 0.5

    def test_save_and_load_fingerprint(self, cache: RepositoryCache):
        fp = RepositoryFingerprint(
            git_head="abc123",
            branch="main",
            file_hashes={"f.py": "h"},
        )
        cache.save_fingerprint(fp)
        loaded = cache.load_fingerprint()
        assert loaded is not None
        assert loaded.git_head == "abc123"
        assert loaded.branch == "main"
        assert loaded.file_hashes == {"f.py": "h"}

    def test_load_fingerprint_missing(self, cache: RepositoryCache):
        assert cache.load_fingerprint() is None

    def test_is_stale_with_no_saved(self, cache: RepositoryCache):
        fp = RepositoryFingerprint(git_head="abc")
        assert cache.is_stale(fp) is True

    def test_is_stale_with_matching(self, cache: RepositoryCache):
        fp = RepositoryFingerprint(git_head="abc", branch="main")
        cache.save_fingerprint(fp)
        assert cache.is_stale(fp) is False

    def test_is_stale_with_changed(self, cache: RepositoryCache):
        fp1 = RepositoryFingerprint(git_head="abc")
        cache.save_fingerprint(fp1)
        fp2 = RepositoryFingerprint(git_head="def")
        assert cache.is_stale(fp2) is True

    def test_persist_survives_reload(self, cache_dir: Path):
        cache1 = RepositoryCache(cache_dir)
        cache1.set("k1", {"hello": "world"}, "data")
        del cache1

        cache2 = RepositoryCache(cache_dir)
        result = cache2.get("k1", "data")
        assert result == {"hello": "world"}

    def test_hit_and_miss_counting(self, cache: RepositoryCache):
        cache.set("x", {"v": 1}, "test")
        cache.get("x", "test")
        cache.get("x", "test")
        cache.get("y", "test")
        assert cache.hits == 2
        assert cache.misses == 1
        assert cache.hit_ratio == pytest.approx(2 / 3, abs=0.01)

    def test_long_key_handling(self, cache: RepositoryCache):
        long_key = "a" * 300
        cache.set(long_key, {"data": True}, "test")
        result = cache.get(long_key, "test")
        assert result == {"data": True}


# ---------------------------------------------------------------------------
# CacheEntry / CacheMetadata tests
# ---------------------------------------------------------------------------


class TestCacheModels:
    def test_cache_metadata_defaults(self):
        m = CacheMetadata(key="k", entry_type="test")
        assert m.hit_count == 0
        assert m.size_bytes == 0

    def test_cache_entry_with_data(self):
        entry = CacheEntry(
            metadata=CacheMetadata(key="k", entry_type="graph"),
            data={"nodes": [], "edges": []},
        )
        assert entry.data == {"nodes": [], "edges": []}
