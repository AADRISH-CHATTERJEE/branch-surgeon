"""BranchSurgeonService — deterministic branch health analysis.

Reuses GitService, CommitService, ImpactAnalysisService,
TestIntelligenceService, DocumentationService, and RepositoryGraphService.
No AI calls. No GitHub. Everything local.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from refactory.core.exceptions import IndexError_
from refactory.documentation.service import DocumentationService
from refactory.git.service import GitService
from refactory.git.commit_service import CommitService
from refactory.graph.service import RepositoryGraphService
from refactory.impact.service import ImpactAnalysisService
from refactory.indexer.service import IndexerService
from refactory.surgeon.models import (
    BranchAnalysis,
    BranchCommitSummary,
    BranchHealth,
    BranchIssue,
    BranchRecommendation,
    BranchSurgeonWorkspace,
    ChangedFileSummary,
    IssueKind,
    IssueSeverity,
    RecommendationType,
    SurgeonBlastRadius,
    SurgeonBranchSummary,
    SurgeonHealthSummary,
    SurgeonMergeConflictRisk,
    SurgeonRecommendationCounts,
    SurgeonReviewSummary,
    SurgeonRulesSummary,
    SurgeonScoreSummary,
    SurgeonTimelineEntry,
)
from refactory.testing.service import TestIntelligenceService

if TYPE_CHECKING:
    from loguru import Logger

    from refactory.company.checker import CompanyRulesChecker
    from refactory.db.query_service import RepositoryQueryService
    from refactory.recommendation.service import RecommendationEngine
    from refactory.recommendation.stats import RecommendationStatsService


# Commit message patterns that signal low quality
_POOR_MSG_RE = re.compile(
    r"^(wip|fix|fixup|temp|tmp|asdf|test|final|again|more|update|changes|"
    r"cleanup|refactor|misc|stuff|work|commit|save|done|todo|hack|quick|"
    r"minor|small|tweaks?|typo|oops|nit|nits|revert|patch|bump|lol)[\s!.,:;]*$",
    re.IGNORECASE,
)

# File patterns that signal security / auth / critical paths
_SECURITY_TOKENS = frozenset(
    {
        "auth", "security", "crypto", "jwt", "password", "oauth",
        "session", "token", "secret", "credential", "login", "permission",
        "role", "acl", "access", "encrypt", "decrypt", "hash", "salt",
    }
)

_RISK_TOKENS = frozenset(
    {
        "config", "settings", "database", "db", "migration", "schema",
        "core", "base", "main", "app", "init", "middleware", "router",
    }
)


class BranchSurgeonService:
    """Analyze a local branch and produce structured health recommendations.

    Never modifies code. Never calls AI or GitHub. Reuses existing services.
    """

    def __init__(
        self,
        logger: "Logger",
        git_service: GitService,
        commit_service: CommitService,
        indexer_service: IndexerService,
        graph_service: RepositoryGraphService,
        impact_analysis_service: ImpactAnalysisService,
        test_intelligence_service: TestIntelligenceService,
        documentation_service: DocumentationService,
        *,
        query_service: "RepositoryQueryService | None" = None,
        recommendation_engine: "RecommendationEngine | None" = None,
        recommendation_stats_service: "RecommendationStatsService | None" = None,
        company_rules_checker: "CompanyRulesChecker | None" = None,
        large_pr_file_threshold: int = 20,
        large_pr_line_threshold: int = 1000,
        hotspot_commit_threshold: int = 3,
        branch_age_stale_days: float = 30.0,
        max_commits: int = 100,
    ) -> None:
        self._logger = logger
        self._git = git_service
        self._commits = commit_service
        self._indexer = indexer_service
        self._graph = graph_service
        self._impact = impact_analysis_service
        self._testing = test_intelligence_service
        self._docs = documentation_service
        self._query = query_service
        self._recommendation_engine = recommendation_engine
        self._recommendation_stats = recommendation_stats_service
        self._company_rules = company_rules_checker
        self._large_pr_files = large_pr_file_threshold
        self._large_pr_lines = large_pr_line_threshold
        self._hotspot_commits = hotspot_commit_threshold
        self._stale_days = branch_age_stale_days
        self._max_commits = max_commits

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compose_workspace(self) -> BranchSurgeonWorkspace:
        """Orchestrate existing services into one Local API snapshot.

        Never invents analysis engines. Always returns a valid workspace
        (empty sections when data is missing).
        """
        workspace = BranchSurgeonWorkspace()
        try:
            info = self._git.get_repository_info()
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Branch Surgeon workspace: git metadata failed: {}", exc)
            workspace.surgery = self._compute_surgery_score(
                overall=0.0,
                critical_recs=0,
                high_recs=0,
                pending_reviews=0,
                rule_failures=0,
                rule_warnings=0,
            )
            return workspace

        branch_name = info.current_branch or ""
        base_branch = info.default_branch or "main"
        root = Path(info.root_path)

        branch_summary = self._compose_branch_summary(info, branch_name, base_branch)
        workspace.branch = branch_summary

        health = self._compose_health(root)
        workspace.health = health

        rec_counts, rec_rows = self._compose_recommendations(root)
        workspace.recommendations = rec_counts

        review_summary = self._compose_reviews(root)
        # Confidence priority: review → recommendation sample (never fabricate 0).
        if review_summary.latest is not None and review_summary.latest.get("confidence") is None:
            for row in rec_rows:
                c = row.get("confidence")
                if isinstance(c, (int, float)):
                    review_summary.latest["confidence"] = float(c)
                    break
        workspace.reviews = review_summary

        rules_summary = self._compose_rules(root, branch_name, base_branch)
        workspace.rules = rules_summary

        workspace.blast_radius = self._compose_blast_radius(root)
        workspace.timeline = self._compose_timeline(root)
        workspace.merge_conflict_risk = self._compose_merge_conflict_risk(
            branch_summary, info
        )
        workspace.surgery = self._compute_surgery_score(
            overall=health.overall,
            critical_recs=rec_counts.critical,
            high_recs=rec_counts.high,
            pending_reviews=review_summary.pending,
            rule_failures=rules_summary.failed,
            rule_warnings=rules_summary.warning_count,
        )
        workspace.surgery_score = workspace.surgery.score
        latest = review_summary.latest or {}
        conf = latest.get("confidence")
        if isinstance(conf, (int, float)):
            # Expose 0–100 percentage for Local API consumers.
            workspace.confidence = round(float(conf) * 100.0, 1) if float(conf) <= 1.0 else float(conf)
        return workspace

    def analyze(self, branch: str | None = None) -> BranchAnalysis:
        """Run all 10 analyzers on ``branch`` (defaults to current branch)."""
        root = self._git.get_root_path()
        repo_info = self._git.get_repository_info()
        current_branch = branch or repo_info.current_branch
        base_branch = repo_info.default_branch or "main"

        self._logger.info(
            "Branch Surgeon: analyzing '{}' vs '{}'", current_branch, base_branch
        )

        commits = self._branch_commits(current_branch, base_branch, root)
        changed_files = self._aggregate_changed_files(commits, root)

        analysis = BranchAnalysis(
            branch=current_branch,
            base_branch=base_branch,
            repository=repo_info.name,
        )
        analysis.commits = commits
        analysis.changed_files = changed_files

        # Run all analyzers — each appends to analysis.issues
        self._check_large_pr(analysis)
        self._check_hotspots(analysis)
        self._check_missing_tests(analysis, root)
        self._check_blast_radius(analysis, root)
        self._check_risk_concentration(analysis)
        self._check_commit_quality(analysis)
        self._check_duplicate_file_edits(analysis)
        self._check_branch_age(analysis)
        self._check_merge_conflict_risk(analysis, root)
        self._check_documentation_drift(analysis, root)

        analysis.recommendations = self._build_recommendations(analysis)
        analysis.health = self._compute_health(analysis, commits, changed_files)

        self._logger.info(
            "Branch Surgeon done — score={}, issues={}",
            analysis.health.score,
            len(analysis.issues),
        )
        return analysis

    # ------------------------------------------------------------------
    # Commit / file collection
    # ------------------------------------------------------------------

    def _branch_commits(
        self,
        branch: str,
        base: str,
        root: Path,
    ) -> list[BranchCommitSummary]:
        """Return commits reachable from branch but not from base (branch-only)."""
        from git import InvalidGitRepositoryError, NoSuchPathError, Repo
        from git.exc import GitError as GitPythonError

        try:
            repo = Repo(root, search_parent_directories=True)
        except (InvalidGitRepositoryError, NoSuchPathError, GitPythonError):
            return []

        try:
            # Resolve base to a commit (local head or origin/base).
            base_commit = self._resolve_ref(repo, base)
        except Exception:  # noqa: BLE001
            # If base not found (single-branch or shallow), fall back to all commits.
            base_commit = None

        try:
            all_commits = list(
                repo.iter_commits(max_count=self._max_commits)
                if base_commit is None
                else repo.iter_commits(rev=f"{base_commit.hexsha}..HEAD", max_count=self._max_commits)
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Could not iterate branch commits: {}", exc)
            all_commits = []

        result: list[BranchCommitSummary] = []
        for commit in all_commits:
            try:
                stats = commit.stats.total
                files_changed = int(stats.get("files", 0))
                insertions = int(stats.get("insertions", 0))
                deletions = int(stats.get("deletions", 0))
            except Exception:  # noqa: BLE001
                files_changed = insertions = deletions = 0

            author = getattr(commit, "author", None)
            author_name = getattr(author, "name", "") or ""
            msg = (commit.message or "").strip().split("\n", 1)[0]

            committed_at = commit.committed_datetime
            if committed_at.tzinfo is None:
                committed_at = committed_at.replace(tzinfo=timezone.utc)

            result.append(
                BranchCommitSummary(
                    sha=commit.hexsha,
                    short_sha=commit.hexsha[:7],
                    message=msg,
                    author=author_name,
                    committed_at=committed_at,
                    files_changed=files_changed,
                    insertions=insertions,
                    deletions=deletions,
                )
            )
        return result

    def _aggregate_changed_files(
        self,
        commits: list[BranchCommitSummary],
        root: Path,
    ) -> list[ChangedFileSummary]:
        """Build per-file aggregates from all branch commits."""
        from git import Repo
        from git.exc import GitError as GitPythonError

        file_data: dict[str, dict] = defaultdict(
            lambda: {"commit_count": 0, "insertions": 0, "deletions": 0}
        )

        try:
            repo = Repo(root, search_parent_directories=True)
        except Exception:  # noqa: BLE001
            return []

        sha_set = {c.sha for c in commits}
        for sha in sha_set:
            try:
                commit = repo.commit(sha)
                for path, stats in commit.stats.files.items():
                    norm = path.replace("\\", "/")
                    file_data[norm]["commit_count"] += 1
                    file_data[norm]["insertions"] += int(stats.get("insertions", 0))
                    file_data[norm]["deletions"] += int(stats.get("deletions", 0))
            except Exception:  # noqa: BLE001
                continue

        result: list[ChangedFileSummary] = []
        for path, data in file_data.items():
            stem = Path(path).stem.lower()
            parts = [p.lower() for p in Path(path).parts]
            is_test = (
                any(t in parts for t in ("tests", "test", "spec", "specs"))
                or stem.startswith("test_")
                or stem.endswith("_test")
                or "conftest" in stem
            )
            is_sec = any(tok in stem or tok in parts for tok in _SECURITY_TOKENS)
            result.append(
                ChangedFileSummary(
                    path=path,
                    commit_count=data["commit_count"],
                    insertions=data["insertions"],
                    deletions=data["deletions"],
                    is_test=is_test,
                    is_security_sensitive=is_sec,
                )
            )
        result.sort(key=lambda f: (-f.commit_count, f.path))
        return result

    # ------------------------------------------------------------------
    # Analyzers
    # ------------------------------------------------------------------

    def _check_large_pr(self, analysis: BranchAnalysis) -> None:
        n_files = len(analysis.changed_files)
        total_lines = sum(
            f.insertions + f.deletions for f in analysis.changed_files
        )
        too_many_files = n_files > self._large_pr_files
        too_many_lines = total_lines > self._large_pr_lines

        if too_many_files or too_many_lines:
            details: list[str] = []
            if too_many_files:
                details.append(f"{n_files} files changed (threshold: {self._large_pr_files})")
            if too_many_lines:
                details.append(f"{total_lines} lines changed (threshold: {self._large_pr_lines})")
            analysis.issues.append(
                BranchIssue(
                    kind=IssueKind.LARGE_PR,
                    severity=IssueSeverity.MEDIUM,
                    title="Large PR",
                    detail="; ".join(details),
                )
            )

    def _check_hotspots(self, analysis: BranchAnalysis) -> None:
        hotspots = [
            f for f in analysis.changed_files
            if f.commit_count >= self._hotspot_commits
        ]
        for f in hotspots:
            analysis.issues.append(
                BranchIssue(
                    kind=IssueKind.HOTSPOT,
                    severity=IssueSeverity.MEDIUM,
                    title=f"Hotspot: {f.path}",
                    detail=(
                        f"{f.path} touched in {f.commit_count} commits on this branch. "
                        "Repeated edits to the same file may signal scope creep or instability."
                    ),
                    files=[f.path],
                )
            )

    def _check_missing_tests(self, analysis: BranchAnalysis, root: Path) -> None:
        production_changed = [
            f.path for f in analysis.changed_files if not f.is_test
            and f.path.endswith(".py")
        ]
        if not production_changed:
            return

        try:
            cache = self._testing._ensure_ready()
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("TI not ready for missing-test check: {}", exc)
            return

        for path in production_changed:
            norm = path.replace("\\", "/").lstrip("./")
            related = cache.coverage.get(norm, [])
            if related:
                continue
            # Also check via find_related_tests quick path
            report = self._testing.find_related_tests(norm)
            if report.tests:
                continue
            analysis.issues.append(
                BranchIssue(
                    kind=IssueKind.MISSING_TESTS,
                    severity=IssueSeverity.MEDIUM,
                    title=f"No tests for {path}",
                    detail=(
                        f"{path} was modified on this branch but has no related tests. "
                        "Add or update tests to maintain coverage."
                    ),
                    files=[path],
                )
            )

    def _check_blast_radius(self, analysis: BranchAnalysis, root: Path) -> None:
        production_changed = [
            f.path for f in analysis.changed_files
            if not f.is_test and f.path.endswith(".py")
        ]
        for path in production_changed:
            try:
                report = self._impact.analyze(path)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("impact skipped for {}: {}", path, exc)
                continue
            direct = len(report.direct_impact)
            if direct >= 5:
                severity = IssueSeverity.HIGH
            elif direct >= 3:
                severity = IssueSeverity.MEDIUM
            else:
                continue
            analysis.issues.append(
                BranchIssue(
                    kind=IssueKind.BLAST_RADIUS,
                    severity=severity,
                    title=f"High blast radius: {path}",
                    detail=(
                        f"{path} has {direct} direct dependent(s). "
                        "Changes here may cascade broadly."
                    ),
                    files=[path] + [i.path for i in report.direct_impact[:5]],
                )
            )

    def _check_risk_concentration(self, analysis: BranchAnalysis) -> None:
        security_files = [
            f.path for f in analysis.changed_files if f.is_security_sensitive
        ]
        if security_files:
            analysis.issues.append(
                BranchIssue(
                    kind=IssueKind.RISK_CONCENTRATION,
                    severity=IssueSeverity.HIGH,
                    title="Security-sensitive files modified",
                    detail=(
                        f"{len(security_files)} security-sensitive file(s) changed: "
                        + ", ".join(security_files[:5])
                    ),
                    files=security_files[:10],
                )
            )

        risk_files = [
            f.path for f in analysis.changed_files
            if not f.is_security_sensitive
            and any(
                tok in Path(f.path).stem.lower() or tok in [p.lower() for p in Path(f.path).parts]
                for tok in _RISK_TOKENS
            )
        ]
        if risk_files:
            analysis.issues.append(
                BranchIssue(
                    kind=IssueKind.RISK_CONCENTRATION,
                    severity=IssueSeverity.MEDIUM,
                    title="Core infrastructure files modified",
                    detail=(
                        f"{len(risk_files)} core/config/database file(s) changed: "
                        + ", ".join(risk_files[:5])
                    ),
                    files=risk_files[:10],
                )
            )

    def _check_commit_quality(self, analysis: BranchAnalysis) -> None:
        poor: list[BranchCommitSummary] = [
            c for c in analysis.commits if _POOR_MSG_RE.match(c.message.strip())
        ]
        if poor:
            analysis.issues.append(
                BranchIssue(
                    kind=IssueKind.POOR_COMMIT_MESSAGE,
                    severity=IssueSeverity.LOW,
                    title=f"{len(poor)} low-quality commit message(s)",
                    detail=(
                        "Commit messages like '"
                        + "', '".join(c.message[:40] for c in poor[:3])
                        + "' are not informative. Consider squashing or rewording."
                    ),
                    commits=[c.short_sha for c in poor],
                )
            )

    def _check_duplicate_file_edits(self, analysis: BranchAnalysis) -> None:
        candidates = [
            f for f in analysis.changed_files
            if f.commit_count >= 3 and not f.is_test
        ]
        if candidates:
            analysis.issues.append(
                BranchIssue(
                    kind=IssueKind.DUPLICATE_FILE_EDITS,
                    severity=IssueSeverity.LOW,
                    title=f"{len(candidates)} file(s) edited across many commits",
                    detail=(
                        "Files like "
                        + ", ".join(f.path for f in candidates[:3])
                        + " appear in 3+ commits. Consider squashing for a cleaner history."
                    ),
                    files=[f.path for f in candidates[:10]],
                )
            )

    def _check_branch_age(self, analysis: BranchAnalysis) -> None:
        if not analysis.commits:
            return
        oldest = min(c.committed_at for c in analysis.commits)
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age_days = (now - oldest).total_seconds() / 86400

        if age_days >= self._stale_days:
            severity = IssueSeverity.HIGH if age_days >= 60 else IssueSeverity.MEDIUM
            analysis.issues.append(
                BranchIssue(
                    kind=IssueKind.BRANCH_AGE,
                    severity=severity,
                    title=f"Branch is {int(age_days)} days old",
                    detail=(
                        f"The oldest commit on this branch is {int(age_days)} days old "
                        f"(threshold: {int(self._stale_days)} days). "
                        "Consider rebasing onto the latest base branch."
                    ),
                )
            )

    def _check_merge_conflict_risk(self, analysis: BranchAnalysis, root: Path) -> None:
        n_files = len(analysis.changed_files)
        n_hotspot = sum(
            1 for f in analysis.changed_files if f.commit_count >= self._hotspot_commits
        )
        n_security = sum(1 for f in analysis.changed_files if f.is_security_sensitive)

        # Heuristic score: more files + hotspots → higher conflict risk
        risk_score = n_files * 1.0 + n_hotspot * 2.0 + n_security * 1.5
        if risk_score >= 20:
            severity = IssueSeverity.HIGH
        elif risk_score >= 8:
            severity = IssueSeverity.MEDIUM
        else:
            severity = IssueSeverity.LOW

        analysis.health.merge_conflict_risk = severity

        if severity in {IssueSeverity.MEDIUM, IssueSeverity.HIGH}:
            analysis.issues.append(
                BranchIssue(
                    kind=IssueKind.MERGE_CONFLICT_RISK,
                    severity=severity,
                    title=f"Merge conflict risk: {severity.value.upper()}",
                    detail=(
                        f"Risk estimate based on {n_files} changed file(s), "
                        f"{n_hotspot} hotspot(s), {n_security} security-sensitive file(s)."
                    ),
                )
            )

    def _check_documentation_drift(self, analysis: BranchAnalysis, root: Path) -> None:
        production_changed = {
            f.path for f in analysis.changed_files
            if not f.is_test and f.path.endswith(".py")
        }
        if not production_changed:
            return

        try:
            stale = self._docs.find_stale_documentation()
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("Docs stale check skipped: {}", exc)
            return

        drifted = [
            item for item in stale
            if (item.related_source or "") in production_changed
        ]
        if drifted:
            analysis.issues.append(
                BranchIssue(
                    kind=IssueKind.DOCUMENTATION_DRIFT,
                    severity=IssueSeverity.LOW,
                    title=f"{len(drifted)} documentation file(s) appear outdated",
                    detail=(
                        "Documentation for changed modules appears stale: "
                        + ", ".join(d.path for d in drifted[:3])
                    ),
                    files=[d.path for d in drifted[:10]],
                )
            )

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------

    def _build_recommendations(self, analysis: BranchAnalysis) -> list[BranchRecommendation]:
        recs: list[BranchRecommendation] = []
        kinds_seen: set[IssueKind] = {i.kind for i in analysis.issues}

        if IssueKind.LARGE_PR in kinds_seen:
            recs.append(BranchRecommendation(
                kind=RecommendationType.SPLIT_PR,
                title="Split into smaller PRs",
                detail=(
                    "This branch touches many files. Consider splitting by feature "
                    "or module to make review easier and reduce risk."
                ),
            ))

        missing_test_files = [
            p for i in analysis.issues
            if i.kind == IssueKind.MISSING_TESTS
            for p in i.files
        ]
        if missing_test_files:
            recs.append(BranchRecommendation(
                kind=RecommendationType.ADD_TESTS,
                title="Add tests for modified production code",
                detail=(
                    f"{len(missing_test_files)} production file(s) changed without test coverage."
                ),
                files=missing_test_files[:10],
            ))

        squash_files = [
            p for i in analysis.issues
            if i.kind in {IssueKind.DUPLICATE_FILE_EDITS, IssueKind.POOR_COMMIT_MESSAGE}
            for p in (i.files or [])
        ]
        if IssueKind.DUPLICATE_FILE_EDITS in kinds_seen or IssueKind.POOR_COMMIT_MESSAGE in kinds_seen:
            poor_shas = [
                sha for i in analysis.issues
                if i.kind == IssueKind.POOR_COMMIT_MESSAGE
                for sha in i.commits
            ]
            recs.append(BranchRecommendation(
                kind=RecommendationType.SQUASH_COMMITS,
                title="Squash or reword commits",
                detail=(
                    "Some commits have low-quality messages or duplicate edits. "
                    "Squash intermediate commits before merging."
                ),
                files=list(dict.fromkeys(squash_files))[:10],
            ))

        if IssueKind.DOCUMENTATION_DRIFT in kinds_seen:
            doc_files = [
                p for i in analysis.issues
                if i.kind == IssueKind.DOCUMENTATION_DRIFT
                for p in i.files
            ]
            recs.append(BranchRecommendation(
                kind=RecommendationType.UPDATE_DOCS,
                title="Update stale documentation",
                detail="Documentation appears outdated relative to changed source files.",
                files=doc_files[:10],
            ))

        if IssueKind.RISK_CONCENTRATION in kinds_seen:
            recs.append(BranchRecommendation(
                kind=RecommendationType.REVIEW_SECURITY,
                title="Request security review",
                detail=(
                    "This branch modifies security-sensitive or core infrastructure files. "
                    "Request an additional review before merging."
                ),
            ))

        if IssueKind.BRANCH_AGE in kinds_seen:
            recs.append(BranchRecommendation(
                kind=RecommendationType.REBASE,
                title="Rebase onto latest base branch",
                detail=(
                    f"This branch is old. Rebase onto '{analysis.base_branch}' "
                    "to reduce merge conflict risk."
                ),
            ))

        return recs

    # ------------------------------------------------------------------
    # Health scoring
    # ------------------------------------------------------------------

    def _compute_health(
        self,
        analysis: BranchAnalysis,
        commits: list[BranchCommitSummary],
        files: list[ChangedFileSummary],
    ) -> BranchHealth:
        score = 100
        severity_penalty = {
            IssueSeverity.LOW: 3,
            IssueSeverity.MEDIUM: 8,
            IssueSeverity.HIGH: 15,
            IssueSeverity.CRITICAL: 25,
        }
        for issue in analysis.issues:
            score -= severity_penalty.get(issue.severity, 5)
        score = max(0, score)

        grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F"

        total_ins = sum(c.insertions for c in commits)
        total_del = sum(c.deletions for c in commits)

        age_days = 0.0
        if commits:
            oldest = min(c.committed_at for c in commits)
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - oldest).total_seconds() / 86400

        has_poor = any(i.kind == IssueKind.POOR_COMMIT_MESSAGE for i in analysis.issues)
        test_gap = any(i.kind == IssueKind.MISSING_TESTS for i in analysis.issues)

        return BranchHealth(
            score=score,
            grade=grade,
            commit_count=len(commits),
            changed_file_count=len(files),
            total_insertions=total_ins,
            total_deletions=total_del,
            branch_age_days=round(age_days, 1),
            merge_conflict_risk=analysis.health.merge_conflict_risk,
            test_coverage_gap=test_gap,
            has_poor_commits=has_poor,
        )

    # ------------------------------------------------------------------
    # Workspace composition helpers (GET /branch-surgeon)
    # ------------------------------------------------------------------

    def _compose_branch_summary(
        self, info: Any, branch_name: str, base_branch: str
    ) -> SurgeonBranchSummary:
        commits: list[Any] = []
        changed: list[Any] = []
        insertions = 0
        deletions = 0
        try:
            commits = list(
                self._git.get_commits_since_ref(base_branch, max_count=self._max_commits)
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("compose branch commits failed: {}", exc)
        try:
            changed = list(self._git.get_changed_files_vs_default_branch())
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("compose changed files failed: {}", exc)
            try:
                changed = list(self._git.get_changed_files_vs_ref(base_branch))
            except Exception:  # noqa: BLE001
                changed = []

        for commit in commits[:50]:
            sha = getattr(commit, "sha", None) or ""
            if not sha:
                continue
            try:
                stats = self._commits.get_commit_statistics(sha)
                insertions += int(getattr(stats, "insertions", 0) or 0)
                deletions += int(getattr(stats, "deletions", 0) or 0)
            except Exception:  # noqa: BLE001
                continue

        return SurgeonBranchSummary(
            name=branch_name,
            base_branch=base_branch,
            head_sha=getattr(info, "head_sha", None),
            repository=getattr(info, "name", "") or "",
            commits=len(commits),
            changed_files=len(changed),
            insertions=insertions,
            deletions=deletions,
        )

    def _compose_health(self, root: Path) -> SurgeonHealthSummary:
        if self._recommendation_engine is None:
            return SurgeonHealthSummary()
        try:
            report = self._recommendation_engine.calculate_health(root)
            scores = report.scores
            return SurgeonHealthSummary(
                overall=float(scores.overall or 0),
                architecture=float(scores.architecture or 0),
                security=float(scores.security or 0),
                testing=float(scores.testing or 0),
                maintainability=float(scores.maintainability or 0),
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("compose health failed: {}", exc)
            return SurgeonHealthSummary()

    def _compose_recommendations(
        self, root: Path
    ) -> tuple[SurgeonRecommendationCounts, list[dict[str, Any]]]:
        """Populate recommendation snapshot from RecommendationStatsService only."""
        rows: list[dict[str, Any]] = []
        root_s = str(root.resolve())
        branch = ""
        try:
            branch = self._git.get_repository_info().current_branch or ""
        except Exception:  # noqa: BLE001
            branch = ""

        if self._recommendation_stats is None:
            self._logger.warning(
                "RecommendationStatsService missing — Branch Surgeon recommendation "
                "counts will be zero (no local aggregation)."
            )
            return SurgeonRecommendationCounts(repo_root=root_s, branch=branch), rows

        try:
            # Always live — never serve a stale in-process cache on the flagship page.
            summary = self._recommendation_stats.get_repository_summary(
                repo_root=root_s,
                branch=branch,
                force_refresh=True,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("compose recommendations failed: {}", exc)
            return SurgeonRecommendationCounts(repo_root=root_s, branch=branch), []

        # Validation: Recommendations page uses the same service (may be cached).
        try:
            page_view = self._recommendation_stats.get_repository_summary(
                repo_root=root_s,
                repository_id=summary.repository_id or None,
                branch=branch,
                force_refresh=False,
            )
            if page_view.total != summary.total or page_view.critical != summary.critical:
                self._logger.error(
                    "Recommendation summary mismatch\n"
                    "Branch Surgeon : {}\n"
                    "Recommendation Page : {}\n"
                    "Repository : {}",
                    summary.total,
                    page_view.total,
                    summary.repository or root_s,
                )
                # Prefer the live recomputed summary and replace cache.
                self._recommendation_stats.invalidate(
                    repository_id=summary.repository_id or None,
                    repo_root=root_s,
                )
        except Exception:  # noqa: BLE001
            pass

        if self._query is not None and summary.repository_id:
            try:
                rows = self._query.get_recommendations(
                    summary.repository_id, limit=20
                ) or []
            except Exception:  # noqa: BLE001
                rows = []

        counts = SurgeonRecommendationCounts(
            total=summary.total,
            critical=summary.critical,
            high=summary.high,
            medium=summary.medium,
            low=summary.low,
            pending=summary.pending,
            resolved=summary.resolved,
            ignored=summary.ignored,
            by_type=dict(summary.by_type),
            last_updated=summary.last_updated,
            repository_id=summary.repository_id,
            repository=summary.repository,
            repo_root=summary.repo_root or root_s,
            branch=summary.branch or branch,
            source=summary.source,
            version=summary.version,
        )
        return counts, rows

    def _compose_reviews(self, root: Path) -> SurgeonReviewSummary:
        if self._query is None:
            return SurgeonReviewSummary()
        repo = self._query.get_repository_by_root(str(root.resolve()))
        if repo is None:
            return SurgeonReviewSummary()
        try:
            reviews = self._query.get_reviews(repo["id"], limit=50) or []
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("compose reviews failed: {}", exc)
            return SurgeonReviewSummary()

        pending = 0
        try:
            runs = self._query.get_analyses(repo["id"], limit=40) or []
            pending = sum(
                1
                for r in runs
                if str(r.get("command", "")).lower() in {"review", "branch_surgeon"}
                and str(r.get("status", "")).lower() in {"running", "pending", "queued"}
            )
        except Exception:  # noqa: BLE001
            pending = 0

        latest = None
        if reviews:
            top = reviews[0]
            conf = top.get("confidence")
            latest = {
                "id": top.get("id"),
                "pr_number": top.get("pr_number"),
                "risk": top.get("risk"),
                "summary": top.get("summary"),
                "created_at": top.get("created_at"),
                "suggestion_count": top.get("suggestion_count"),
                # Preserve null/missing — never coerce to 0 for the meter.
                "confidence": conf if isinstance(conf, (int, float)) else None,
            }
        return SurgeonReviewSummary(
            completed=len(reviews),
            pending=pending,
            latest=latest,
        )

    def _compose_rules(
        self, root: Path, branch_name: str, base_branch: str
    ) -> SurgeonRulesSummary:
        if self._company_rules is None:
            return SurgeonRulesSummary()
        try:
            from refactory.company.context import resolve_gate_context

            ctx = resolve_gate_context(
                self._git,
                branch_name=branch_name,
                base_branch=base_branch,
            )
            result = self._company_rules.check(
                root,
                branch_name=ctx.branch_name,
                commit_message=ctx.commit_message,
                commit_messages=ctx.commit_messages,
                changed_files=ctx.changed_files,
            )
            failed = len(result.blockers)
            warnings = len(result.warnings)
            passed = 1 if failed == 0 else 0
            return SurgeonRulesSummary(
                passed=passed,
                failed=failed,
                warning_count=warnings,
                outcome=result.outcome.value,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("compose rules failed: {}", exc)
            return SurgeonRulesSummary()

    def _compose_blast_radius(self, root: Path) -> SurgeonBlastRadius:
        empty = SurgeonBlastRadius()
        if self._query is None:
            return empty
        repo = self._query.get_repository_by_root(str(root.resolve()))
        if repo is None:
            return empty
        try:
            graph = self._query.get_graph(repo["id"]) or {}
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("compose graph failed: {}", exc)
            return empty

        nodes = graph.get("nodes") or []
        edges = graph.get("edges") or []
        degree: dict[str, int] = {}
        names: dict[str, str] = {}
        types: dict[str, str] = {}
        for n in nodes:
            nid = str(n.get("id") or "")
            if not nid:
                continue
            ntype = str(n.get("type") or n.get("node_type") or "").lower()
            label = str(n.get("name") or n.get("label") or n.get("path") or nid)
            if ntype and ntype not in {"file", "module", ""}:
                continue
            names[nid] = label
            types[nid] = ntype or "file"
            degree[nid] = 0
        for e in edges:
            src = str(e.get("source") or e.get("from_id") or e.get("from") or "")
            dst = str(e.get("target") or e.get("to_id") or e.get("to") or "")
            if src in degree:
                degree[src] += 1
            if dst in degree:
                degree[dst] += 1

        ranked = sorted(degree.items(), key=lambda kv: (-kv[1], names.get(kv[0], kv[0])))
        # Presentation only: prefer file labels; drop module aliases (auth vs auth.py).
        top = self._normalize_file_labels(
            [names[nid] for nid, _ in ranked[:24] if nid in names],
            prefer_types=[types.get(nid) for nid, _ in ranked[:24] if nid in names],
        )
        return SurgeonBlastRadius(
            node_count=int(graph.get("node_count") or len(nodes)),
            edge_count=int(graph.get("edge_count") or len(edges)),
            critical_files=top[:8],
            most_connected=top[:6],
        )

    def _compose_timeline(self, root: Path) -> list[SurgeonTimelineEntry]:
        if self._query is None:
            return []
        repo = self._query.get_repository_by_root(str(root.resolve()))
        if repo is None:
            return []
        entries: list[SurgeonTimelineEntry] = []
        try:
            runs = self._query.get_analyses(repo["id"], limit=30) or []
        except Exception:  # noqa: BLE001
            runs = []
        for run in runs:
            entries.append(
                SurgeonTimelineEntry(
                    id=str(run.get("id") or ""),
                    kind="activity",
                    label=str(run.get("command") or "analysis"),
                    status=str(run.get("status") or ""),
                    at=run.get("created_at"),
                    detail=run.get("summary") or run.get("result_type"),
                )
            )
        try:
            reviews = self._query.get_reviews(repo["id"], limit=10) or []
        except Exception:  # noqa: BLE001
            reviews = []
        for rev in reviews:
            entries.append(
                SurgeonTimelineEntry(
                    id=str(rev.get("id") or ""),
                    kind="review",
                    label=f"review PR #{rev.get('pr_number')}"
                    if rev.get("pr_number") is not None
                    else "review",
                    status=str(rev.get("risk") or "completed"),
                    at=rev.get("created_at"),
                    detail=rev.get("summary"),
                )
            )
        # Newest first; stable tie-break by id; drop duplicate ids.
        seen: set[str] = set()
        deduped: list[SurgeonTimelineEntry] = []
        for e in sorted(
            entries,
            key=lambda x: (x.at or "", x.id or ""),
            reverse=True,
        ):
            key = f"{e.kind}:{e.id}" if e.id else f"{e.kind}:{e.at}:{e.label}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(e)
        return deduped[:40]

    @staticmethod
    def _normalize_file_labels(
        labels: list[str],
        prefer_types: list[str | None] | None = None,
    ) -> list[str]:
        """Collapse module/file aliases for display (auth + auth.py → auth.py)."""
        best: dict[str, tuple[int, str]] = {}
        order: list[str] = []
        for i, raw in enumerate(labels):
            label = (raw or "").replace("\\", "/").strip()
            if not label:
                continue
            base = label.rsplit("/", 1)[-1]
            stem = base.lower().rsplit(".", 1)[0]
            ntype = ""
            if prefer_types and i < len(prefer_types):
                ntype = (prefer_types[i] or "").lower()
            score = (2 if "." in base else 0) + (1 if ntype == "file" else 0)
            display = label
            if "." not in base and ntype == "module":
                display = f"{base}.py"
            if stem not in best:
                order.append(stem)
                best[stem] = (score, display)
            elif score > best[stem][0]:
                best[stem] = (score, display)
        return [best[s][1] for s in order if s in best]

    @staticmethod
    def _compose_merge_conflict_risk(
        branch: SurgeonBranchSummary,
        info: Any,
    ) -> SurgeonMergeConflictRisk:
        """Deterministic merge-conflict risk heuristic (not a git merge simulator).

        Inputs: commits ahead of base, changed file count, dirty working tree.
        Returns level low|medium|high and score in [0.0, 1.0].
        """
        commits = max(0, int(branch.commits or 0))
        changed = max(0, int(branch.changed_files or 0))
        dirty = bool(getattr(info, "is_dirty", False))
        score = min(
            1.0,
            round(
                min(commits, 25) / 50.0
                + min(changed, 40) / 80.0
                + (0.2 if dirty else 0.0)
                + (0.1 if commits >= 10 else 0.0)
                + (0.1 if changed >= 15 else 0.0),
                4,
            ),
        )
        if score >= 0.55:
            level = "high"
        elif score >= 0.28:
            level = "medium"
        else:
            level = "low"
        parts = [
            f"Branch diverges by {commits} commit(s) with {changed} changed file(s)",
        ]
        if dirty:
            parts.append("working tree is dirty")
        reason = "; ".join(parts) + "."
        return SurgeonMergeConflictRisk(level=level, score=score, reason=reason)

    @staticmethod
    def _compute_surgery_score(
        *,
        overall: float,
        critical_recs: int,
        high_recs: int,
        pending_reviews: int,
        rule_failures: int,
        rule_warnings: int,
    ) -> SurgeonScoreSummary:
        """Deterministic Surgery Score (no AI).

        score = clamp(0, 100,
            health.overall
            - min(40, critical_recs * 8)
            - min(21, high_recs * 3)
            - min(10, pending_reviews * 2)
            - min(30, rule_failures * 10)
            - min(10, rule_warnings * 2)
        )

        Grades: >=85 Healthy, >=70 Stable, >=50 Caution, else At Risk.
        """
        penalty = (
            min(40, critical_recs * 8)
            + min(21, high_recs * 3)
            + min(10, pending_reviews * 2)
            + min(30, rule_failures * 10)
            + min(10, rule_warnings * 2)
        )
        raw = float(overall or 0) - penalty
        score = int(max(0, min(100, round(raw))))
        if score >= 85:
            grade = "Healthy"
        elif score >= 70:
            grade = "Stable"
        elif score >= 50:
            grade = "Caution"
        else:
            grade = "At Risk"
        formula = (
            "clamp(0,100, health.overall"
            " - min(40, critical*8) - min(21, high*3)"
            " - min(10, pending_reviews*2)"
            " - min(30, rule_failures*10) - min(10, rule_warnings*2))"
        )
        return SurgeonScoreSummary(score=score, grade=grade, formula=formula)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_ref(repo, ref_name: str):
        """Resolve a branch name to a commit object (local or origin)."""
        if ref_name in repo.heads:
            return repo.heads[ref_name].commit
        origin_ref = f"origin/{ref_name}"
        for ref in repo.refs:
            if ref.name == origin_ref:
                return ref.commit
        return repo.commit(ref_name)
