import type { useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/queries/keys";

type QueryClient = ReturnType<typeof useQueryClient>;

/**
 * Invalidate the single recommendation truth surface:
 * - RecommendationStatsService (GET /recommendations/stats)
 * - Branch Surgeon workspace (embeds the same summary)
 * - Recommendations list cache
 * - Dashboard / repository status / health / activity / history
 *
 * Call after Generate / Resolve / Ignore / Rollback / Transform Apply /
 * Index / Health / Review / Rules Check / PostTransformationPipeline.
 */
export function invalidateRecommendationTruth(
  qc: QueryClient,
  repoRoot: string,
) {
  const root = repoRoot || "default";
  void qc.invalidateQueries({
    queryKey: queryKeys.recommendationStats(root),
  });
  void qc.invalidateQueries({
    queryKey: queryKeys.branchSurgeon(root),
  });
  void qc.invalidateQueries({
    queryKey: [...queryKeys.repo(root), "recommendations"],
  });
  void qc.invalidateQueries({
    queryKey: queryKeys.repositoryStatus(root),
  });
  void qc.invalidateQueries({
    queryKey: queryKeys.repositoryHealth(root),
  });
  void qc.invalidateQueries({
    queryKey: queryKeys.repository(root),
  });
  void qc.invalidateQueries({
    queryKey: queryKeys.activityRoot(root),
  });
  void qc.invalidateQueries({
    queryKey: queryKeys.historyRoot(root),
  });
  void qc.invalidateQueries({
    queryKey: queryKeys.graphSummary(root),
  });
  void qc.invalidateQueries({
    queryKey: queryKeys.graphFull(root),
  });
}
