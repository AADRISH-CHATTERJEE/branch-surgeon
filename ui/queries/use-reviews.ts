"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { useApiOptions } from "@/hooks/use-api-options";
import {
  applyOptimisticRecommendationStats,
  patchSuggestionInList,
} from "@/lib/suggestion-lifecycle";
import { REVIEWS_FETCH_LIMIT } from "@/lib/query-limits";
import { invalidateAnalysisMemory } from "@/queries/invalidate-analysis-memory";
import { invalidateRecommendationTruth } from "@/queries/invalidate-recommendation-truth";
import { gateRepoQuery } from "@/queries/repo-query-gate";
import { queryKeys } from "@/queries/keys";
import { ApiError } from "@/services/errors";
import {
  createReview,
  fetchReview,
  fetchReviews,
  updateReviewSuggestionStatus,
} from "@/services/reviews";
import type {
  PersistedReview,
  RecommendationRepositorySummary,
  ReviewSuggestionStatus,
} from "@/types/domain";

/**
 * Shared reviews list. Always fetches {@link REVIEWS_FETCH_LIMIT}; `limit` only
 * slices the cached result so Dashboard/Surgeon/Activity reuse one request.
 */
export function useReviews(limit = REVIEWS_FETCH_LIMIT) {
  const opts = useApiOptions();
  const slice = Math.min(Math.max(1, limit), REVIEWS_FETCH_LIMIT);
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: queryKeys.reviews(opts.repoRoot ?? "default"),
      queryFn: ({ signal }) => fetchReviews({ ...opts, signal }, REVIEWS_FETCH_LIMIT),
      enabled: opts.hydrated,
      staleTime: 30_000,
      placeholderData: keepPreviousData,
      select: (rows: PersistedReview[]) => rows.slice(0, slice),
    }),
  );
}

export function useReview(id: string | null) {
  const opts = useApiOptions();
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: queryKeys.review(opts.repoRoot ?? "default", id ?? ""),
      queryFn: ({ signal }) => fetchReview(id!, { ...opts, signal }),
      enabled: opts.hydrated && Boolean(id),
      staleTime: 60_000,
      placeholderData: keepPreviousData,
    }),
  );
}

export function useCreateReview() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (prNumber: number) => createReview(prNumber, opts),
    onSuccess: () => {
      toast.success("Review complete");
      const repoRoot = opts.repoRoot ?? "default";
      void qc.invalidateQueries({ queryKey: queryKeys.reviews(repoRoot) });
      invalidateRecommendationTruth(qc, repoRoot);
      invalidateAnalysisMemory(qc, repoRoot);
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Review failed");
    },
  });
}

export function useUpdateReviewSuggestionStatus() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  const repoRoot = opts.repoRoot ?? "default";

  return useMutation({
    mutationFn: (input: {
      reviewId: string;
      /** Extra query-cache keys (e.g. PR number URL id) to patch alongside reviewId. */
      cacheIds?: string[];
      suggestionId: string;
      status: ReviewSuggestionStatus;
    }) =>
      updateReviewSuggestionStatus(
        input.reviewId,
        input.suggestionId,
        input.status,
        opts,
      ),
    onMutate: async (vars) => {
      const cacheIds = Array.from(
        new Set(
          [vars.reviewId, ...(vars.cacheIds ?? [])].filter(
            (id): id is string => Boolean(id),
          ),
        ),
      );
      await Promise.all(
        cacheIds.map((id) =>
          qc.cancelQueries({ queryKey: queryKeys.review(repoRoot, id) }),
        ),
      );
      await qc.cancelQueries({
        queryKey: queryKeys.recommendationStats(repoRoot),
      });

      const previousReviews = cacheIds.map((id) => ({
        id,
        data: qc.getQueryData<PersistedReview>(queryKeys.review(repoRoot, id)),
      }));
      const previousStats = qc.getQueryData<RecommendationRepositorySummary>(
        queryKeys.recommendationStats(repoRoot),
      );

      const now = new Date().toISOString();
      const statusPatch =
        vars.status === "resolved"
          ? { status: vars.status, resolved_at: now, ignored_at: null }
          : vars.status === "ignored"
            ? { status: vars.status, ignored_at: now, resolved_at: null }
            : { status: vars.status };

      for (const id of cacheIds) {
        qc.setQueryData(
          queryKeys.review(repoRoot, id),
          (prev: PersistedReview | undefined) => {
            if (!prev) return prev;
            return {
              ...prev,
              suggestions: patchSuggestionInList(
                prev.suggestions,
                vars.suggestionId,
                statusPatch,
              ),
            };
          },
        );
      }

      if (vars.status === "resolved" || vars.status === "ignored") {
        qc.setQueryData(
          queryKeys.recommendationStats(repoRoot),
          (prev: RecommendationRepositorySummary | undefined) =>
            applyOptimisticRecommendationStats(prev, vars.status as "resolved" | "ignored", true),
        );
      }

      return { previousReviews, previousStats, cacheIds };
    },
    onError: (err, _vars, ctx) => {
      if (ctx?.previousReviews) {
        for (const entry of ctx.previousReviews) {
          qc.setQueryData(queryKeys.review(repoRoot, entry.id), entry.data);
        }
      }
      if (ctx?.previousStats !== undefined) {
        qc.setQueryData(
          queryKeys.recommendationStats(repoRoot),
          ctx.previousStats,
        );
      }
      toast.error(
        err instanceof ApiError ? err.message : "Unable to update suggestion",
      );
    },
    onSuccess: (data, vars, ctx) => {
      const label =
        vars.status === "resolved"
          ? "Suggestion marked resolved"
          : vars.status === "ignored"
            ? "Suggestion ignored"
            : "Suggestion updated";
      toast.success(label);

      const cacheIds = Array.from(
        new Set(
          [
            vars.reviewId,
            data.reviewId,
            ...(vars.cacheIds ?? []),
            ...(ctx?.cacheIds ?? []),
          ].filter((id): id is string => Boolean(id)),
        ),
      );

      for (const id of cacheIds) {
        qc.setQueryData(
          queryKeys.review(repoRoot, id),
          (prev: PersistedReview | undefined) => {
            if (!prev?.suggestions) return prev;
            return {
              ...prev,
              suggestions: patchSuggestionInList(
                prev.suggestions,
                vars.suggestionId,
                { ...data.suggestion, status: vars.status },
              ),
            };
          },
        );
      }

      if (data.summary) {
        qc.setQueryData(queryKeys.recommendationStats(repoRoot), data.summary);
      } else if (data.syncedRecommendationIds.length === 0 && ctx?.previousStats) {
        // No matching recommendation — roll back optimistic stats bump.
        qc.setQueryData(
          queryKeys.recommendationStats(repoRoot),
          ctx.previousStats,
        );
      }

      void qc.invalidateQueries({ queryKey: queryKeys.reviews(repoRoot) });
      for (const id of cacheIds) {
        void qc.invalidateQueries({
          queryKey: queryKeys.review(repoRoot, id),
        });
      }
      invalidateRecommendationTruth(qc, repoRoot);
      invalidateAnalysisMemory(qc, repoRoot);
    },
  });
}
