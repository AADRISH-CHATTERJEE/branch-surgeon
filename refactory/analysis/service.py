"""RepositoryAnalysisService — local repository intelligence (read-only).

Reuses GitService, CommitService, ParserService, IndexerService, and
RepositoryGraphService. Never talks to GitHub or the network.
Independent of ReviewEngine / PromptBuilder / AI Gateway.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from git import InvalidGitRepositoryError, NoSuchPathError, Repo
from git.exc import GitError as GitPythonError

from refactory.analysis.models import (
    ActivityEntry,
    AnalysisStatistics,
    BranchAnalysis,
    BranchInsight,
    ContributorStat,
    FileAuthor,
    FileHistory,
    FileHistoryEvent,
    FileRenameEvent,
    HotspotEntry,
    HotspotReport,
    PathSize,
    RepositoryHealth,
    RepositoryOverview,
)
from refactory.core.exceptions import RefactoryError, RepositoryNotFound
from refactory.git.commit_service import CommitService
from refactory.git.models import ChangeKind, CommitFileChange, CommitSummary
from refactory.git.service import GitService
from refactory.graph.service import RepositoryGraphService
from refactory.indexer.models import RepositoryIndex
from refactory.indexer.service import IndexerService
from refactory.parser.service import ParserService

if TYPE_CHECKING:
    from loguru import Logger


@dataclass
class _FileTouch:
    sha: str
    short_sha: str
    message: str
    author_name: str
    author_email: str
    committed_at: datetime
    kind: ChangeKind
    insertions: int
    deletions: int
    old_path: str | None = None


@dataclass
class _AnalysisCache:
    head_sha: str | None
    root: Path
    commits: list[CommitSummary] = field(default_factory=list)
    files_by_sha: dict[str, list[CommitFileChange]] = field(default_factory=dict)
    touches_by_path: dict[str, list[_FileTouch]] = field(default_factory=dict)
    index: RepositoryIndex | None = None
    tracked_files: list[str] = field(default_factory=list)
    tag_names: list[str] = field(default_factory=list)


class RepositoryAnalysisService:
    """Read-only repository intelligence built on existing local services."""

    def __init__(
        self,
        logger: "Logger",
        git_service: GitService,
        commit_service: CommitService,
        parser_service: ParserService,
        indexer_service: IndexerService,
        graph_service: RepositoryGraphService,
        *,
        history_limit: int = 1000,
        recent_days: int = 30,
        stale_days: int = 90,
        large_file_bytes: int = 1_000_000,
        hotspot_limit: int = 20,
        ignore_dirs: list[str] | None = None,
    ) -> None:
        self._logger = logger
        self._git = git_service
        self._commits = commit_service
        self._parser = parser_service
        self._indexer = indexer_service
        self._graph = graph_service
        self._history_limit = max(1, history_limit)
        self._recent_days = max(1, recent_days)
        self._stale_days = max(1, stale_days)
        self._large_file_bytes = max(1, large_file_bytes)
        self._hotspot_limit = max(1, hotspot_limit)
        self._ignore_dirs = list(ignore_dirs or [])
        self._cache: _AnalysisCache | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_repository(self) -> RepositoryOverview:
        """Build a full repository intelligence snapshot."""
        cache = self._ensure_cache(force=True)
        name, root_path, current_branch, head_sha, remote_url = self._overview_identity(cache)
        statistics = self.get_repository_statistics()
        branches = self.get_branch_information()
        hotspots = self._hotspot_report()
        health = self._health(cache, hotspots)
        recent = self.get_recent_activity(limit=20)
        languages = self.get_repository_languages()
        return RepositoryOverview(
            name=name,
            root_path=root_path,
            current_branch=current_branch,
            head_sha=head_sha,
            remote_url=remote_url,
            statistics=statistics,
            branches=branches,
            hotspots=hotspots,
            health=health,
            recent_activity=recent,
            languages=languages,
        )

    def _overview_identity(
        self,
        cache: _AnalysisCache,
    ) -> tuple[str, str, str, str | None, str | None]:
        try:
            info = self._git.get_repository_info()
            return (
                info.name,
                info.root_path,
                info.current_branch,
                info.head_sha,
                info.remote_url,
            )
        except RefactoryError:
            branch_info = self._git.get_branch_info()
            return (
                cache.root.name,
                str(cache.root),
                branch_info.current_branch,
                cache.head_sha,
                None,
            )

    def get_repository_statistics(self) -> AnalysisStatistics:
        cache = self._ensure_cache()
        root = cache.root
        tracked = cache.tracked_files
        index = cache.index
        ignored = int(index.summary.ignored_file_count) if index else 0
        languages = self.get_repository_languages()

        branch_info = self._git.get_branch_info()
        branch_count = len(branch_info.local_branches)

        contributors = self._contributor_stats(cache.commits)
        largest_files = self._largest_files(root, tracked, limit=10)
        largest_dirs = self._largest_directories(root, tracked, limit=10)

        oldest = cache.commits[-1] if cache.commits else None
        newest = cache.commits[0] if cache.commits else None
        avg = self._average_commits_per_day(cache.commits)

        # Prefer full reachable count when history window is complete.
        commit_count = len(cache.commits)
        if commit_count >= self._history_limit:
            # Window saturated — still report scanned count (documented limit).
            self._logger.debug(
                "Commit history capped at history_limit={}",
                self._history_limit,
            )

        return AnalysisStatistics(
            total_files=len(tracked),
            tracked_files=len(tracked),
            ignored_files=ignored,
            languages=languages,
            branch_count=branch_count,
            tag_count=len(cache.tag_names),
            commit_count=commit_count,
            contributor_count=len(contributors),
            contributors=contributors,
            largest_files=largest_files,
            largest_directories=largest_dirs,
            oldest_commit_sha=oldest.sha if oldest else None,
            oldest_commit_at=oldest.committed_at if oldest else None,
            newest_commit_sha=newest.sha if newest else None,
            newest_commit_at=newest.committed_at if newest else None,
            average_commits_per_day=avg,
        )

    def get_branch_information(self) -> BranchAnalysis:
        cache = self._ensure_cache()
        info = self._git.get_branch_info()
        default = info.default_branch
        insights: list[BranchInsight] = []
        merged: list[str] = []
        stale: list[str] = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._stale_days)

        try:
            repo = self._open_repo(cache.root)
        except RepositoryNotFound:
            return BranchAnalysis(
                active_branch=info.current_branch,
                default_branch=default,
                is_detached=info.is_detached,
            )

        for name in info.local_branches:
            insight = self._branch_insight(repo, name, default=default, active=info.current_branch)
            insights.append(insight)
            if insight.is_merged and name != default:
                merged.append(name)
            if insight.is_stale or (
                insight.last_committed_at is not None and insight.last_committed_at < cutoff
            ):
                insight.is_stale = True
                if name not in stale and name != info.current_branch:
                    stale.append(name)

        insights.sort(key=lambda b: (not b.is_active, b.name))
        return BranchAnalysis(
            active_branch=info.current_branch,
            default_branch=default,
            is_detached=info.is_detached,
            branches=insights,
            merged_branches=sorted(merged),
            stale_branches=sorted(stale),
        )

    def get_hot_files(self, limit: int | None = None) -> list[HotspotEntry]:
        report = self.get_hotspots(limit=limit)
        return report.files

    def get_hotspots(self, limit: int | None = None) -> HotspotReport:
        """Return ranked hotspot files and directories."""
        return self._hotspot_report(limit=limit)

    def get_file_history(self, path: str) -> FileHistory:
        cache = self._ensure_cache()
        norm = self._norm(path)
        aliases = self._path_aliases(norm, cache)
        events: list[FileHistoryEvent] = []
        renames: list[FileRenameEvent] = []
        authors: dict[tuple[str, str], FileAuthor] = {}
        was_deleted = False
        was_restored = False
        seen_deleted = False

        for commit in cache.commits:
            files = cache.files_by_sha.get(commit.sha, [])
            match = self._match_file_change(files, aliases)
            if match is None:
                continue
            if match.kind == ChangeKind.RENAMED and match.old_path:
                renames.append(
                    FileRenameEvent(
                        sha=commit.sha,
                        old_path=self._norm(match.old_path),
                        new_path=self._norm(match.path),
                        committed_at=commit.committed_at,
                    )
                )
                aliases.add(self._norm(match.old_path))
                aliases.add(self._norm(match.path))
            if match.kind == ChangeKind.DELETED:
                was_deleted = True
                seen_deleted = True
            elif seen_deleted and match.kind in {ChangeKind.ADDED, ChangeKind.MODIFIED}:
                was_restored = True

            events.append(
                FileHistoryEvent(
                    sha=commit.sha,
                    short_sha=commit.short_sha,
                    message=commit.message,
                    author_name=commit.author_name,
                    author_email=commit.author_email,
                    committed_at=commit.committed_at,
                    kind=match.kind.value,
                    insertions=match.insertions,
                    deletions=match.deletions,
                )
            )
            key = (commit.author_name, commit.author_email)
            author = authors.get(key)
            if author is None:
                author = FileAuthor(name=commit.author_name, email=commit.author_email)
                authors[key] = author
            author.commits += 1
            author.insertions += match.insertions
            author.deletions += match.deletions

        # Events collected newest-first (commits order); creation is last event.
        creation = events[-1] if events else None
        latest = events[0] if events else None
        exists = (cache.root / norm).is_file() or any(
            (cache.root / alias).is_file() for alias in aliases
        )
        return FileHistory(
            path=norm,
            exists=exists and not (was_deleted and not was_restored and not exists),
            creation_sha=creation.sha if creation else None,
            creation_at=creation.committed_at if creation else None,
            last_modification_sha=latest.sha if latest else None,
            last_modification_at=latest.committed_at if latest else None,
            modification_count=len(events),
            authors=sorted(authors.values(), key=lambda a: (-a.commits, a.email)),
            rename_history=list(reversed(renames)),
            was_deleted=was_deleted,
            was_restored=was_restored,
            events=events,
        )

    def get_file_authors(self, path: str) -> list[FileAuthor]:
        return self.get_file_history(path).authors

    def get_repository_languages(self) -> dict[str, int]:
        cache = self._ensure_cache()
        if cache.index and cache.index.summary.languages:
            return dict(sorted(cache.index.summary.languages.items(), key=lambda kv: (-kv[1], kv[0])))
        counts: dict[str, int] = defaultdict(int)
        for relative in cache.tracked_files:
            lang = self._language_for_path(relative)
            if lang:
                counts[lang] += 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    def get_recent_activity(self, limit: int = 20) -> list[ActivityEntry]:
        cache = self._ensure_cache()
        out: list[ActivityEntry] = []
        for commit in cache.commits[: max(1, limit)]:
            files = cache.files_by_sha.get(commit.sha, [])
            out.append(
                ActivityEntry(
                    sha=commit.sha,
                    short_sha=commit.short_sha,
                    message=commit.message,
                    author_name=commit.author_name,
                    author_email=commit.author_email,
                    committed_at=commit.committed_at,
                    files_changed=len(files),
                )
            )
        return out

    # ------------------------------------------------------------------
    # Cache / Git helpers
    # ------------------------------------------------------------------

    def _ensure_cache(self, *, force: bool = False) -> _AnalysisCache:
        root = self._git.get_root_path()
        head = self._git.get_head_sha()
        if (
            not force
            and self._cache is not None
            and self._cache.head_sha == head
            and self._cache.root == root
        ):
            return self._cache
        self._cache = self._build_cache(root, head)
        return self._cache

    def _build_cache(self, root: Path, head: str | None) -> _AnalysisCache:
        self._logger.info("Building repository analysis cache (limit={})", self._history_limit)
        commits = self._commits.get_recent_commits(limit=self._history_limit)
        files_by_sha: dict[str, list[CommitFileChange]] = {}
        touches: dict[str, list[_FileTouch]] = defaultdict(list)

        for commit in commits:
            try:
                files = self._commits.get_commit_files(commit.sha)
            except RefactoryError as exc:
                self._logger.warning("Skipping commit {}: {}", commit.short_sha, exc)
                files = []
            files_by_sha[commit.sha] = files
            for change in files:
                path = self._norm(change.path)
                touch = _FileTouch(
                    sha=commit.sha,
                    short_sha=commit.short_sha,
                    message=commit.message,
                    author_name=commit.author_name,
                    author_email=commit.author_email,
                    committed_at=commit.committed_at,
                    kind=change.kind,
                    insertions=change.insertions,
                    deletions=change.deletions,
                    old_path=self._norm(change.old_path) if change.old_path else None,
                )
                touches[path].append(touch)

        index = self._load_or_build_index(root)
        tracked = self._list_tracked_files(root)
        tags = self._list_tags(root)

        if index is not None:
            try:
                self._graph.build_graph(index)
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("Graph build skipped: {}", exc)

        return _AnalysisCache(
            head_sha=head,
            root=root,
            commits=commits,
            files_by_sha=files_by_sha,
            touches_by_path=dict(touches),
            index=index,
            tracked_files=tracked,
            tag_names=tags,
        )

    def _load_or_build_index(self, root: Path) -> RepositoryIndex | None:
        try:
            existing = self._indexer.load_index(root)
            if existing is not None:
                return existing
            try:
                meta = self._git.get_repository_metadata()
                name = meta.name
            except RefactoryError:
                name = root.name
            return self._indexer.build_index(root, repository_name=name, force=False)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Indexer unavailable for analysis: {}", exc)
            return None

    def _list_tracked_files(self, root: Path) -> list[str]:
        try:
            repo = self._open_repo(root)
            if self._is_empty(repo):
                return []
            raw = repo.git.ls_files().splitlines()
            return sorted(self._norm(line) for line in raw if line.strip())
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("ls-files failed: {}", exc)
            return []

    def _list_tags(self, root: Path) -> list[str]:
        try:
            repo = self._open_repo(root)
            return sorted(tag.name for tag in repo.tags)
        except Exception:  # noqa: BLE001
            return []

    def _open_repo(self, root: Path) -> Repo:
        try:
            return Repo(root, search_parent_directories=True)
        except (InvalidGitRepositoryError, NoSuchPathError) as exc:
            raise RepositoryNotFound(f"No Git repository found at '{root}'.") from exc
        except Exception as exc:  # noqa: BLE001
            raise RefactoryError(f"Failed to open Git repository: {exc}") from exc

    @staticmethod
    def _is_empty(repo: Repo) -> bool:
        try:
            _ = repo.head.commit
            return False
        except (ValueError, GitPythonError, TypeError):
            return True

    # ------------------------------------------------------------------
    # Branch / hotspot / health
    # ------------------------------------------------------------------

    def _branch_insight(
        self,
        repo: Repo,
        name: str,
        *,
        default: str | None,
        active: str,
    ) -> BranchInsight:
        try:
            commit = repo.heads[name].commit
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("Branch {} unavailable: {}", name, exc)
            return BranchInsight(name=name, is_active=(name == active))

        ahead = behind = 0
        is_merged = False
        if default and default in repo.heads and name != default:
            try:
                ahead = sum(1 for _ in repo.iter_commits(f"{default}..{name}"))
                behind = sum(1 for _ in repo.iter_commits(f"{name}..{default}"))
                is_merged = bool(repo.is_ancestor(commit, repo.heads[default].commit))
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("ahead/behind failed for {}: {}", name, exc)

        author = commit.author
        message = (commit.message or "").strip().split("\n", 1)[0]
        committed_at = commit.committed_datetime
        if committed_at.tzinfo is None:
            committed_at = committed_at.replace(tzinfo=timezone.utc)

        return BranchInsight(
            name=name,
            is_active=(name == active),
            is_merged=is_merged,
            ahead=ahead,
            behind=behind,
            last_commit_sha=commit.hexsha,
            last_commit_message=message,
            last_author=f"{author.name or ''} <{author.email or ''}>".strip(),
            last_committed_at=committed_at,
        )

    def _hotspot_report(self, limit: int | None = None) -> HotspotReport:
        cache = self._ensure_cache()
        top_n = limit or self._hotspot_limit
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._recent_days)

        file_scores: list[HotspotEntry] = []
        dir_agg: dict[str, dict[str, float | int | set]] = defaultdict(
            lambda: {
                "mods": 0,
                "authors": set(),
                "recent": 0,
                "churn": 0,
            }
        )

        for path, touches in cache.touches_by_path.items():
            authors = {(t.author_name, t.author_email) for t in touches}
            recent = sum(1 for t in touches if t.committed_at >= cutoff)
            churn = sum(t.insertions + t.deletions for t in touches)
            mods = len(touches)
            score = (
                mods * 1.0
                + len(authors) * 2.0
                + recent * 3.0
                + min(churn, 500) * 0.02
            )
            entry = HotspotEntry(
                path=path,
                score=round(score, 3),
                modification_count=mods,
                author_count=len(authors),
                recent_modification_count=recent,
                churn=churn,
                is_directory=False,
            )
            file_scores.append(entry)

            parent = str(Path(path).parent).replace("\\", "/")
            if parent in {"", "."}:
                parent = "."
            bucket = dir_agg[parent]
            bucket["mods"] = int(bucket["mods"]) + mods
            authors_set = bucket["authors"]
            assert isinstance(authors_set, set)
            authors_set.update(authors)
            bucket["recent"] = int(bucket["recent"]) + recent
            bucket["churn"] = int(bucket["churn"]) + churn

        file_scores.sort(key=lambda e: (-e.score, e.path))
        directories: list[HotspotEntry] = []
        for dirname, bucket in dir_agg.items():
            authors_set = bucket["authors"]
            assert isinstance(authors_set, set)
            mods = int(bucket["mods"])
            recent = int(bucket["recent"])
            churn = int(bucket["churn"])
            score = mods * 1.0 + len(authors_set) * 1.5 + recent * 2.0
            directories.append(
                HotspotEntry(
                    path=dirname,
                    score=round(score, 3),
                    modification_count=mods,
                    author_count=len(authors_set),
                    recent_modification_count=recent,
                    churn=churn,
                    is_directory=True,
                )
            )
        directories.sort(key=lambda e: (-e.score, e.path))

        recent_files = sorted(
            [e for e in file_scores if e.recent_modification_count > 0],
            key=lambda e: (-e.recent_modification_count, -e.score, e.path),
        )
        multi_author = sorted(
            [e for e in file_scores if e.author_count >= 2],
            key=lambda e: (-e.author_count, -e.score, e.path),
        )
        high_churn = sorted(
            file_scores,
            key=lambda e: (-e.churn, -e.score, e.path),
        )

        return HotspotReport(
            files=file_scores[:top_n],
            directories=directories[:top_n],
            recent_files=recent_files[:top_n],
            multi_author_files=multi_author[:top_n],
            high_churn_files=high_churn[:top_n],
        )

    def _health(self, cache: _AnalysisCache, hotspots: HotspotReport) -> RepositoryHealth:
        root = cache.root
        tracked = cache.tracked_files
        large = [
            item
            for item in self._largest_files(root, tracked, limit=50)
            if item.size_bytes >= self._large_file_bytes
        ]

        todo_count = 0
        fixme_count = 0
        sizes: list[int] = []
        largest_module = None
        largest_module_size = -1
        if cache.index:
            for indexed in cache.index.files:
                tags = [t.upper() for t in indexed.todo_tags]
                todo_count += sum(1 for t in tags if t == "TODO")
                fixme_count += sum(1 for t in tags if t == "FIXME")
                sizes.append(indexed.file_size)
                if indexed.file_size > largest_module_size:
                    largest_module_size = indexed.file_size
                    largest_module = indexed.relative_path

        indexed_count = max(len(cache.index.files) if cache.index else 0, 1)
        todo_density = todo_count / indexed_count
        fixme_density = fixme_count / indexed_count
        avg_size = (sum(sizes) / len(sizes)) if sizes else 0.0

        orphans: list[str] = []
        chain_len = 0
        chain_path: list[str] = []
        try:
            if cache.index is not None:
                orphans = [o.file_path for o in self._graph.orphan_modules()]
                chain_len, chain_path = self._longest_dependency_chain()
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("Health graph metrics skipped: {}", exc)

        dead_dirs = self._dead_directories(root, tracked, cache.index)
        high_churn = [e.path for e in hotspots.high_churn_files[:10]]

        return RepositoryHealth(
            very_large_files=large[:20],
            dead_directories=dead_dirs,
            orphan_modules=orphans,
            high_churn_files=high_churn,
            todo_density=round(todo_density, 4),
            fixme_density=round(fixme_density, 4),
            todo_count=todo_count,
            fixme_count=fixme_count,
            average_file_size=round(avg_size, 2),
            largest_module=largest_module,
            longest_dependency_chain=chain_len,
            longest_dependency_path=chain_path,
        )

    def _longest_dependency_chain(self) -> tuple[int, list[str]]:
        """Approximate longest import chain via DFS with depth cap."""
        from refactory.graph.models import NodeKind

        try:
            graph = self._graph.graph()
        except Exception:  # noqa: BLE001
            return 0, []

        paths = sorted(
            {
                self._norm(node.file_path or "")
                for node in graph.nodes.values()
                if node.kind == NodeKind.FILE and node.file_path
            }
        )
        if not paths:
            return 0, []

        best: list[str] = []
        memo: dict[str, list[str]] = {}

        def dfs(path: str, visiting: set[str]) -> list[str]:
            if path in memo:
                return memo[path]
            if path in visiting:
                return [path]
            visiting.add(path)
            longest = [path]
            try:
                deps = self._graph.dependencies_of(path)
            except Exception:  # noqa: BLE001
                deps = []
            for dep in deps:
                dep_n = self._norm(dep)
                if not dep_n or dep_n == path:
                    continue
                tail = dfs(dep_n, visiting)
                candidate = [path, *[p for p in tail if p != path]]
                if len(candidate) > len(longest):
                    longest = candidate
            visiting.remove(path)
            memo[path] = longest
            return longest

        for start in paths[:200]:
            chain = dfs(start, set())
            if len(chain) > len(best):
                best = chain
        return max(0, len(best) - 1), best

    def _dead_directories(
        self,
        root: Path,
        tracked: list[str],
        index: RepositoryIndex | None,
    ) -> list[str]:
        """Directories that exist on disk but contain no tracked/indexed source."""
        ignore = {d.lower() for d in self._ignore_dirs}
        tracked_dirs = {str(Path(p).parent).replace("\\", "/") for p in tracked}
        tracked_dirs.discard(".")
        indexed_dirs: set[str] = set()
        if index:
            indexed_dirs = {
                str(Path(f.relative_path).parent).replace("\\", "/") for f in index.files
            }
            indexed_dirs.discard(".")

        dead: list[str] = []
        try:
            for path in root.rglob("*"):
                if not path.is_dir():
                    continue
                rel = self._norm(str(path.relative_to(root)))
                if not rel or rel == ".":
                    continue
                if any(part.lower() in ignore for part in Path(rel).parts):
                    continue
                if rel in tracked_dirs or rel in indexed_dirs:
                    continue
                # Only flag empty-of-source dirs that have no tracked children prefix.
                if any(t.startswith(rel + "/") for t in tracked):
                    continue
                dead.append(rel)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("dead directory scan failed: {}", exc)
        return sorted(dead)[:50]

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _norm(path: str) -> str:
        return path.replace("\\", "/").lstrip("./")

    def _path_aliases(self, path: str, cache: _AnalysisCache) -> set[str]:
        aliases = {path}
        changed = True
        while changed:
            changed = False
            for p, touches in cache.touches_by_path.items():
                for touch in touches:
                    if touch.kind != ChangeKind.RENAMED or not touch.old_path:
                        continue
                    new_p = self._norm(p)
                    old_p = self._norm(touch.old_path)
                    if new_p in aliases and old_p not in aliases:
                        aliases.add(old_p)
                        changed = True
                    if old_p in aliases and new_p not in aliases:
                        aliases.add(new_p)
                        changed = True
        return aliases

    def _match_file_change(
        self,
        files: list[CommitFileChange],
        aliases: set[str],
    ) -> CommitFileChange | None:
        for change in files:
            if self._norm(change.path) in aliases:
                return change
            if change.old_path and self._norm(change.old_path) in aliases:
                return change
        return None

    def _contributor_stats(self, commits: list[CommitSummary]) -> list[ContributorStat]:
        counts: dict[tuple[str, str], int] = defaultdict(int)
        for commit in commits:
            counts[(commit.author_name, commit.author_email)] += 1
        stats = [
            ContributorStat(name=name, email=email, commits=count)
            for (name, email), count in counts.items()
        ]
        return sorted(stats, key=lambda c: (-c.commits, c.email))

    def _average_commits_per_day(self, commits: list[CommitSummary]) -> float:
        if len(commits) < 2:
            return float(len(commits))
        newest = commits[0].committed_at
        oldest = commits[-1].committed_at
        span = max((newest - oldest).total_seconds(), 0.0)
        days = max(span / 86400.0, 1.0)
        return round(len(commits) / days, 4)

    def _largest_files(self, root: Path, tracked: list[str], *, limit: int) -> list[PathSize]:
        sizes: list[PathSize] = []
        for relative in tracked:
            path = root / relative
            try:
                size = path.stat().st_size if path.is_file() else 0
            except OSError:
                size = 0
            sizes.append(PathSize(path=relative, size_bytes=size))
        sizes.sort(key=lambda item: (-item.size_bytes, item.path))
        return sizes[:limit]

    def _largest_directories(
        self,
        root: Path,
        tracked: list[str],
        *,
        limit: int,
    ) -> list[PathSize]:
        totals: dict[str, int] = defaultdict(int)
        for relative in tracked:
            parent = str(Path(relative).parent).replace("\\", "/")
            if parent in {"", "."}:
                parent = "."
            path = root / relative
            try:
                size = path.stat().st_size if path.is_file() else 0
            except OSError:
                size = 0
            totals[parent] += size
        items = [PathSize(path=path, size_bytes=size) for path, size in totals.items()]
        items.sort(key=lambda item: (-item.size_bytes, item.path))
        return items[:limit]

    @staticmethod
    def _language_for_path(path: str) -> str | None:
        ext = Path(path).suffix.lower()
        mapping = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".md": "markdown",
            ".json": "json",
            ".yml": "yaml",
            ".yaml": "yaml",
            ".toml": "toml",
            ".css": "css",
            ".html": "html",
            ".sh": "shell",
        }
        return mapping.get(ext)
