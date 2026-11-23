"""GitService — local Git repository inspection via GitPython.

Architectural boundaries:
- Talks only to the local filesystem / `.git` directory.
- Never calls GitHub, Gemini, parsers, embeddings, or indexers.
- Converts GitPython exceptions into Refactory exceptions before they escape.
- Prefers GitPython object APIs over shelling out to the `git` binary.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from git import InvalidGitRepositoryError, NoSuchPathError, Repo
from git.exc import GitError as GitPythonError
from git.objects.commit import Commit
from git.objects.util import Actor

from refactory.core.exceptions import RefactoryError, RepositoryNotFound
from refactory.git.models import (
    BranchInfo,
    ChangeKind,
    ChangedPath,
    GitCommitInfo,
    GitRepositoryInfo,
    WorkingFilePreview,
    WorkingTreeStatus,
)
from refactory.review.models import Repository

# Max bytes for Local API file preview (Monaco / text viewer).
FILE_PREVIEW_MAX_BYTES = 1_048_576

if TYPE_CHECKING:
    from loguru import Logger


_GITHUB_SSH = re.compile(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$")
_GITHUB_HTTPS = re.compile(
    r"^https?://(?:www\.)?github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)

_DIFF_CHANGE_MAP = {
    "A": ChangeKind.ADDED,
    "M": ChangeKind.MODIFIED,
    "D": ChangeKind.DELETED,
    "R": ChangeKind.RENAMED,
    "C": ChangeKind.COPIED,
    "T": ChangeKind.TYPE_CHANGED,
}


class GitService:
    """Local-only Git operations against an explicit root or process CWD."""

    def __init__(
        self,
        logger: "Logger",
        path: Path | str | None = None,
        *,
        allow_parent_discovery: bool | None = None,
    ) -> None:
        self._logger = logger
        # Explicit path (API / container) should pass allow_parent_discovery=False.
        # CLI discovery from a nested working directory keeps parent walk enabled.
        self._start_path = Path(path or Path.cwd()).resolve()
        self._allow_parent_discovery = (
            True if allow_parent_discovery is None else allow_parent_discovery
        )

    # ------------------------------------------------------------------
    # Port methods (ReviewEngine contract)
    # ------------------------------------------------------------------

    def require_repository(self) -> Repository:
        """Verify a Git repository exists (walking parents) and return metadata."""
        return self.get_repository_metadata()

    def get_repository_metadata(self) -> Repository:
        """Return repository name, root, branch, HEAD, remote, and default branch."""
        info = self.get_repository_info()
        return Repository(
            name=info.name,
            root_path=info.root_path,
            current_branch=info.current_branch,
            remote_url=info.remote_url,
            default_branch=info.default_branch,
            owner=info.owner,
            full_name=info.full_name,
            head_sha=info.head_sha,
        )

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def is_git_repository(self) -> bool:
        """Return True if the start path is inside a Git working tree."""
        try:
            self._open_repo()
            return True
        except RepositoryNotFound:
            return False

    def repository_exists(self) -> bool:
        """Alias for :meth:`is_git_repository`."""
        return self.is_git_repository()

    def repository_root(self) -> Path:
        """Return the repository root (walks parents until `.git` is found)."""
        return self.get_root_path()

    def is_clean_working_tree(self) -> bool:
        """Return True when there are no staged, unstaged, or untracked changes."""
        status = self.get_working_tree_status()
        if status.is_dirty:
            self._logger.info("Working tree dirty")
            self._logger.info("Modified files: {}", len(status.modified_files))
        else:
            self._logger.info("Working tree clean")
        return not status.is_dirty

    def has_remote_origin(self) -> bool:
        """Return True when a remote named `origin` is configured."""
        repo = self._open_repo()
        found = self._has_origin(repo)
        if found:
            self._logger.info("Remote origin found")
        else:
            self._logger.info("Remote: None")
        return found

    def is_detached_head(self) -> bool:
        """Return True when HEAD does not point at a branch."""
        repo = self._open_repo()
        try:
            return bool(repo.head.is_detached)
        except Exception as exc:  # noqa: BLE001
            raise self._wrap_git_error("Failed to inspect HEAD state", exc) from exc

    # ------------------------------------------------------------------
    # Repository information
    # ------------------------------------------------------------------

    def get_repository_info(self) -> GitRepositoryInfo:
        """Collect a typed snapshot of local repository state."""
        repo = self._open_repo()
        root = Path(repo.working_tree_dir or self._start_path).resolve()
        remote_url = self._remote_origin_url(repo)
        owner, name = self._parse_identity(remote_url, fallback_name=root.name)
        current_branch, is_detached = self._current_branch(repo)
        default_branch = self._default_branch(repo)
        commit = self._commit_info(repo)
        working_tree = self._working_tree_status(repo)
        local_branches, remote_branches = self._list_branches(repo)

        info = GitRepositoryInfo(
            root_path=str(root),
            name=name,
            current_branch=current_branch,
            head_sha=commit.sha if commit else None,
            commit=commit,
            remote_url=remote_url,
            default_branch=default_branch,
            is_dirty=working_tree.is_dirty,
            is_detached=is_detached,
            owner=owner,
            full_name=f"{owner}/{name}" if owner else name,
            local_branches=local_branches,
            remote_branches=remote_branches,
            working_tree=working_tree,
        )

        log = self._logger.bind(repository=info.name or info.root_path)
        log.info("Repository detected")
        log.info("Repository root: {}", info.root_path)
        log.info("Current branch: {}", info.current_branch)
        if info.is_dirty:
            log.info("Working tree dirty")
            log.info("Modified files: {}", len(working_tree.modified_files))
        else:
            log.info("Working tree clean")
        log.info("Remote: {}", info.remote_url or "None")
        return info

    def get_root_path(self) -> Path:
        repo = self._open_repo()
        return Path(repo.working_tree_dir or self._start_path).resolve()

    def get_repository_name(self) -> str:
        return self.get_repository_info().name

    def get_current_branch(self) -> str:
        repo = self._open_repo()
        branch, _ = self._current_branch(repo)
        return branch

    def get_head_sha(self) -> str | None:
        repo = self._open_repo()
        commit = self._commit_info(repo)
        return commit.sha if commit else None

    # ------------------------------------------------------------------
    # Working-tree file ops (used by PatchService — never call git from controllers)
    # ------------------------------------------------------------------

    def resolve_workdir_path(self, relative: str) -> Path | None:
        """Resolve a repo-relative path; returns None if it escapes the root."""
        from refactory.git.paths import safe_repo_relative_path

        return safe_repo_relative_path(self.get_root_path(), relative)

    def read_working_file(self, relative: str) -> str | None:
        """Read a UTF-8 working-tree file; None if missing/unreadable/unsafe."""
        path = self.resolve_workdir_path(relative)
        if path is None or not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def preview_working_file(
        self,
        relative: str,
        *,
        max_bytes: int = FILE_PREVIEW_MAX_BYTES,
    ) -> WorkingFilePreview:
        """Safely preview a text file for the Local API (size + binary guards)."""
        cleaned = (relative or "").replace("\\", "/").strip().lstrip("/")
        if not cleaned:
            return WorkingFilePreview(
                status="not_found",
                path="",
                message="File path is required",
            )

        path = self.resolve_workdir_path(cleaned)
        if path is None:
            return WorkingFilePreview(
                status="unsafe",
                path=cleaned,
                message="Path escapes the repository root",
            )
        if not path.is_file():
            return WorkingFilePreview(
                status="not_found",
                path=cleaned,
                message="File not found",
            )

        try:
            size = path.stat().st_size
        except OSError as exc:
            return WorkingFilePreview(
                status="error",
                path=cleaned,
                message=str(exc),
            )

        if size > max_bytes:
            return WorkingFilePreview(
                status="too_large",
                path=cleaned,
                size=size,
                language=self.language_for_path(cleaned),
                message="File too large to preview",
            )

        try:
            raw = path.read_bytes()
        except OSError as exc:
            return WorkingFilePreview(
                status="error",
                path=cleaned,
                size=size,
                message=str(exc),
            )

        if b"\x00" in raw[:8192]:
            return WorkingFilePreview(
                status="binary",
                path=cleaned,
                size=size,
                language=self.language_for_path(cleaned),
                message="Binary file cannot be previewed",
            )

        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            return WorkingFilePreview(
                status="binary",
                path=cleaned,
                size=size,
                language=self.language_for_path(cleaned),
                message="Binary file cannot be previewed",
            )

        root = self.get_root_path()
        try:
            rel = str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            rel = cleaned

        return WorkingFilePreview(
            status="ok",
            path=rel,
            size=size,
            content=content,
            language=self.language_for_path(rel),
            sha=hashlib.sha256(raw).hexdigest(),
            truncated=False,
        )

    @staticmethod
    def language_for_path(path: str) -> str:
        """Map a file extension to a Monaco / highlight language id."""
        ext = Path(path).suffix.lower()
        mapping = {
            ".py": "python",
            ".js": "javascript",
            ".jsx": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".json": "json",
            ".yml": "yaml",
            ".yaml": "yaml",
            ".md": "markdown",
            ".css": "css",
            ".html": "html",
            ".htm": "html",
            ".sh": "shell",
            ".bash": "shell",
            ".toml": "toml",
            ".rs": "rust",
            ".go": "go",
            ".java": "java",
            ".sql": "sql",
            ".xml": "xml",
            ".txt": "plaintext",
        }
        return mapping.get(ext, "plaintext")

    def find_content_mismatches(self, expected: dict[str, str]) -> list[str]:
        """Return relative paths whose disk content differs from ``expected``."""
        mismatches: list[str] = []
        for rel, baseline in expected.items():
            current = self.read_working_file(rel)
            if current is None:
                mismatches.append(rel)
                continue
            if self._normalize_text(current) != self._normalize_text(baseline):
                mismatches.append(rel)
        return mismatches

    def target_files_are_dirty(self, relatives: list[str]) -> list[str]:
        """Return target paths that appear as unstaged/staged changes in git status."""
        status = self.get_working_tree_status()
        dirty: set[str] = set()
        for group in (
            status.modified_files,
            status.staged_files,
            status.deleted_files,
        ):
            for item in group:
                path = getattr(item, "path", None) or str(item)
                dirty.add(str(path).replace("\\", "/"))
        for u in status.untracked_files:
            dirty.add(str(u).replace("\\", "/"))
        return [r for r in relatives if r.replace("\\", "/") in dirty]

    def has_unmerged_paths(self) -> bool:
        """True when the index has unresolved merge conflicts."""
        try:
            repo = self._open_repo()
            unmerged = repo.index.unmerged_blobs()
            return bool(unmerged)
        except Exception:  # noqa: BLE001
            return False

    def write_working_files(self, files: dict[str, str]) -> list[str]:
        """Write full file contents into the working tree. Returns written relatives."""
        written: list[str] = []
        for rel, content in files.items():
            path = self.resolve_workdir_path(rel)
            if path is None:
                raise OSError(f"Unsafe path: {rel}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            written.append(rel.replace("\\", "/"))
        return written

    def restore_working_files(self, originals: dict[str, str]) -> None:
        """Best-effort restore of previous file contents (rollback)."""
        for rel, content in originals.items():
            path = self.resolve_workdir_path(rel)
            if path is None:
                continue
            try:
                path.write_text(content, encoding="utf-8")
            except OSError:
                pass

    @staticmethod
    def _normalize_text(text: str) -> str:
        return text.replace("\r\n", "\n").replace("\r", "\n")

    def get_current_commit(self) -> GitCommitInfo | None:
        """Return HEAD commit message, author, and timestamp."""
        repo = self._open_repo()
        return self._commit_info(repo)

    def get_remote_origin_url(self) -> str | None:
        repo = self._open_repo()
        return self._remote_origin_url(repo)

    def get_default_branch(self) -> str | None:
        repo = self._open_repo()
        return self._default_branch(repo)

    def has_uncommitted_changes(self) -> bool:
        return not self.is_clean_working_tree()

    def get_branch_info(self) -> BranchInfo:
        """Return current / default / local / remote-tracking branch names."""
        repo = self._open_repo()
        current_branch, is_detached = self._current_branch(repo)
        local_branches, remote_branches = self._list_branches(repo)
        return BranchInfo(
            current_branch=current_branch,
            is_detached=is_detached,
            default_branch=self._default_branch(repo),
            local_branches=local_branches,
            remote_branches=remote_branches,
        )

    def get_local_branches(self) -> list[str]:
        return self.get_branch_info().local_branches

    def get_remote_branches(self) -> list[str]:
        """Return remote-tracking branch names (local refs only — no network)."""
        return self.get_branch_info().remote_branches

    # ------------------------------------------------------------------
    # Working tree status
    # ------------------------------------------------------------------

    def get_working_tree_status(self) -> WorkingTreeStatus:
        repo = self._open_repo()
        return self._working_tree_status(repo)

    def get_modified_files(self) -> list[ChangedPath]:
        return self.get_working_tree_status().modified_files

    def get_deleted_files(self) -> list[ChangedPath]:
        return self.get_working_tree_status().deleted_files

    def get_renamed_files(self) -> list[ChangedPath]:
        return self.get_working_tree_status().renamed_files

    def get_staged_files(self) -> list[ChangedPath]:
        """Return staged paths as typed models."""
        return self.get_working_tree_status().staged_files

    def get_untracked_files(self) -> list[str]:
        return self.get_working_tree_status().untracked_files

    def get_changed_file_count(self) -> int:
        return self.get_working_tree_status().changed_file_count

    def get_changed_files_vs_ref(self, ref: str) -> list[ChangedPath]:
        """Return files that differ between HEAD and ``ref`` (branch/commit tip)."""
        if not ref:
            return []
        repo = self._open_repo()
        try:
            base_commit = self._resolve_ref_commit(repo, ref)
            head_commit = repo.head.commit
        except RefactoryError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._wrap_git_error(f"Failed to resolve commits for diff vs '{ref}'", exc) from exc

        if base_commit.hexsha == head_commit.hexsha:
            self._logger.info("No committed changes vs '{}'", ref)
            return []

        try:
            diffs = base_commit.diff(head_commit, M=True)
        except Exception as exc:  # noqa: BLE001
            raise self._wrap_git_error(f"Failed to diff against '{ref}'", exc) from exc

        changes = [self._diff_to_changed_path(diff, staged=False) for diff in diffs]
        self._logger.info("Found {} file(s) changed vs '{}'", len(changes), ref)
        return changes

    def get_changed_files_vs_default_branch(self) -> list[ChangedPath]:
        """Return files that differ between HEAD and the default branch (three-dot)."""
        repo = self._open_repo()
        default_branch = self._default_branch(repo)
        if not default_branch:
            self._logger.warning("Default branch unavailable; cannot compute changed files")
            return []
        base_ref = self.resolve_diff_base_ref(default_branch)
        return self.get_changed_files_three_dot(base_ref, "HEAD")

    def resolve_diff_base_ref(self, branch_name: str) -> str:
        """Return a locally resolvable ref for ``branch_name`` (prefer origin/ when needed)."""
        if not branch_name or not str(branch_name).strip():
            raise RefactoryError("Unable to resolve PR base branch: empty branch name.")
        name = str(branch_name).strip()
        repo = self._open_repo()
        if name in repo.heads:
            return name
        if any(ref.name == name for ref in repo.refs):
            return name
        origin_ref = name if name.startswith("origin/") else f"origin/{name}"
        if any(ref.name == origin_ref for ref in repo.refs):
            return origin_ref
        try:
            repo.commit(name)
            return name
        except Exception as exc:  # noqa: BLE001
            raise RefactoryError(
                f"Unable to resolve PR base branch '{name}'. "
                f"Ensure a local branch or origin/{name.removeprefix('origin/')} exists."
            ) from exc

    def get_changed_files_three_dot(
        self, base: str, head: str = "HEAD"
    ) -> list[ChangedPath]:
        """Return files in the three-dot range ``base...head`` (merge-base semantics).

        Compares committed tips only — never the working tree.
        """
        if not base:
            return []
        repo = self._open_repo()
        try:
            base_ref = self.resolve_diff_base_ref(base)
            base_commit = repo.commit(base_ref)

            if not head or head == "HEAD":
                head_commit = repo.head.commit
                head_label = "HEAD"
            else:
                head_commit = self._resolve_ref_commit(repo, head)
                head_label = head
        except RefactoryError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._wrap_git_error(
                f"Failed to resolve commits for three-dot diff {base}...{head}",
                exc,
            ) from exc

        if base_commit.hexsha == head_commit.hexsha:
            self._logger.info("No committed changes for {}...{}", base_ref, head_label)
            return []

        try:
            merge_bases = repo.merge_base(base_commit, head_commit)
            if merge_bases:
                diffs = merge_bases[0].diff(head_commit, M=True)
            else:
                diffs = base_commit.diff(head_commit, M=True)
        except Exception as exc:  # noqa: BLE001
            raise self._wrap_git_error(
                f"Failed three-dot diff {base_ref}...{head_label}",
                exc,
            ) from exc

        changes = [self._diff_to_changed_path(diff, staged=False) for diff in diffs]
        self._logger.info(
            "Found {} file(s) changed for {}...{}",
            len(changes),
            base_ref,
            head_label,
        )
        return changes

    def get_unified_diff_three_dot(self, base: str, head: str = "HEAD") -> str:
        """Unified diff for ``base...head`` (committed tips only)."""
        repo = self._open_repo()
        base_ref = self.resolve_diff_base_ref(base)
        head_ref = "HEAD" if not head or head == "HEAD" else head
        if head_ref != "HEAD":
            # Validate head resolves before shelling out
            self._resolve_ref_commit(repo, head_ref)
        try:
            diff_text = repo.git.diff(f"{base_ref}...{head_ref}")
        except Exception as exc:  # noqa: BLE001
            raise self._wrap_git_error(
                f"Failed to generate unified diff {base_ref}...{head_ref}",
                exc,
            ) from exc
        text = diff_text if isinstance(diff_text, str) else str(diff_text or "")
        if text and not text.endswith("\n"):
            text += "\n"
        self._logger.info(
            "Unified diff {}...{} — {} byte(s)",
            base_ref,
            head_ref,
            len(text.encode("utf-8")),
        )
        return text

    def get_commits_since_ref(
        self, ref: str, *, max_count: int = 50
    ) -> list[GitCommitInfo]:
        """Return commits reachable from HEAD but not from ``ref`` (newest first).

        Falls back to ``[HEAD]`` when ``ref`` cannot be resolved.
        """
        if max_count < 1:
            return []
        repo = self._open_repo()
        try:
            base_commit = self._resolve_ref_commit(repo, ref) if ref else None
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("Could not resolve ref '{}': {}; using HEAD only", ref, exc)
            base_commit = None

        try:
            if base_commit is None:
                commits = list(repo.iter_commits(max_count=1))
            else:
                commits = list(
                    repo.iter_commits(
                        rev=f"{base_commit.hexsha}..HEAD",
                        max_count=max_count,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Could not iterate commits since '{}': {}", ref, exc)
            return []

        result: list[GitCommitInfo] = []
        for commit in commits:
            author = commit.author
            message = (commit.message or "").strip()
            if "\n" in message:
                message = message.split("\n", 1)[0].strip()
            committed_at = commit.committed_datetime
            if committed_at is not None and committed_at.tzinfo is None:
                committed_at = committed_at.replace(tzinfo=timezone.utc)
            result.append(
                GitCommitInfo(
                    sha=commit.hexsha,
                    short_sha=commit.hexsha[:7],
                    message=message,
                    author_name=(author.name or "") if author else "",
                    author_email=(author.email or "") if author else "",
                    committed_at=committed_at
                    if isinstance(committed_at, datetime)
                    else datetime.now(timezone.utc),
                )
            )
        return result

    def get_unified_diff_vs_default_branch(self) -> str:
        """Return the unified git diff between the default branch and HEAD.

        Uses a three-dot comparison (``default...HEAD``) so the patch is relative
        to the merge base with the default branch. Working tree is never included.
        """
        repo = self._open_repo()
        default_branch = self._default_branch(repo)
        if not default_branch:
            self._logger.warning("Default branch unavailable; cannot compute unified diff")
            return ""
        return self.get_unified_diff_three_dot(default_branch, "HEAD")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _open_repo(self) -> Repo:
        """Open the Git repo at `_start_path` (optionally walking parents for CLI)."""
        try:
            repo = Repo(
                self._start_path,
                search_parent_directories=self._allow_parent_discovery,
            )
        except (InvalidGitRepositoryError, NoSuchPathError) as exc:
            where = "at or above" if self._allow_parent_discovery else "at"
            raise RepositoryNotFound(
                f"No Git repository found {where} '{self._start_path}'."
            ) from exc
        except Exception as exc:  # noqa: BLE001 — never leak GitPython/OS errors
            raise self._wrap_git_error("Failed to open Git repository", exc) from exc

        if repo.bare:
            raise RepositoryNotFound(f"Repository at '{self._start_path}' is bare.")

        if not self._allow_parent_discovery:
            working = Path(repo.working_tree_dir or self._start_path).resolve()
            if working != self._start_path:
                raise RepositoryNotFound(
                    f"Git working tree {working} does not match requested root "
                    f"{self._start_path}."
                )
        return repo

    def _working_tree_status(self, repo: Repo) -> WorkingTreeStatus:
        try:
            # HEAD → working tree. Use M=True for rename detection (not R — R reverses sides).
            try:
                unstaged = list(repo.head.commit.diff(None, M=True))
            except (GitPythonError, ValueError):
                unstaged = list(repo.index.diff(None, M=True))

            try:
                staged = list(repo.index.diff("HEAD", M=True))
            except (GitPythonError, ValueError):
                staged = []
            untracked = list(repo.untracked_files)
        except Exception as exc:  # noqa: BLE001
            raise self._wrap_git_error("Failed to inspect working tree status", exc) from exc

        modified: list[ChangedPath] = []
        deleted: list[ChangedPath] = []
        renamed: list[ChangedPath] = []

        for diff in unstaged:
            change = self._classify_unstaged_diff(diff)
            if change.kind == ChangeKind.DELETED:
                deleted.append(change)
            elif change.kind == ChangeKind.RENAMED:
                renamed.append(change)
            else:
                modified.append(change)

        staged_files = [self._diff_to_changed_path(diff, staged=True) for diff in staged]
        for change in staged_files:
            if change.kind == ChangeKind.RENAMED and change.path not in {
                item.path for item in renamed
            }:
                renamed.append(change)

        is_dirty = bool(unstaged or staged or untracked)
        paths = {
            *[item.path for item in modified],
            *[item.path for item in deleted],
            *[item.path for item in renamed],
            *[item.path for item in staged_files],
            *untracked,
        }
        ahead, behind = self._ahead_behind(repo)

        return WorkingTreeStatus(
            is_dirty=is_dirty,
            modified_files=modified,
            deleted_files=deleted,
            renamed_files=renamed,
            staged_files=staged_files,
            untracked_files=untracked,
            changed_file_count=len(paths),
            ahead=ahead,
            behind=behind,
        )

    def _ahead_behind(self, repo: Repo) -> tuple[int | None, int | None]:
        """Return (ahead, behind) vs upstream when a tracking branch exists."""
        try:
            if repo.head.is_detached:
                return None, None
            branch = repo.active_branch
            tracking = branch.tracking_branch()
            if tracking is None:
                return None, None
            ahead = sum(1 for _ in repo.iter_commits(f"{tracking.name}..{branch.name}"))
            behind = sum(1 for _ in repo.iter_commits(f"{branch.name}..{tracking.name}"))
            return ahead, behind
        except Exception:  # noqa: BLE001
            return None, None

    def _classify_unstaged_diff(self, diff) -> ChangedPath:
        """Classify an unstaged working-tree diff into a ChangedPath."""
        change = self._diff_to_changed_path(diff, staged=False)
        if getattr(diff, "deleted_file", False) or change.kind == ChangeKind.DELETED:
            path = diff.a_path or diff.b_path or change.path
            return ChangedPath(path=path, kind=ChangeKind.DELETED, staged=False)
        if getattr(diff, "renamed_file", False) or change.kind == ChangeKind.RENAMED:
            return change.model_copy(update={"kind": ChangeKind.RENAMED})
        # Working-tree modifications often have a_blob set and b_blob unset.
        if change.kind == ChangeKind.UNKNOWN:
            return change.model_copy(update={"kind": ChangeKind.MODIFIED})
        return change

    def _commit_info(self, repo: Repo) -> GitCommitInfo | None:
        try:
            commit: Commit = repo.head.commit
        except (ValueError, GitPythonError):
            return None

        author: Actor = commit.author
        message = (commit.message or "").strip()
        if "\n" in message:
            message = message.split("\n", 1)[0].strip()

        committed_at = commit.committed_datetime
        if committed_at.tzinfo is None:
            committed_at = committed_at.replace(tzinfo=timezone.utc)

        return GitCommitInfo(
            sha=commit.hexsha,
            short_sha=commit.hexsha[:7],
            message=message,
            author_name=author.name or "",
            author_email=author.email or "",
            committed_at=committed_at if isinstance(committed_at, datetime) else datetime.now(timezone.utc),
        )

    def _remote_origin_url(self, repo: Repo) -> str | None:
        try:
            if not self._has_origin(repo):
                return None
            urls = list(repo.remotes.origin.urls)
            return urls[0] if urls else None
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Unable to read remote origin: {}", exc)
            return None

    @staticmethod
    def _has_origin(repo: Repo) -> bool:
        return "origin" in {remote.name for remote in repo.remotes}

    def _current_branch(self, repo: Repo) -> tuple[str, bool]:
        try:
            if repo.head.is_detached:
                sha = repo.head.commit.hexsha[:8]
                label = f"HEAD (detached @ {sha})"
                self._logger.info("Detached HEAD at {}", sha)
                return label, True
            return repo.active_branch.name, False
        except Exception as exc:  # noqa: BLE001
            raise RepositoryNotFound(
                f"Unable to determine current branch at '{self._start_path}'."
            ) from exc

    def _default_branch(self, repo: Repo) -> str | None:
        # Prefer canonical main/master tips over origin/HEAD (which may point at a
        # feature branch after a shallow/partial clone).
        try:
            ref_names = {ref.name for ref in repo.refs}
        except Exception:  # noqa: BLE001
            ref_names = set()

        for candidate in ("main", "master"):
            if candidate in {branch.name for branch in repo.heads}:
                return candidate
            if f"origin/{candidate}" in ref_names:
                return candidate

        # origin/HEAD symbolic ref when it names a real tip
        try:
            if self._has_origin(repo):
                try:
                    origin_head = repo.remotes.origin.refs["HEAD"]
                    reference = getattr(origin_head, "reference", None)
                    if reference is not None:
                        name = reference.name  # e.g. origin/main
                        return name.rsplit("/", 1)[-1]
                except (IndexError, KeyError, AttributeError):
                    pass
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("origin default-branch probe failed: {}", exc)

        try:
            if not repo.head.is_detached:
                return repo.active_branch.name
        except Exception:  # noqa: BLE001
            pass
        return None

    def _list_branches(self, repo: Repo) -> tuple[list[str], list[str]]:
        try:
            local_branches = sorted(branch.name for branch in repo.heads)
            remote_branches: list[str] = []
            for remote in repo.remotes:
                for ref in remote.refs:
                    # Skip symbolic origin/HEAD
                    if ref.name.endswith("/HEAD"):
                        continue
                    remote_branches.append(ref.name)
            return local_branches, sorted(set(remote_branches))
        except Exception as exc:  # noqa: BLE001
            raise self._wrap_git_error("Failed to list branches", exc) from exc

    def _resolve_ref_commit(self, repo: Repo, branch_name: str) -> Commit:
        try:
            if branch_name in repo.heads:
                return repo.heads[branch_name].commit
            origin_ref = f"origin/{branch_name}"
            for ref in repo.refs:
                if ref.name == origin_ref:
                    return ref.commit
            return repo.commit(branch_name)
        except Exception as exc:  # noqa: BLE001
            raise self._wrap_git_error(
                f"Could not resolve default branch '{branch_name}'",
                exc,
            ) from exc

    @staticmethod
    def _diff_to_changed_path(diff, *, staged: bool) -> ChangedPath:
        if getattr(diff, "deleted_file", False):
            kind = ChangeKind.DELETED
        elif getattr(diff, "renamed_file", False):
            kind = ChangeKind.RENAMED
        elif getattr(diff, "new_file", False):
            kind = ChangeKind.ADDED
        else:
            change_type = getattr(diff, "change_type", None) or "M"
            kind = _DIFF_CHANGE_MAP.get(str(change_type)[:1], ChangeKind.UNKNOWN)

        path = diff.b_path or diff.a_path or ""
        old_path = diff.a_path if kind in {ChangeKind.RENAMED, ChangeKind.COPIED} else None
        if staged and kind == ChangeKind.UNKNOWN:
            kind = ChangeKind.STAGED
        return ChangedPath(path=path, kind=kind, old_path=old_path, staged=staged)

    @staticmethod
    def _parse_identity(remote_url: str | None, *, fallback_name: str) -> tuple[str | None, str]:
        if not remote_url:
            return None, fallback_name
        for pattern in (_GITHUB_SSH, _GITHUB_HTTPS):
            match = pattern.match(remote_url.strip())
            if match:
                return match.group("owner"), match.group("repo")
        parsed = urlparse(remote_url)
        if parsed.path:
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2:
                return parts[-2], parts[-1].removesuffix(".git")
        return None, fallback_name

    def _wrap_git_error(self, message: str, exc: Exception) -> RefactoryError:
        self._logger.error("{}: {}", message, exc)
        return RefactoryError(f"{message}: {exc}")
