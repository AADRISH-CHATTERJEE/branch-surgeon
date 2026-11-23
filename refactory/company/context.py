"""Resolve rich git context for the company-rules gate.

Prefer real branch commits and base-branch diffs over PR title alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from refactory.company.models import GateContext

if TYPE_CHECKING:
    from refactory.git.service import GitService
    from refactory.github.models import PullRequest


def resolve_gate_context(
    git: "GitService | None",
    *,
    branch_name: str | None = None,
    commit_message: str | None = None,
    base_branch: str | None = None,
    changed_files: list[str] | None = None,
    pull_request: "PullRequest | None" = None,
    max_commits: int = 50,
) -> GateContext:
    """Build gate context from git (+ optional PR / CLI overrides).

    Priority (highest first):

    * **branch** — explicit → PR head → current git branch
    * **base** — explicit → PR base → git default branch
    * **commits** — explicit message → branch commits since base → HEAD → PR title
    * **files** — explicit → PR files → git vs base → working tree
    """
    sources: list[str] = []

    resolved_branch = (branch_name or "").strip()
    if resolved_branch:
        sources.append("override")
    elif pull_request is not None and (pull_request.head_branch or "").strip():
        resolved_branch = pull_request.head_branch.strip()
        sources.append("pr")
    else:
        resolved_branch = _safe_git(git, "get_current_branch", default="") or ""
        if resolved_branch:
            sources.append("git")

    resolved_base = (base_branch or "").strip()
    if not resolved_base and pull_request is not None:
        resolved_base = (pull_request.base_branch or "").strip()
    if not resolved_base:
        resolved_base = _safe_git(git, "get_default_branch", default="") or ""
    if not resolved_base:
        resolved_base = "main"

    # --- Commit messages ---
    override_commit = (commit_message or "").strip()
    commit_messages: list[str] = []
    primary_commit = ""
    head_sha: str | None = None

    if override_commit:
        primary_commit = override_commit.splitlines()[0].strip()
        commit_messages = [primary_commit]
        sources.append("override")
    else:
        branch_commits = _branch_commit_subjects(git, resolved_base, max_commits=max_commits)
        if branch_commits:
            commit_messages = branch_commits
            primary_commit = branch_commits[0]
            sources.append("git")
        else:
            head = _safe_git(git, "get_current_commit", default=None)
            msg = ""
            if head is not None and not isinstance(head, (str, int, float, bool)):
                raw = getattr(head, "message", "") or ""
                if isinstance(raw, str):
                    msg = raw.strip()
                sha = getattr(head, "sha", None)
                if isinstance(sha, str):
                    head_sha = sha
            if msg:
                primary_commit = msg.splitlines()[0].strip()
                commit_messages = [primary_commit]
                sources.append("git")

        if not primary_commit and pull_request is not None:
            title = (pull_request.title or "").strip()
            if title:
                primary_commit = title.splitlines()[0].strip()
                commit_messages = [primary_commit]
                sources.append("pr")

    if head_sha is None:
        raw_sha = _safe_git(git, "get_head_sha", default=None)
        head_sha = raw_sha if isinstance(raw_sha, str) else None

    # --- Changed files ---
    # When a PullRequest is provided, its change set is authoritative — even if empty.
    # Never fall back to the working tree for PR-scoped gates (avoids dirty-tree bleed).
    files: list[str] = []
    if changed_files is not None:
        files = [f.replace("\\", "/") for f in changed_files]
        if files:
            sources.append("override")
    elif pull_request is not None:
        files = [
            f.path.replace("\\", "/")
            for f in pull_request.changed_files
            if f.path
        ]
        sources.append("pr")
    else:
        files = _changed_files_vs_base(git, resolved_base)
        if files:
            sources.append("git")
        if not files:
            files = _working_tree_files(git)
            if files:
                sources.append("git")

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_files: list[str] = []
    for path in files:
        if path and path not in seen:
            seen.add(path)
            unique_files.append(path)

    unique_msgs: list[str] = []
    seen_msg: set[str] = set()
    for msg in commit_messages:
        if msg and msg not in seen_msg:
            seen_msg.add(msg)
            unique_msgs.append(msg)

    source = "mixed" if len(set(sources)) > 1 else (sources[0] if sources else "unknown")
    return GateContext(
        branch_name=resolved_branch,
        base_branch=resolved_base,
        commit_message=primary_commit,
        commit_messages=unique_msgs or ([primary_commit] if primary_commit else []),
        changed_files=unique_files,
        head_sha=head_sha,
        source=source,
    )


def _safe_git(git: "GitService | None", method: str, *, default: Any) -> Any:
    if git is None:
        return default
    fn = getattr(git, method, None)
    if not callable(fn):
        return default
    try:
        value = fn()
        if value is None:
            return default
        # Reject unexpected mock / non-concrete returns
        if default == "" and not isinstance(value, str):
            return default
        return value
    except Exception:  # noqa: BLE001
        return default


def _branch_commit_subjects(
    git: "GitService | None",
    base: str,
    *,
    max_commits: int,
) -> list[str]:
    if git is None or not isinstance(base, str) or not base:
        return []
    fn = getattr(git, "get_commits_since_ref", None)
    if not callable(fn):
        return []
    try:
        commits = fn(base, max_count=max_commits)
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(commits, (list, tuple)):
        return []
    subjects: list[str] = []
    for c in commits:
        msg = (getattr(c, "message", "") or "").strip()
        if isinstance(msg, str) and msg:
            subjects.append(msg.splitlines()[0].strip())
    return subjects


def _changed_files_vs_base(git: "GitService | None", base: str) -> list[str]:
    if git is None or not isinstance(base, str) or not base:
        return []
    fn = getattr(git, "get_changed_files_vs_ref", None)
    if callable(fn):
        try:
            changes = fn(base)
            if isinstance(changes, (list, tuple)):
                return [
                    c.path.replace("\\", "/")
                    for c in changes
                    if getattr(c, "path", None)
                ]
        except Exception:  # noqa: BLE001
            pass
    # Fallback to default-branch helper
    fn_default = getattr(git, "get_changed_files_vs_default_branch", None)
    if callable(fn_default):
        try:
            changes = fn_default()
            if isinstance(changes, (list, tuple)):
                return [
                    c.path.replace("\\", "/")
                    for c in changes
                    if getattr(c, "path", None)
                ]
        except Exception:  # noqa: BLE001
            return []
    return []


def _working_tree_files(git: "GitService | None") -> list[str]:
    if git is None:
        return []
    fn = getattr(git, "get_working_tree_status", None)
    if not callable(fn):
        return []
    try:
        status = fn()
    except Exception:  # noqa: BLE001
        return []
    if status is None or isinstance(status, (str, int, float, bool)):
        return []
    paths: list[str] = []
    for group_name in (
        "staged_files",
        "modified_files",
        "deleted_files",
        "renamed_files",
    ):
        group = getattr(status, group_name, None)
        if not isinstance(group, (list, tuple)):
            continue
        for item in group:
            path = getattr(item, "path", None) or (str(item) if isinstance(item, str) else None)
            if path and isinstance(path, str):
                paths.append(path.replace("\\", "/"))
    untracked = getattr(status, "untracked_files", None)
    if isinstance(untracked, (list, tuple)):
        for u in untracked:
            if isinstance(u, str) and u:
                paths.append(u.replace("\\", "/"))
    return paths

