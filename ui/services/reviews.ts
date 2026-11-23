import {
  apiRequest,
  apiRequestWithMeta,
  type ApiClientOptions,
} from "@/services/client";
import { endpoints } from "@/services/endpoints";
import type {
  PersistedReview,
  RecommendationRepositorySummary,
  ReviewSuggestion,
  ReviewSuggestionStatus,
} from "@/types/domain";

export function fetchReviews(options: ApiClientOptions = {}, limit = 50) {
  return apiRequest<PersistedReview[]>(`${endpoints.reviews}?limit=${limit}`, options);
}

export function fetchReview(id: string, options: ApiClientOptions = {}) {
  return apiRequest<PersistedReview>(endpoints.review(id), options);
}

export function createReview(prNumber: number, options: ApiClientOptions = {}) {
  return apiRequest<unknown>(endpoints.createReview, {
    ...options,
    method: "POST",
    body: JSON.stringify({ pr_number: prNumber }),
  });
}

export type SuggestionStatusUpdateResult = {
  suggestion: ReviewSuggestion;
  syncedRecommendationIds: string[];
  summary: RecommendationRepositorySummary | null;
  reviewId: string | null;
};

export async function updateReviewSuggestionStatus(
  reviewId: string,
  suggestionId: string,
  status: ReviewSuggestionStatus,
  options: ApiClientOptions = {},
): Promise<SuggestionStatusUpdateResult> {
  const envelope = await apiRequestWithMeta<ReviewSuggestion>(
    endpoints.reviewSuggestionStatus(reviewId, suggestionId),
    {
      ...options,
      method: "PATCH",
      body: JSON.stringify({ status, updated_by: "local" }),
    },
  );
  const meta = envelope.meta ?? {};
  const summary =
    meta.summary && typeof meta.summary === "object"
      ? (meta.summary as RecommendationRepositorySummary)
      : null;
  const synced = Array.isArray(meta.synced_recommendation_ids)
    ? (meta.synced_recommendation_ids as string[])
    : [];
  return {
    suggestion: envelope.data,
    syncedRecommendationIds: synced,
    summary,
    reviewId:
      typeof meta.review_id === "string"
        ? meta.review_id
        : envelope.data?.review_id ?? reviewId,
  };
}
