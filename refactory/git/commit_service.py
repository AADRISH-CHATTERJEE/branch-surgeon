"""CommitService — local commit inspection via GitPython.

Architectural boundaries:
- Talks only to the local filesystem / ``.git`` directory.
- Never calls GitHub or any network API.
- Independent of ReviewEngine / PromptBuilder / AI Gateway.
- Converts GitPython exceptions into Refactory exceptions before they escape.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from git import NULL_TREE, InvalidGitRepositoryError, NoSuchPathError, Repo
from git.exc import BadName, GitCommandError, GitError as GitPythonError
from git.objects.commit import Commit
from git.objects.util import Actor

from refactory.core.exceptions import CommitNotFound, RefactoryError, RepositoryNotFound
from refactory.git.models import (
    ChangeKind,
    CommitDetail,
    CommitDiff,
    CommitFileChange,
    CommitStatistics,
    CommitSummary,
)

if TYPE_CHECKING:
    from loguru import Logger


_DIFF_CHANGE_MAP = {
    "A": ChangeKind.ADDED,
    "M": ChangeKind.MODIFIED,
    "D": ChangeKind.DELETED,
    "R": ChangeKind.RENAMED,
    "C": ChangeKind.COPIED,
    "T": ChangeKind.TYPE_CHANGED,
}


class CommitService:
    """Local-only commit history and patch inspection."""

    def __init__(self, logger: "Logger", path: Path | str | None = None) -> None:
        self._logger = logger
        self._start_path = Path(path or Path.cwd()).resolve()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_commit(self, hash: str) -> CommitDetail:
        """Resolve ``hash`` (full or abbreviated) to typed commit metadata."""
        commit = self._resolve_commit(hash)
        return self._to_detail(commit)

    def get_recent_commits(self, limit: int = 20) -> list[CommitSummary]:
        """Return up to ``limit`` commits reachable from HEAD (newest first)."""
        if limit < 1:
            return []
        repo = self._open_repo()
        if self._is_empty(repo):
            self._logger.info("Empty repository — no commits")
            return []
        try:
            commits = list(repo.iter_commits(max_count=limit))
        except Exception as exc:  # noqa: BLE001
            raise self._wrap_git_error("Failed to list recent commits", exc) from exc
        return [self._to_summary(commit) for commit in commits]

    def get_commit_diff(self, hash: str) -> CommitDiff:
        """Return the unified patch, per-file changes, and statistics for ``hash``."""
        commit = self._resolve_commit(hash)
        files = self._file_changes(commit)
        patch = self._unified_patch(commit, files)
        stats = self._statistics(commit, files)
        return CommitDiff(sha=commit.hexsha, patch=patch, files=files, statistics=stats)

    def get_commit_files(self, hash: str) -> list[CommitFileChange]:
        """Return changed paths (with patches when available) for ``hash``."""
        commit = self._resolve_commit(hash)
        return self._file_changes(commit)

    def get_commit_statistics(self, hash: str) -> CommitStatistics:
        """Return aggregate insertions / deletions / file count for ``hash``."""
        commit = self._resolve_commit(hash)
        files = self._file_changes(commit)
        return self._statistics(commit, files)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _open_repo(self) -> Repo:
        try:
            repo = Repo(self._start_path, search_parent_directories=True)
        except (InvalidGitRepositoryError, NoSuchPathError) as exc:
            raise RepositoryNotFound(
                f"No Git repository found at or above '{self._start_path}'."
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise self._wrap_git_error("Failed to open Git repository", exc) from exc
        if repo.bare:
            raise RepositoryNotFound(f"Repository at '{self._start_path}' is bare.")
        return repo

    @staticmethod
    def _is_empty(repo: Repo) -> bool:
        try:
            _ = repo.head.commit
            return False
        except (ValueError, GitPythonError, TypeError):
            return True

    def _resolve_commit(self, hash: str) -> Commit:
        repo = self._open_repo()
        if self._is_empty(repo):
            raise CommitNotFound("Repository has no commits.")
        rev = (hash or "").strip()
        if not rev:
            raise CommitNotFound("Commit hash is empty.")
        try:
            commit = repo.commit(rev)
        except (BadName, ValueError, GitCommandError, GitPythonError) as exc:
            raise CommitNotFound(f"Commit '{hash}' not found.") from exc
        except Exception as exc:  # noqa: BLE001
            message = str(exc).lower()
            if "bad" in message or "ambiguous" in message or "unknown revision" in message:
                raise CommitNotFound(f"Commit '{hash}' not found.") from exc
            raise self._wrap_git_error(f"Failed to resolve commit '{hash}'", exc) from exc
        return commit

    def _to_summary(self, commit: Commit) -> CommitSummary:
        author: Actor = commit.author
        return CommitSummary(
            sha=commit.hexsha,
            short_sha=commit.hexsha[:7],
            message=self._subject(commit),
            author_name=author.name or "",
            author_email=author.email or "",
            committed_at=self._committed_at(commit),
            parent_shas=[parent.hexsha for parent in commit.parents],
        )

    def _to_detail(self, commit: Commit) -> CommitDetail:
        author: Actor = commit.author
        parents = [parent.hexsha for parent in commit.parents]
        return CommitDetail(
            sha=commit.hexsha,
            short_sha=commit.hexsha[:7],
            message=(commit.message or "").rstrip(),
            author_name=author.name or "",
            author_email=author.email or "",
            committed_at=self._committed_at(commit),
            parent_shas=parents,
            is_merge=len(parents) > 1,
        )

    @staticmethod
    def _subject(commit: Commit) -> str:
        message = (commit.message or "").strip()
        if "\n" in message:
            message = message.split("\n", 1)[0].strip()
        return message

    @staticmethod
    def _committed_at(commit: Commit) -> datetime:
        committed_at = commit.committed_datetime
        if isinstance(committed_at, datetime):
            if committed_at.tzinfo is None:
                return committed_at.replace(tzinfo=timezone.utc)
            return committed_at
        return datetime.now(timezone.utc)

    def _diff_index(self, commit: Commit):
        """Return DiffIndex of changes introduced by ``commit`` (vs first parent)."""
        try:
            # M=True enables rename/copy detection (GitPython); avoid R=True (reverses sides).
            if commit.parents:
                return commit.parents[0].diff(commit, create_patch=True, M=True)
            # Root commit: compare commit → empty tree; GitPython still marks paths as added.
            return commit.diff(NULL_TREE, create_patch=True, M=True)
        except Exception as exc:  # noqa: BLE001
            raise self._wrap_git_error(
                f"Failed to diff commit '{commit.hexsha[:7]}'",
                exc,
            ) from exc

    def _file_changes(self, commit: Commit) -> list[CommitFileChange]:
        diffs = self._diff_index(commit)
        stats_by_path = self._stats_by_path(commit)
        files: list[CommitFileChange] = []
        for diff in diffs:
            change = self._diff_to_file_change(diff, stats_by_path)
            files.append(change)
        files.sort(key=lambda item: item.path)
        return files

    def _stats_by_path(self, commit: Commit) -> dict[str, tuple[int, int]]:
        try:
            raw = commit.stats.files or {}
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("commit.stats unavailable for {}: {}", commit.hexsha[:7], exc)
            return {}
        result: dict[str, tuple[int, int]] = {}
        for path, values in raw.items():
            insertions = int(values.get("insertions", 0) or 0)
            deletions = int(values.get("deletions", 0) or 0)
            # Rename keys may appear as "old => new".
            if " => " in path:
                path = path.split(" => ", 1)[-1].strip()
            result[path.replace("\\", "/")] = (insertions, deletions)
        return result

    def _diff_to_file_change(
        self,
        diff,
        stats_by_path: dict[str, tuple[int, int]],
    ) -> CommitFileChange:
        kind = self._diff_kind(diff)
        path = (diff.b_path or diff.a_path or "").replace("\\", "/")
        old_path = None
        if kind in {ChangeKind.RENAMED, ChangeKind.COPIED}:
            old_path = (diff.a_path or None)
            if old_path:
                old_path = old_path.replace("\\", "/")
        is_binary = self._is_binary_diff(diff)
        patch = None if is_binary else self._decode_patch(diff.diff)
        insertions, deletions = stats_by_path.get(path, (0, 0))
        if not is_binary and patch and (insertions, deletions) == (0, 0):
            insertions, deletions = self._count_hunk_stats(patch)
        return CommitFileChange(
            path=path,
            kind=kind,
            old_path=old_path,
            insertions=insertions,
            deletions=deletions,
            is_binary=is_binary,
            patch=patch,
        )

    @staticmethod
    def _diff_kind(diff) -> ChangeKind:
        if getattr(diff, "deleted_file", False):
            return ChangeKind.DELETED
        if getattr(diff, "renamed_file", False):
            return ChangeKind.RENAMED
        if getattr(diff, "new_file", False):
            return ChangeKind.ADDED
        change_type = getattr(diff, "change_type", None) or "M"
        return _DIFF_CHANGE_MAP.get(str(change_type)[:1], ChangeKind.UNKNOWN)

    @staticmethod
    def _is_binary_diff(diff) -> bool:
        raw = getattr(diff, "diff", None)
        if isinstance(raw, (bytes, bytearray)):
            if b"Binary files" in raw or b"\x00" in raw:
                return True
        elif isinstance(raw, str) and "Binary files" in raw:
            return True

        for blob in (getattr(diff, "a_blob", None), getattr(diff, "b_blob", None)):
            if blob is None:
                continue
            try:
                sample = blob.data_stream.read(8192)
            except Exception:  # noqa: BLE001
                continue
            if b"\x00" in sample:
                return True
        return False

    @staticmethod
    def _decode_patch(raw: object) -> str | None:
        if raw is None:
            return None
        if isinstance(raw, bytes):
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("utf-8", errors="replace")
        else:
            text = str(raw)
        if not text:
            return None
        if not text.endswith("\n"):
            text += "\n"
        return text

    @staticmethod
    def _count_hunk_stats(patch: str) -> tuple[int, int]:
        insertions = 0
        deletions = 0
        for line in patch.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                continue
            if line.startswith("+"):
                insertions += 1
            elif line.startswith("-"):
                deletions += 1
        return insertions, deletions

    def _unified_patch(self, commit: Commit, files: list[CommitFileChange]) -> str:
        """Assemble a unified diff text from per-file patches (skips binary bodies)."""
        parts: list[str] = []
        for item in files:
            if item.is_binary:
                label = item.path
                if item.old_path:
                    parts.append(
                        f"diff --git a/{item.old_path} b/{item.path}\n"
                        f"Binary files a/{item.old_path} and b/{item.path} differ\n"
                    )
                else:
                    parts.append(
                        f"diff --git a/{label} b/{label}\n"
                        f"Binary files a/{label} and b/{label} differ\n"
                    )
                continue
            if item.patch:
                # GitPython create_patch bodies often omit the diff --git header.
                if not item.patch.lstrip().startswith("diff --git"):
                    old = item.old_path or item.path
                    parts.append(f"diff --git a/{old} b/{item.path}\n")
                parts.append(item.patch if item.patch.endswith("\n") else item.patch + "\n")
        return "".join(parts)

    def _statistics(
        self,
        commit: Commit,
        files: list[CommitFileChange],
    ) -> CommitStatistics:
        try:
            total = commit.stats.total or {}
            insertions = int(total.get("insertions", 0) or 0)
            deletions = int(total.get("deletions", 0) or 0)
            files_changed = int(total.get("files", 0) or 0) or len(files)
            if files_changed or insertions or deletions:
                return CommitStatistics(
                    files_changed=files_changed,
                    insertions=insertions,
                    deletions=deletions,
                )
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("Falling back to per-file stats: {}", exc)

        return CommitStatistics(
            files_changed=len(files),
            insertions=sum(item.insertions for item in files),
            deletions=sum(item.deletions for item in files),
        )

    def _wrap_git_error(self, message: str, exc: Exception) -> RefactoryError:
        self._logger.error("{}: {}", message, exc)
        return RefactoryError(f"{message}: {exc}")
