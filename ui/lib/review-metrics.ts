import type { PersistedReview, ReviewSuggestion } from "@/types/domain";

/** Single source for suggestion count — History and Detail must match. */
export function reviewSuggestionCount(review: PersistedReview): number {
  if (typeof review.suggestion_count === "number") return review.suggestion_count;
  return review.suggestions?.length ?? 0;
}

export function reviewFileCount(review: PersistedReview): number {
  if (typeof review.file_count === "number") return review.file_count;
  if (!review.suggestions?.length) return 0;
  return new Set(review.suggestions.map((s) => s.file).filter(Boolean)).size;
}

export function reviewCriticalCount(review: PersistedReview): number {
  if (typeof review.critical_count === "number") return review.critical_count;
  return countBySeverity(review.suggestions, ["critical", "high", "blocker"]);
}

export function reviewWarningCount(review: PersistedReview): number {
  if (typeof review.warning_count === "number") return review.warning_count;
  return countBySeverity(review.suggestions, ["medium", "low", "warning", "warn"]);
}

/** Overall display score derived from persisted risk label (single mapping). */
export function reviewOverallScore(risk: string | undefined | null): number {
  const label = (risk || "unknown").toLowerCase();
  if (label === "critical") return 90;
  if (label === "high") return 70;
  if (label === "medium") return 50;
  if (label === "low") return 30;
  return 0;
}

function countBySeverity(
  suggestions: ReviewSuggestion[] | undefined,
  severities: string[],
): number {
  const set = new Set(severities);
  return (suggestions ?? []).filter((s) => set.has((s.severity || "").toLowerCase()))
    .length;
}
