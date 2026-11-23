"""TestIntelligenceService — map production code to local tests.

Reuses ParserService, IndexerService, RepositoryGraphService,
ImpactAnalysisService, RepositoryAnalysisService, CodeSearchService,
GitService, and CommitService. Never rebuilds the repository index.
Never calls AI Gateway / network / GitHub.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from refactory.analysis.service import RepositoryAnalysisService
from refactory.codesearch.service import CodeSearchService
from refactory.core.exceptions import IndexError_
from refactory.git.commit_service import CommitService
from refactory.git.service import GitService
from refactory.graph.service import RepositoryGraphService
from refactory.impact.models import RiskLevel
from refactory.impact.service import ImpactAnalysisService
from refactory.indexer.models import IndexedFile, RepositoryIndex, SymbolKind
from refactory.indexer.service import IndexerService
from refactory.parser.service import ParserService
from refactory.testing.models import (
    DuplicateTestGroup,
    ProductionCoverage,
    RelatedTestsReport,
    SlowTestCandidate,
    TestCoverageMap,
    TestFramework,
    TestImpactReport,
    TestMatch,
    TestRiskLevel,
)

if TYPE_CHECKING:
    from loguru import Logger


_TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|testing|spec|specs)(/|$)|(^|/)test_[^/]+\.py$|_test\.py$",
    re.IGNORECASE,
)
_TEST_FUNC_RE = re.compile(r"^test_", re.IGNORECASE)
_TEST_CLASS_RE = re.compile(r"^Test[A-Z_]", re.IGNORECASE)


@dataclass
class _TestCache:
    root: Path
    index_stamp: str
    index: RepositoryIndex
    graph_ready: bool = False
    test_files: list[str] = field(default_factory=list)
    production_files: list[str] = field(default_factory=list)
    # production path -> related test matches
    coverage: dict[str, list[TestMatch]] = field(default_factory=dict)
    # test path -> production paths it appears to cover
    test_targets: dict[str, list[str]] = field(default_factory=dict)
    frameworks: dict[str, TestFramework] = field(default_factory=dict)


class TestIntelligenceService:
    """Local test ↔ production mapping and coverage intelligence."""

    __test__ = False

    def __init__(
        self,
        logger: "Logger",
        git_service: GitService,
        commit_service: CommitService,
        parser_service: ParserService,
        indexer_service: IndexerService,
        graph_service: RepositoryGraphService,
        impact_analysis_service: ImpactAnalysisService,
        repository_analysis_service: RepositoryAnalysisService,
        code_search_service: CodeSearchService,
    ) -> None:
        self._logger = logger
        self._git = git_service
        self._commits = commit_service
        self._parser = parser_service
        self._indexer = indexer_service
        self._graph = graph_service
        self._impact = impact_analysis_service
        self._analysis = repository_analysis_service
        self._search = code_search_service
        self._cache: _TestCache | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_related_tests(self, target: str) -> RelatedTestsReport:
        cache = self._ensure_ready()
        paths, symbols = self._resolve_target(target, cache)
        if not paths and not symbols:
            return RelatedTestsReport(
                target=target.strip(),
                tests=[],
                coverage_confidence=0.0,
                framework_hint=TestFramework.UNKNOWN,
                target_found=False,
                notes=[f"Target '{target.strip()}' was not found."],
            )
        matches: list[TestMatch] = []
        for path in paths:
            matches.extend(self._tests_for_production_path(path, cache))
        for symbol in symbols:
            matches.extend(self.find_tests_for_symbol(symbol).tests)
        matches = self._dedupe_matches(matches)
        confidence = self._aggregate_confidence(matches)
        framework = self._dominant_framework(matches, cache)
        return RelatedTestsReport(
            target=target.strip(),
            tests=matches,
            coverage_confidence=confidence,
            framework_hint=framework,
            target_found=True,
        )

    def find_tests_for_file(self, path: str) -> RelatedTestsReport:
        return self.find_related_tests(path)

    def find_tests_for_symbol(self, symbol: str) -> RelatedTestsReport:
        cache = self._ensure_ready()
        bare = symbol.rsplit(".", 1)[-1]
        matches: list[TestMatch] = []

        # Callers / references that live in test files.
        try:
            for caller in self._graph.callers_of(bare):
                if self._is_test_path(caller):
                    matches.append(
                        TestMatch(
                            path=caller,
                            symbol=bare,
                            framework=cache.frameworks.get(caller, TestFramework.UNKNOWN),
                            confidence=0.9,
                            reasons=["call_graph"],
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("callers_of failed for {}: {}", bare, exc)

        try:
            for ref in self._graph.files_referencing_symbol(bare):
                if self._is_test_path(ref):
                    matches.append(
                        TestMatch(
                            path=ref,
                            symbol=bare,
                            framework=cache.frameworks.get(ref, TestFramework.UNKNOWN),
                            confidence=0.85,
                            reasons=["symbol_reference"],
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("files_referencing_symbol failed for {}: {}", bare, exc)

        # Naming conventions inside test files (test_<symbol>, TestSymbol).
        needle = bare.lower()
        for test_path in cache.test_files:
            indexed = self._file_by_path(cache, test_path)
            if indexed is None:
                continue
            for sym in indexed.symbols:
                name_l = sym.name.lower()
                if name_l == f"test_{needle}" or name_l == f"test{needle}":
                    matches.append(
                        TestMatch(
                            path=test_path,
                            symbol=sym.name,
                            framework=cache.frameworks.get(test_path, TestFramework.UNKNOWN),
                            confidence=0.88,
                            reasons=["naming_convention"],
                        )
                    )
                elif sym.kind == SymbolKind.CLASS and name_l in {
                    f"test{needle}",
                    f"test_{needle}",
                }:
                    matches.append(
                        TestMatch(
                            path=test_path,
                            symbol=sym.name,
                            framework=cache.frameworks.get(test_path, TestFramework.UNKNOWN),
                            confidence=0.8,
                            reasons=["naming_convention"],
                        )
                    )

        # Defining files for the symbol → file-level tests.
        try:
            for def_path in self._graph.where_defined(bare):
                matches.extend(self._tests_for_production_path(self._norm(def_path), cache))
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("where_defined failed for {}: {}", bare, exc)

        matches = self._dedupe_matches(matches)
        return RelatedTestsReport(
            target=symbol.strip(),
            tests=matches,
            coverage_confidence=self._aggregate_confidence(matches),
            framework_hint=self._dominant_framework(matches, cache),
        )

    def find_orphan_tests(self) -> list[TestMatch]:
        cache = self._ensure_ready()
        orphans: list[TestMatch] = []
        for path in cache.test_files:
            if Path(path).name.lower() == "conftest.py":
                continue
            targets = cache.test_targets.get(path, [])
            if targets:
                continue
            orphans.append(
                TestMatch(
                    path=path,
                    framework=cache.frameworks.get(path, TestFramework.UNKNOWN),
                    confidence=0.75,
                    reasons=["no_production_links"],
                )
            )
        return orphans

    def find_uncovered_files(self) -> list[ProductionCoverage]:
        mapping = self.compute_test_coverage_map()
        return [item for item in mapping.production_files if not item.covered]

    def estimate_test_impact(self, target: str) -> TestImpactReport:
        cache = self._ensure_ready()
        related = self.find_related_tests(target)
        impact = self._impact.analyze(target)
        impacted_prod = [
            self._norm(p)
            for p in impact.impacted_files
            if not self._is_test_path(p)
        ]

        recommended = list(related.tests)
        # Expand recommendations via tests covering impacted production files.
        for path in impacted_prod:
            recommended.extend(self._tests_for_production_path(path, cache))
        recommended = self._dedupe_matches(recommended)

        missing: list[str] = []
        for path in impacted_prod:
            if not cache.coverage.get(path):
                missing.append(path)

        coverage_conf = self._aggregate_confidence(recommended)
        if impacted_prod and not recommended:
            coverage_conf = min(coverage_conf, 0.2)

        risk = self._map_skip_risk(impact.risk_level, coverage_conf, missing)
        notes: list[str] = []
        if missing:
            notes.append(f"{len(missing)} impacted production file(s) lack related tests.")
        if impact.in_cycle:
            notes.append("Target participates in an import cycle — prefer broader regression tests.")

        # Light touch on repository analysis / commits for context (no rebuild).
        try:
            _ = self._analysis.get_repository_languages()
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("repository analysis touch skipped: {}", exc)
        try:
            _ = self._commits.get_recent_commits(limit=1)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("recent commits touch skipped: {}", exc)

        return TestImpactReport(
            target=target.strip(),
            recommended_tests=recommended,
            coverage_confidence=coverage_conf,
            risk_if_skipped=risk,
            missing_critical_tests=sorted(set(missing))[:50],
            impacted_production_files=impacted_prod,
            notes=notes,
        )

    def find_duplicate_tests(self) -> list[DuplicateTestGroup]:
        cache = self._ensure_ready()
        by_key: dict[str, list[TestMatch]] = defaultdict(list)

        # Same test function name across multiple files.
        name_files: dict[str, list[str]] = defaultdict(list)
        for path in cache.test_files:
            indexed = self._file_by_path(cache, path)
            if indexed is None:
                continue
            for sym in indexed.symbols:
                if sym.kind in {
                    SymbolKind.FUNCTION,
                    SymbolKind.METHOD,
                    SymbolKind.NESTED_FUNCTION,
                } and _TEST_FUNC_RE.match(sym.name):
                    name_files[sym.name].append(path)

        for name, paths in name_files.items():
            unique = sorted(set(paths))
            if len(unique) < 2:
                continue
            tests = [
                TestMatch(
                    path=p,
                    symbol=name,
                    framework=cache.frameworks.get(p, TestFramework.UNKNOWN),
                    confidence=0.7,
                    reasons=["same_test_name"],
                )
                for p in unique
            ]
            by_key[f"name:{name}"] = tests

        # Multiple tests covering the exact same single production file with high confidence.
        for prod, matches in cache.coverage.items():
            strong = [m for m in matches if m.confidence >= 0.85]
            paths = sorted({m.path for m in strong})
            if len(paths) < 2:
                continue
            key = f"target:{prod}"
            by_key[key] = [
                TestMatch(
                    path=p,
                    framework=cache.frameworks.get(p, TestFramework.UNKNOWN),
                    confidence=0.65,
                    reasons=["same_production_target"],
                )
                for p in paths
            ]

        groups: list[DuplicateTestGroup] = []
        for key, tests in sorted(by_key.items()):
            if len(tests) < 2:
                continue
            groups.append(
                DuplicateTestGroup(
                    key=key,
                    tests=tests,
                    confidence=round(sum(t.confidence for t in tests) / len(tests), 4),
                    reasons=sorted({r for t in tests for r in t.reasons}),
                )
            )
        return groups

    def find_slow_test_candidates(self, *, limit: int = 20) -> list[SlowTestCandidate]:
        cache = self._ensure_ready()
        candidates: list[SlowTestCandidate] = []
        for path in cache.test_files:
            indexed = self._file_by_path(cache, path)
            if indexed is None:
                continue
            import_count = len(indexed.import_references) or len(indexed.imports)
            symbol_count = len(indexed.symbols)
            reasons: list[str] = []
            score = 0.0
            if import_count >= 8:
                score += 2.0 + min(import_count, 40) * 0.05
                reasons.append("many_imports")
            if symbol_count >= 20:
                score += 1.5
                reasons.append("many_symbols")
            lower = path.lower()
            if any(token in lower for token in ("integration", "e2e", "end_to_end", "slow")):
                score += 2.5
                reasons.append("integration_path")
            if path.count("/") >= 3:
                score += 0.5
                reasons.append("deep_nesting")
            # Multi-module coverage breadth.
            targets = cache.test_targets.get(path, [])
            if len(targets) >= 4:
                score += 1.5 + len(targets) * 0.1
                reasons.append("covers_many_modules")
            if score <= 0:
                continue
            candidates.append(
                SlowTestCandidate(
                    path=path,
                    score=round(score, 3),
                    import_count=import_count,
                    symbol_count=symbol_count,
                    reasons=reasons,
                )
            )
        candidates.sort(key=lambda c: (-c.score, c.path))
        return candidates[: max(1, limit)]

    def compute_test_coverage_map(self) -> TestCoverageMap:
        cache = self._ensure_ready()
        production: list[ProductionCoverage] = []
        uncovered_files: list[str] = []
        uncovered_classes: list[str] = []
        uncovered_functions: list[str] = []

        # Precompute symbol names exercised by tests (naming + imports) — O(tests), not O(symbols²).
        exercised: set[str] = set()
        for test_path in cache.test_files:
            indexed_test = self._file_by_path(cache, test_path)
            if indexed_test is None:
                continue
            for sym in indexed_test.symbols:
                name = sym.name
                if _TEST_FUNC_RE.match(name):
                    exercised.add(name[5:].lower() if name.lower().startswith("test_") else name.lower())
                    if name.lower().startswith("test"):
                        exercised.add(name[4:].lstrip("_").lower())
                if _TEST_CLASS_RE.match(name):
                    exercised.add(name[4:].lstrip("_").lower())
            for ref in indexed_test.import_references:
                if ref.symbol:
                    exercised.add(ref.symbol.lower())

        for path in cache.production_files:
            tests = cache.coverage.get(path, [])
            covered = bool(tests)
            conf = self._aggregate_confidence(tests)
            production.append(
                ProductionCoverage(
                    path=path,
                    kind="file",
                    tests=tests,
                    covered=covered,
                    coverage_confidence=conf,
                )
            )
            if not covered:
                uncovered_files.append(path)

            indexed = self._file_by_path(cache, path)
            if indexed is None:
                continue
            file_covered = covered
            for sym in indexed.symbols:
                if sym.kind == SymbolKind.CLASS:
                    if sym.name.lower() not in exercised and not file_covered:
                        uncovered_classes.append(f"{path}::{sym.name}")
                elif sym.kind in {
                    SymbolKind.FUNCTION,
                    SymbolKind.METHOD,
                    SymbolKind.NESTED_FUNCTION,
                }:
                    if sym.name.startswith("_") and not sym.name.startswith("__"):
                        continue
                    if sym.name.lower() not in exercised and not file_covered:
                        uncovered_functions.append(f"{path}::{sym.name}")

        multi = [
            path
            for path, targets in cache.test_targets.items()
            if len(set(targets)) >= 2
        ]
        orphans = [m.path for m in self.find_orphan_tests()]
        duplicates = self.find_duplicate_tests()
        covered_count = sum(1 for item in production if item.covered)
        ratio = (covered_count / len(production)) if production else 0.0

        return TestCoverageMap(
            production_files=production,
            test_files=list(cache.test_files),
            uncovered_files=uncovered_files,
            uncovered_classes=uncovered_classes[:200],
            uncovered_functions=uncovered_functions[:400],
            multi_module_tests=sorted(multi),
            orphan_tests=orphans,
            duplicate_groups=duplicates,
            coverage_ratio=round(ratio, 4),
        )

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------

    def _tests_for_production_path(self, path: str, cache: _TestCache) -> list[TestMatch]:
        path = self._norm(path)
        if path in cache.coverage:
            return list(cache.coverage[path])
        return []

    def _build_coverage(self, cache: _TestCache) -> None:
        coverage: dict[str, list[TestMatch]] = defaultdict(list)
        test_targets: dict[str, list[str]] = defaultdict(list)

        for test_path in cache.test_files:
            framework = cache.frameworks.get(test_path, TestFramework.UNKNOWN)
            indexed = self._file_by_path(cache, test_path)
            linked: set[str] = set()

            # Graph imports: production files imported by this test.
            try:
                for dep in self._graph.dependencies_of(test_path):
                    dep_n = self._norm(dep)
                    if not self._is_test_path(dep_n):
                        linked.add(dep_n)
                        coverage[dep_n].append(
                            TestMatch(
                                path=test_path,
                                framework=framework,
                                confidence=0.92,
                                reasons=["imports"],
                            )
                        )
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("dependencies_of failed for {}: {}", test_path, exc)

            # Index import references (aliases / from-imports).
            if indexed is not None:
                for ref in indexed.import_references:
                    target = self._module_to_path(ref.target_module, cache)
                    if target and not self._is_test_path(target):
                        linked.add(target)
                        coverage[target].append(
                            TestMatch(
                                path=test_path,
                                symbol=ref.symbol,
                                framework=framework,
                                confidence=0.9,
                                reasons=["import_reference"],
                            )
                        )

            # Naming + directory conventions.
            for prod in cache.production_files:
                score, reasons = self._naming_score(prod, test_path)
                if score <= 0:
                    continue
                linked.add(prod)
                coverage[prod].append(
                    TestMatch(
                        path=test_path,
                        framework=framework,
                        confidence=score,
                        reasons=reasons,
                    )
                )

            # Semantic neighbors via CodeSearchService (local embeddings if present).
            try:
                related = self._search.find_related(test_path, top_k=6)
                for hit in related.hits:
                    prod = self._norm(hit.file)
                    if self._is_test_path(prod) or prod not in cache.production_files:
                        continue
                    linked.add(prod)
                    coverage[prod].append(
                        TestMatch(
                            path=test_path,
                            symbol=hit.symbol or None,
                            framework=framework,
                            confidence=min(0.7, max(0.35, hit.score)),
                            reasons=["semantic_similarity"],
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("semantic related skipped for {}: {}", test_path, exc)

            test_targets[test_path] = sorted(linked)

        # Reverse: production files that are imported BY tests (who_imports).
        for prod in cache.production_files:
            try:
                for importer in self._graph.reverse_dependencies(prod):
                    imp = self._norm(importer)
                    if not self._is_test_path(imp):
                        continue
                    coverage[prod].append(
                        TestMatch(
                            path=imp,
                            framework=cache.frameworks.get(imp, TestFramework.UNKNOWN),
                            confidence=0.93,
                            reasons=["imported_by_test"],
                        )
                    )
                    if prod not in test_targets[imp]:
                        test_targets[imp].append(prod)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("reverse_dependencies failed for {}: {}", prod, exc)

        cache.coverage = {
            path: self._dedupe_matches(matches) for path, matches in coverage.items()
        }
        cache.test_targets = {path: sorted(set(targets)) for path, targets in test_targets.items()}

    def _naming_score(self, production: str, test_path: str) -> tuple[float, list[str]]:
        prod = Path(production)
        test = Path(test_path)
        stem = prod.stem.lower()
        test_stem = test.stem.lower()
        reasons: list[str] = []
        score = 0.0

        candidates = {
            f"test_{stem}",
            f"{stem}_test",
            f"test{stem}",
        }
        if test_stem in candidates:
            score = 0.86
            reasons.append("naming_convention")

        # Directory mirroring: auth.py ↔ tests/test_auth.py or tests/unit/auth/test_auth.py
        prod_parts = [p.lower() for p in prod.parts[:-1]]
        test_parts = [p.lower() for p in test.parts]
        if stem and stem in test_stem and any(p in {"tests", "test", "testing"} for p in test_parts):
            score = max(score, 0.7)
            reasons.append("directory_structure")
        if prod_parts and any(part in test_parts for part in prod_parts if part not in {"src", "lib"}):
            if stem in test_stem:
                score = max(score, 0.72)
                reasons.append("mirrored_package")
        return score, sorted(set(reasons))

    def _module_to_path(self, module: str, cache: _TestCache) -> str | None:
        needle = (module or "").removesuffix(".py").replace(".", "/")
        if not needle:
            return None
        candidates = [
            p
            for p in cache.production_files
            if p == f"{needle}.py" or p.endswith(f"/{needle}.py") or Path(p).stem == Path(needle).name
        ]
        if len(candidates) == 1:
            return candidates[0]
        exact = f"{needle}.py"
        if exact in cache.production_files:
            return exact
        return None

    # ------------------------------------------------------------------
    # Cache / classification
    # ------------------------------------------------------------------

    def _ensure_ready(self) -> _TestCache:
        root = self._git.get_root_path()
        index = self._load_index_only(root)
        stamp = (
            f"{index.summary.timestamp.isoformat()}|"
            f"{index.summary.total_indexed_files}|"
            f"{len(index.symbols)}|"
            f"{len(index.file_hashes)}"
        )
        if (
            self._cache is not None
            and self._cache.root == root
            and self._cache.index_stamp == stamp
            and self._cache.graph_ready
        ):
            return self._cache

        self._graph.build_graph(index)
        _ = self._parser.supported_languages()

        test_files: list[str] = []
        production_files: list[str] = []
        frameworks: dict[str, TestFramework] = {}
        for indexed in index.files:
            path = self._norm(indexed.relative_path)
            if self._is_test_path(path) or self._looks_like_test_module(indexed):
                test_files.append(path)
                frameworks[path] = self._detect_framework(indexed, path)
            else:
                production_files.append(path)

        cache = _TestCache(
            root=root,
            index_stamp=stamp,
            index=index,
            graph_ready=True,
            test_files=sorted(set(test_files)),
            production_files=sorted(set(production_files)),
            frameworks=frameworks,
        )
        self._build_coverage(cache)
        self._cache = cache
        self._logger.info(
            "Test intelligence ready — {} production / {} test file(s)",
            len(cache.production_files),
            len(cache.test_files),
        )
        return cache

    def _load_index_only(self, root: Path) -> RepositoryIndex:
        existing = self._indexer.load_index(root)
        if existing is not None:
            return existing
        last = self._indexer.get_last_index()
        if last is not None:
            return last
        raise IndexError_(
            "No cached repository index found. Run `refactory index` first "
            "(TestIntelligenceService never rebuilds the repository)."
        )

    def _resolve_target(self, target: str, cache: _TestCache) -> tuple[list[str], list[str]]:
        text = (target or "").strip()
        if not text:
            return [], []
        norm = self._norm(text)
        if "/" in norm or "\\" in text or norm.endswith(".py"):
            if norm in cache.production_files or norm in cache.test_files:
                return [norm], []
            node = self._graph.find_file(norm)
            if node and node.file_path:
                return [self._norm(node.file_path)], []
            # Basename unique match against indexed files.
            name = Path(norm).name
            matches = [
                p
                for p in (cache.production_files + cache.test_files)
                if p == name or p.endswith("/" + name)
            ]
            if len(matches) == 1:
                return matches, []
            return [], []

        parent, name = self._split_qualified(text)
        paths: list[str] = []
        try:
            for match in self._graph.find_symbol(name):
                if parent and (match.parent_name or "").lower() != parent.lower():
                    continue
                if match.file_path:
                    paths.append(self._norm(match.file_path))
        except Exception:  # noqa: BLE001
            pass
        if not paths:
            return [], []
        symbols = [f"{parent}.{name}"] if parent else [name]
        return sorted(set(paths)), symbols

    @staticmethod
    def _is_test_path(path: str) -> bool:
        return bool(_TEST_PATH_RE.search(path.replace("\\", "/")))

    def _looks_like_test_module(self, indexed: IndexedFile) -> bool:
        names = [s.name for s in indexed.symbols]
        if any(_TEST_FUNC_RE.match(n) for n in names):
            return True
        if any(_TEST_CLASS_RE.match(n) for n in names):
            return True
        return False

    def _detect_framework(self, indexed: IndexedFile, path: str) -> TestFramework:
        imports = " ".join(indexed.imports).lower()
        for ref in indexed.import_references:
            imports += f" {ref.target_module}".lower()
        text = imports + " " + path.lower()
        if "pytest" in text:
            return TestFramework.PYTEST
        if "unittest" in text:
            return TestFramework.UNITTEST
        # Path heuristics.
        if "tests/" in path.replace("\\", "/") or path.startswith("test_"):
            return TestFramework.PYTEST
        return TestFramework.UNKNOWN

    def _file_by_path(self, cache: _TestCache, path: str) -> IndexedFile | None:
        path = self._norm(path)
        for indexed in cache.index.files:
            if self._norm(indexed.relative_path) == path:
                return indexed
        return None

    @staticmethod
    def _dedupe_matches(matches: list[TestMatch]) -> list[TestMatch]:
        best: dict[tuple[str, str | None], TestMatch] = {}
        for match in matches:
            key = (match.path, match.symbol)
            existing = best.get(key)
            if existing is None or match.confidence > existing.confidence:
                if existing is not None:
                    match = match.model_copy(
                        update={"reasons": sorted(set(existing.reasons + match.reasons))}
                    )
                best[key] = match
        return sorted(best.values(), key=lambda m: (-m.confidence, m.path, m.symbol or ""))

    @staticmethod
    def _aggregate_confidence(matches: list[TestMatch]) -> float:
        if not matches:
            return 0.0
        top = sorted((m.confidence for m in matches), reverse=True)[:3]
        return round(sum(top) / len(top), 4)

    @staticmethod
    def _dominant_framework(matches: list[TestMatch], cache: _TestCache) -> TestFramework:
        counts: dict[TestFramework, int] = defaultdict(int)
        for match in matches:
            fw = match.framework
            if fw == TestFramework.UNKNOWN:
                fw = cache.frameworks.get(match.path, TestFramework.UNKNOWN)
            counts[fw] += 1
        if not counts:
            return TestFramework.UNKNOWN
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].value))[0][0]

    @staticmethod
    def _map_skip_risk(
        impact_risk: RiskLevel,
        coverage_confidence: float,
        missing: list[str],
    ) -> TestRiskLevel:
        if coverage_confidence >= 0.85 and not missing:
            return TestRiskLevel.LOW
        if impact_risk == RiskLevel.CRITICAL or (missing and coverage_confidence < 0.4):
            return TestRiskLevel.CRITICAL
        if impact_risk == RiskLevel.HIGH or len(missing) >= 3:
            return TestRiskLevel.HIGH
        if impact_risk == RiskLevel.MEDIUM or coverage_confidence < 0.6:
            return TestRiskLevel.MEDIUM
        return TestRiskLevel.LOW

    @staticmethod
    def _split_qualified(symbol: str) -> tuple[str | None, str]:
        text = (symbol or "").strip()
        if "." in text and not text.endswith(".py"):
            parent, name = text.rsplit(".", 1)
            if parent and name:
                return parent, name
        return None, text

    @staticmethod
    def _norm(path: str) -> str:
        return path.replace("\\", "/").lstrip("./")
