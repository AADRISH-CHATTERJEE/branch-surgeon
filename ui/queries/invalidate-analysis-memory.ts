import type { useQueryClient } from "@tanstack/react-query";

import { invalidateRecommendationTruth } from "@/queries/invalidate-recommendation-truth";
import { queryKeys } from "@/queries/keys";

type QueryClient = ReturnType<typeof useQueryClient>;

/**
 * Invalidate History + Activity after ops that persist analysis memory.
 * Also refreshes recommendation truth so Branch Surgeon stays aligned.
 */
export function invalidateAnalysisMemory(qc: QueryClient, repoRoot: string) {
  const root = repoRoot || "default";
  void qc.invalidateQueries({ queryKey: queryKeys.historyRoot(root) });
  void qc.invalidateQueries({ queryKey: queryKeys.activityRoot(root) });
  invalidateRecommendationTruth(qc, root);
}
