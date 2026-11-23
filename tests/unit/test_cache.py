"""Deterministic intelligent cache keys and store behavior."""

from __future__ import annotations

from refactory.cache.keys import (
    ai_response_cache_key,
    embedding_lookup_key,
    file_hashes_digest,
    graph_cache_key,
    prompt_cache_key,
    retrieval_cache_key,
)
from refactory.cache.store import DeterministicCache, NullCache
from refactory.core.logger import get_service_logger
from refactory.graph.service import RepositoryGraphService
from datetime import datetime, timezone

from refactory.github.models import PullRequest
from refactory.indexer.models import (
    IndexedFile,
    RepositoryIndex,
    RepositoryStatistics,
    RepositorySummary,
)
from refactory.prompt.builder import PromptBuilder
from refactory.prompt.budget import ContextBudget
from refactory.prompt.models import PromptContext


def test_file_hashes_digest_is_order_independent():
    a = file_hashes_digest({"b.py": "2", "a.py": "1"})
    b = file_hashes_digest({"a.py": "1", "b.py": "2"})
    assert a == b
    assert a != file_hashes_digest({"a.py": "9"})


def test_cache_keys_stable():
    k1 = graph_cache_key(repository_hash="abc", index_name="demo")
    k2 = graph_cache_key(repository_hash="abc", index_name="demo")
    assert k1 == k2
    assert prompt_cache_key(
        repository_hash="abc",
        prompt_version="2.0.0",
        pr_number=1,
        changed_paths=["z.py", "a.py"],
    ) == prompt_cache_key(
        repository_hash="abc",
        prompt_version="2.0.0",
        pr_number=1,
        changed_paths=["a.py", "z.py"],
    )
    assert retrieval_cache_key(
        repository_hash="h",
        model_version="m",
        query="q",
        top_k=5,
        metric="cosine",
    ).startswith("retrieval:")
    assert embedding_lookup_key(model_version="m", text="hello").startswith("embed:")
    assert ai_response_cache_key(
        provider="mock",
        model_version="m",
        system_prompt="s",
        user_prompt="u",
    ).startswith("ai:")


def test_deterministic_cache_roundtrip(tmp_path):
    cache = DeterministicCache(enabled=True, disk_dir=tmp_path / "c", namespace="t")
    cache.set("k1", {"ok": True, "n": 1})
    assert cache.get("k1") == {"ok": True, "n": 1}
    # Reload from disk via fresh instance sharing dir
    other = DeterministicCache(enabled=True, disk_dir=tmp_path / "c", namespace="t")
    assert other.get("k1") == {"ok": True, "n": 1}


def test_null_cache_noop():
    cache = NullCache()
    cache.set("x", 1)
    assert cache.get("x") is None


def test_graph_cache_hit_no_behavior_change():
    index = RepositoryIndex(
        summary=RepositorySummary(
            repository_name="demo",
            repository_root="/tmp/demo",
            total_indexed_files=1,
            timestamp=datetime.now(timezone.utc),
        ),
        statistics=RepositoryStatistics(),
        files=[
            IndexedFile(
                relative_path="a.py",
                module_name="a",
                language="python",
                content_hash="hash-a",
            )
        ],
        file_hashes={"a.py": "hash-a"},
    )
    cache = DeterministicCache(enabled=True, disk_dir=None, namespace="graph")
    svc = RepositoryGraphService(logger=get_service_logger("test.graph"), cache=cache)
    first = svc.build_graph(index)
    second = svc.build_graph(index)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.statistics.total_nodes == second.statistics.total_nodes


def test_prompt_builder_cache_hit():
    cache = DeterministicCache(enabled=True, disk_dir=None, namespace="prompt")
    builder = PromptBuilder(
        logger=get_service_logger("test.prompt"),
        default_budget=ContextBudget(),
        cache=cache,
    )
    pr = PullRequest(
        number=3,
        title="t",
        body="",
        state="open",
        base_branch="main",
        head_branch="feat",
        changed_files=[],
        diff="",
    )
    ctx = PromptContext(pull_request=pr, budget=ContextBudget())
    first = builder.build(ctx)
    second = builder.build(ctx)
    assert first.system_prompt == second.system_prompt
    assert first.user_prompt == second.user_prompt
    assert first.metadata.template_version == second.metadata.template_version
