import type {
  RecommendationRepositorySummary,
  ReviewSuggestion,
  ReviewSuggestionStatus,
} from "@/types/domain";

/** Apply a suggestion status patch onto a review's suggestion list. */
export function patchSuggestionInList(
  suggestions: ReviewSuggestion[] | undefined,
  suggestionId: string,
  patch: Partial<ReviewSuggestion> & { status: ReviewSuggestionStatus },
): ReviewSuggestion[] | undefined {
  if (!suggestions) return suggestions;
  return suggestions.map((s) =>
    s.id === suggestionId ? { ...s, ...patch, status: patch.status } : s,
  );
}

/**
 * Optimistic RecommendationStatsService totals when a matching recommendation
 * is resolved or ignored. Priority tiles are left unchanged (all-status).
 */
export function applyOptimisticRecommendationStats(
  prev: RecommendationRepositorySummary | undefined,
  status: Exclude<ReviewSuggestionStatus, "pending">,
  synced: boolean,
): RecommendationRepositorySummary | undefined {
  if (!prev || !synced) return prev;
  const pending = Math.max(0, (prev.pending ?? 0) - 1);
  if (status === "resolved") {
    return {
      ...prev,
      pending,
      resolved: (prev.resolved ?? 0) + 1,
      by_status: {
        ...(prev.by_status ?? {}),
        pending,
        resolved: ((prev.by_status?.resolved ?? prev.resolved) || 0) + 1,
      },
    };
  }
  return {
    ...prev,
    pending,
    ignored: (prev.ignored ?? 0) + 1,
    by_status: {
      ...(prev.by_status ?? {}),
      pending,
      ignored: ((prev.by_status?.ignored ?? prev.ignored) || 0) + 1,
    },
  };
}
