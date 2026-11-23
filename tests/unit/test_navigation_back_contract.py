"""Frontend-facing path helpers for repository navigation (no GitHub UI)."""

from __future__ import annotations

# Pure logic mirrored in ui/lib/navigation-back.ts — keep parents off /dashboard.


def logical_parent_path(pathname: str) -> str:
    roots = {"/", "/surgeon", "/dashboard"}
    p = pathname.rstrip("/") or "/"
    if p in roots:
        return "/surgeon"
    prefixes = [
        ("/repository/graph", "/repository"),
        ("/repository", "/surgeon"),
        ("/reviews", "/surgeon"),
        ("/recommendations", "/surgeon"),
        ("/history", "/surgeon"),
        ("/activity", "/surgeon"),
    ]
    best = None
    for prefix, parent in prefixes:
        if p == prefix or p.startswith(prefix + "/"):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, parent)
    return best[1] if best else "/surgeon"


def test_section_roots_go_to_surgeon():
    assert logical_parent_path("/reviews") == "/surgeon"
    assert logical_parent_path("/repository") == "/surgeon"
    assert logical_parent_path("/dashboard") == "/surgeon"


def test_nested_repository_routes():
    assert logical_parent_path("/repository/graph") == "/repository"
