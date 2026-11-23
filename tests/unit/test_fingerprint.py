"""Tests for RepositoryFingerprint."""

from __future__ import annotations

import pytest

from refactory.cache.repository_cache import RepositoryFingerprint


class TestRepositoryFingerprint:
    def test_empty_fingerprint(self):
        fp = RepositoryFingerprint()
        d = fp.digest()
        assert isinstance(d, str)
        assert len(d) == 32

    def test_same_state_same_digest(self):
        fp1 = RepositoryFingerprint(git_head="abc", branch="main", file_hashes={"a.py": "h"})
        fp2 = RepositoryFingerprint(git_head="abc", branch="main", file_hashes={"a.py": "h"})
        assert fp1.digest() == fp2.digest()

    def test_different_head_different_digest(self):
        fp1 = RepositoryFingerprint(git_head="abc")
        fp2 = RepositoryFingerprint(git_head="def")
        assert fp1.digest() != fp2.digest()

    def test_different_branch_different_digest(self):
        fp1 = RepositoryFingerprint(branch="main")
        fp2 = RepositoryFingerprint(branch="dev")
        assert fp1.digest() != fp2.digest()

    def test_different_files_different_digest(self):
        fp1 = RepositoryFingerprint(file_hashes={"a.py": "h1"})
        fp2 = RepositoryFingerprint(file_hashes={"a.py": "h2"})
        assert fp1.digest() != fp2.digest()

    def test_parser_version_affects_digest(self):
        fp1 = RepositoryFingerprint(parser_version="1.0")
        fp2 = RepositoryFingerprint(parser_version="2.0")
        assert fp1.digest() != fp2.digest()

    def test_graph_version_affects_digest(self):
        fp1 = RepositoryFingerprint(graph_version="1.0")
        fp2 = RepositoryFingerprint(graph_version="2.0")
        assert fp1.digest() != fp2.digest()

    def test_embedding_version_affects_digest(self):
        fp1 = RepositoryFingerprint(embedding_version="1.0")
        fp2 = RepositoryFingerprint(embedding_version="2.0")
        assert fp1.digest() != fp2.digest()

    def test_dirty_state_does_not_affect_digest(self):
        fp1 = RepositoryFingerprint(git_head="abc", dirty=False)
        fp2 = RepositoryFingerprint(git_head="abc", dirty=True)
        assert fp1.digest() == fp2.digest()

    def test_file_count_affects_digest(self):
        fp1 = RepositoryFingerprint(file_count=10)
        fp2 = RepositoryFingerprint(file_count=20)
        assert fp1.digest() != fp2.digest()

    def test_many_files_stable(self):
        hashes = {f"file_{i}.py": f"hash_{i}" for i in range(1000)}
        fp = RepositoryFingerprint(file_hashes=hashes)
        d1 = fp.digest()
        d2 = fp.digest()
        assert d1 == d2

    def test_file_order_independent(self):
        fp1 = RepositoryFingerprint(file_hashes={"b.py": "h2", "a.py": "h1"})
        fp2 = RepositoryFingerprint(file_hashes={"a.py": "h1", "b.py": "h2"})
        assert fp1.digest() == fp2.digest()
