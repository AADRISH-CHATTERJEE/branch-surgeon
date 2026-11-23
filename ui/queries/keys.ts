/** Hierarchical React Query keys — always include repoRoot for cache isolation. */

export const queryKeys = {
  all: ["refactory"] as const,
  health: (apiBase: string) => [...queryKeys.all, "health", apiBase] as const,
  repo: (repoRoot: string) => [...queryKeys.all, "repo", repoRoot] as const,
  repository: (repoRoot: string) => [...queryKeys.repo(repoRoot), "repository"] as const,
  repositoryStatus: (repoRoot: string) =>
    [...queryKeys.repo(repoRoot), "status"] as const,
  repositoryHealth: (repoRoot: string) =>
    [...queryKeys.repo(repoRoot), "health"] as const,
  branchSurgeon: (repoRoot: string) =>
    [...queryKeys.repo(repoRoot), "branchSurgeon"] as const,
  files: (repoRoot: string, params?: Record<string, unknown>) =>
    [...queryKeys.repo(repoRoot), "files", params ?? {}] as const,
  fileContent: (repoRoot: string, path: string) =>
    [...queryKeys.repo(repoRoot), "fileContent", path] as const,
  symbols: (repoRoot: string, params?: Record<string, unknown>) =>
    [...queryKeys.repo(repoRoot), "symbols", params ?? {}] as const,
  imports: (repoRoot: string, params?: Record<string, unknown>) =>
    [...queryKeys.repo(repoRoot), "imports", params ?? {}] as const,
  /** Shared reviews list cache (canonical fetch limit applied in the hook). */
  reviews: (repoRoot: string) => [...queryKeys.repo(repoRoot), "reviews", "list"] as const,
  review: (repoRoot: string, id: string) =>
    [...queryKeys.repo(repoRoot), "review", id] as const,
  /**
   * Shared recommendations list cache.
   * Limit is NOT part of the key — hooks fetch a canonical page and `select`-slice.
   * Optional `status` remains part of the key when filtering server-side.
   */
  recommendations: (repoRoot: string, status?: string | null) =>
    [...queryKeys.repo(repoRoot), "recommendations", "list", status ?? "all"] as const,
  /** Canonical repository totals — RecommendationStatsService only. */
  recommendationStats: (repoRoot: string) =>
    [...queryKeys.repo(repoRoot), "recommendations", "stats"] as const,
  recommendationPatches: (repoRoot: string, recommendationId: string) =>
    [...queryKeys.repo(repoRoot), "recommendations", recommendationId, "patches"] as const,
  graphSummary: (repoRoot: string) => [...queryKeys.repo(repoRoot), "graph"] as const,
  graphFull: (repoRoot: string) => [...queryKeys.repo(repoRoot), "graph", "full"] as const,
  graphNode: (repoRoot: string, id: string) =>
    [...queryKeys.repo(repoRoot), "graph", "node", id] as const,
  rules: (repoRoot: string) => [...queryKeys.repo(repoRoot), "rules"] as const,
  /** Prefix for invalidating all History queries for a repo. */
  historyRoot: (repoRoot: string) =>
    [...queryKeys.repo(repoRoot), "history"] as const,
  /** Prefix for invalidating all activity queries for a repo. */
  activityRoot: (repoRoot: string) =>
    [...queryKeys.repo(repoRoot), "activity"] as const,
  /** Activity list — filters (command/status) in key; limit is applied via select. */
  activity: (
    repoRoot: string,
    filters?: { command?: string | null; status?: string | null },
  ) =>
    [
      ...queryKeys.activityRoot(repoRoot),
      "list",
      filters?.command ?? "all",
      filters?.status ?? "all",
    ] as const,
  documentation: (repoRoot: string) =>
    [...queryKeys.repo(repoRoot), "documentation"] as const,
};
