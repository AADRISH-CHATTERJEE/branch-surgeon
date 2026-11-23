"""Repository root resolution and validation for the Local API."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from git import InvalidGitRepositoryError, NoSuchPathError, Repo

from refactory.core.exceptions import RepositoryNotFound

RepoRootSource = Literal[
    "x-repo-root",
    "query.root",
    "configured",
    "Path.cwd()",
]


def configured_repository_root() -> Path | None:
    """Return ``REFACTORY_REPO_ROOT`` from settings when set."""
    try:
        from refactory.core.config import get_settings

        raw = getattr(get_settings(), "repository_root", None)
    except Exception:  # noqa: BLE001
        return None
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return Path(text).expanduser().resolve()


def choose_repo_root(
    *,
    x_repo_root: str | None,
    query_root: str | None,
) -> tuple[Path, RepoRootSource]:
    """Pick a candidate root using Phase 10.11.5C priority order."""
    if x_repo_root and str(x_repo_root).strip():
        return Path(str(x_repo_root).strip()).expanduser().resolve(), "x-repo-root"
    if query_root and str(query_root).strip():
        return Path(str(query_root).strip()).expanduser().resolve(), "query.root"
    configured = configured_repository_root()
    if configured is not None:
        return configured, "configured"
    return Path.cwd().resolve(), "Path.cwd()"


def validate_repository_root(path: Path) -> Path:
    """Ensure ``path`` is a usable Git working tree with a resolvable HEAD.

    Requires ``path`` itself to be the repository root (``.git`` present).
    Does **not** walk parent directories — avoids silently attaching to a
    monorepo when the UI intended a nested demo checkout.
    Never falls back to demo-repo or any other path.
    """
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise RepositoryNotFound(
            f"Repository root does not exist: {resolved}."
        )
    if not resolved.is_dir():
        raise RepositoryNotFound(
            f"Repository root is not a directory: {resolved}."
        )
    if not os_access_readable(resolved):
        raise RepositoryNotFound(
            f"Repository root is not readable: {resolved}."
        )
    if not (resolved / ".git").exists():
        raise RepositoryNotFound(
            f"Directory is not a Git repository: {resolved}."
        )

    try:
        repo = Repo(str(resolved), search_parent_directories=False)
    except (InvalidGitRepositoryError, NoSuchPathError) as exc:
        raise RepositoryNotFound(
            f"Directory is not a Git repository: {resolved} ({exc})."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise RepositoryNotFound(
            f"Directory is not a Git repository: {resolved} ({exc})."
        ) from exc

    if repo.bare:
        raise RepositoryNotFound(f"Repository at {resolved} is bare.")

    working = Path(repo.working_tree_dir or resolved).resolve()
    if working != resolved:
        raise RepositoryNotFound(
            f"Git working tree {working} does not match requested root {resolved}."
        )

    try:
        _ = repo.head.commit
    except Exception as exc:  # noqa: BLE001
        raise RepositoryNotFound(
            f"Unable to determine HEAD commit: {resolved} ({exc}). "
            "Create an initial commit or select a different repository."
        ) from exc

    try:
        if repo.head.is_detached:
            _ = repo.head.commit.hexsha
        else:
            _ = repo.active_branch.name
    except Exception as exc:  # noqa: BLE001
        raise RepositoryNotFound(
            f"Unable to determine current branch: {resolved} ({exc})."
        ) from exc

    return resolved


def os_access_readable(path: Path) -> bool:
    """True when the directory can be listed."""
    try:
        next(path.iterdir(), None)
        return True
    except OSError:
        return False
