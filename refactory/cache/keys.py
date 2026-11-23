"""Deterministic cache key builders (stable across processes)."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_hashes_digest(file_hashes: Mapping[str, str] | None) -> str:
    """Stable digest of path → content_hash map (repository fingerprint)."""
    if not file_hashes:
        return _sha256_hex("empty")
    payload = json.dumps(
        {str(k): str(v) for k, v in sorted(file_hashes.items())},
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return _sha256_hex(payload)


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def graph_cache_key(*, repository_hash: str, index_name: str = "") -> str:
    return f"graph:v1:{repository_hash}:{_sha256_hex(index_name)}"


def prompt_cache_key(
    *,
    repository_hash: str,
    prompt_version: str,
    pr_number: int,
    changed_paths: list[str] | tuple[str, ...],
    budget: Mapping[str, Any] | None = None,
    template_source: str = "local_default",
    context_fingerprint: Mapping[str, Any] | None = None,
) -> str:
    material = _stable_json(
        {
            "repository_hash": repository_hash,
            "prompt_version": prompt_version,
            "pr_number": pr_number,
            "changed_paths": sorted(str(p) for p in changed_paths),
            "budget": budget or {},
            "template_source": template_source,
            "context": context_fingerprint or {},
        }
    )
    return f"prompt:v1:{_sha256_hex(material)}"


def retrieval_cache_key(
    *,
    repository_hash: str,
    model_version: str,
    query: str,
    top_k: int,
    metric: str,
) -> str:
    material = _stable_json(
        {
            "repository_hash": repository_hash,
            "model_version": model_version,
            "query": query,
            "top_k": top_k,
            "metric": metric,
        }
    )
    return f"retrieval:v1:{_sha256_hex(material)}"


def embedding_lookup_key(*, model_version: str, text: str) -> str:
    return f"embed:v1:{_sha256_hex(model_version)}:{_sha256_hex(text)}"


def ai_response_cache_key(
    *,
    provider: str,
    model_version: str,
    system_prompt: str,
    user_prompt: str,
) -> str:
    material = _stable_json(
        {
            "provider": provider,
            "model_version": model_version,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        }
    )
    return f"ai:v1:{_sha256_hex(material)}"
