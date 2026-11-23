"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { useApiOptions } from "@/hooks/use-api-options";
import { RECOMMENDATIONS_FETCH_LIMIT } from "@/lib/query-limits";
import { invalidateAnalysisMemory } from "@/queries/invalidate-analysis-memory";
import { invalidateRecommendationTruth } from "@/queries/invalidate-recommendation-truth";
import { gateRepoQuery } from "@/queries/repo-query-gate";
import { queryKeys } from "@/queries/keys";
import { ApiError } from "@/services/errors";
import {
  applyRecommendation,
  deleteRecommendation,
  fetchRecommendations,
  fetchRecommendationPatches,
  fetchRecommendationStats,
  generateRecommendationPatch,
  generateRecommendations,
  ignoreRecommendation,
  resolveRecommendation,
  rollbackRecommendation,
  updateRecommendation,
} from "@/services/recommendations";
import type { PersistedRecommendation } from "@/types/domain";

function invalidateAfterPatchApply(
  qc: ReturnType<typeof useQueryClient>,
  repoRoot: string,
) {
  // Invalidate repository-scoped caches (recommendations, repo, graph, health, history).
  void qc.invalidateQueries({ queryKey: queryKeys.repo(repoRoot) });
  void qc.invalidateQueries({ queryKey: [...queryKeys.all, "health"] });
  invalidateRecommendationTruth(qc, repoRoot);
  invalidateAnalysisMemory(qc, repoRoot);
}

/** Canonical repository totals from RecommendationStatsService. */
export function useRecommendationStats() {
  const opts = useApiOptions();
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: queryKeys.recommendationStats(opts.repoRoot ?? "default"),
      queryFn: ({ signal }) =>
        fetchRecommendationStats({ ...opts, signal }),
      enabled: opts.hydrated,
      staleTime: 10_000,
      refetchInterval: 20_000,
      placeholderData: keepPreviousData,
      refetchOnWindowFocus: true,
    }),
  );
}

function applyErrorMessage(err: ApiError): string {
  const detail = err.errors[0] || err.message || "";
  const lower = detail.toLowerCase();
  if (err.status === 409) {
    if (lower.includes("outdated") || lower.includes("no longer")) {
      return detail || "Patch outdated — generate a new patch from current files.";
    }
    if (lower.includes("dirty") || lower.includes("merge conflict")) {
      return detail || "Dirty working tree — resolve conflicts before applying.";
    }
    if (lower.includes("organization policy") || lower.includes("controllers")) {
      return detail || "Blocked by organization architecture policy.";
    }
    return detail || "Patch conflict — the repository changed. Generate a new patch.";
  }
  if (err.status === 403) {
    return detail || "Permission denied writing patch files.";
  }
  if (err.status === 422) {
    if (lower.includes("validation")) {
      return detail || "Validation failed — changes were rolled back.";
    }
    if (lower.includes("git failure") || lower.includes("writing")) {
      return detail || "Git failure while writing patch files.";
    }
    return detail || "Unable to apply patch.";
  }
  if (err.status === 404) {
    return (
      detail ||
      "Apply API not found. Restart the Local API so POST /recommendations/{id}/apply is loaded."
    );
  }
  return detail || "Unable to apply patch.";
}

/**
 * Shared recommendations list. Fetches a canonical page once; `limit` slices
 * client-side so Dashboard / Activity / Recommendations share cache.
 */
export function useRecommendations(
  params: { limit?: number; status?: string } = {},
) {
  const opts = useApiOptions();
  const status = params.status ?? null;
  const slice = Math.min(
    Math.max(1, params.limit ?? RECOMMENDATIONS_FETCH_LIMIT),
    RECOMMENDATIONS_FETCH_LIMIT,
  );

  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: queryKeys.recommendations(opts.repoRoot ?? "default", status),
      queryFn: ({ signal }) =>
        fetchRecommendations(
          { ...opts, signal },
          { limit: RECOMMENDATIONS_FETCH_LIMIT, status: status ?? undefined },
        ),
      enabled: opts.hydrated,
      staleTime: 30_000,
      placeholderData: keepPreviousData,
      select: (rows: PersistedRecommendation[]) => rows.slice(0, slice),
    }),
  );
}

export function useGenerateRecommendations() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body?: { top?: number; category?: string; priority?: string }) =>
      generateRecommendations(body ?? {}, opts),
    onSuccess: () => {
      toast.success("Recommendations generated");
      const repoRoot = opts.repoRoot ?? "default";
      invalidateRecommendationTruth(qc, repoRoot);
      invalidateAnalysisMemory(qc, repoRoot);
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Recommend failed");
    },
  });
}

export function useGenerateRecommendationPatch() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (recommendationId: string) =>
      generateRecommendationPatch(recommendationId, opts),
    onSuccess: (data, recommendationId) => {
      toast.success("Patch generated");
      const repoRoot = opts.repoRoot ?? "default";
      void qc.invalidateQueries({
        queryKey: queryKeys.recommendationPatches(repoRoot, recommendationId),
      });
      invalidateAnalysisMemory(qc, repoRoot);
      void qc.setQueryData(
        queryKeys.recommendationPatches(opts.repoRoot ?? "default", recommendationId),
        (prev: unknown) => {
          const list = Array.isArray(prev) ? prev : [];
          return [data, ...list];
        },
      );
    },
    onError: (err) => {
      let message =
        err instanceof ApiError
          ? err.errors[0] || err.message
          : "Unable to generate patch";
      if (err instanceof ApiError && err.status === 404) {
        message =
          "Patch API not found (404). Restart the Local API so POST /recommendations/{id}/patch is loaded.";
      }
      toast.error(message);
    },
  });
}

export function useRecommendationPatches(recommendationId: string | null) {
  const opts = useApiOptions();
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: queryKeys.recommendationPatches(
        opts.repoRoot ?? "default",
        recommendationId ?? "",
      ),
      queryFn: ({ signal }) =>
        fetchRecommendationPatches(recommendationId!, { ...opts, signal }),
      enabled: opts.hydrated && Boolean(recommendationId),
      staleTime: 30_000,
    }),
  );
}

export function useApplyRecommendationPatch() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  const repoRoot = opts.repoRoot ?? "default";

  return useMutation({
    mutationFn: (input: { recommendationId: string; patchId?: string }) =>
      applyRecommendation(input.recommendationId, opts, {
        patch_id: input.patchId,
      }),
    onSuccess: (data) => {
      toast.success(data.message || "Patch applied");
      invalidateAfterPatchApply(qc, repoRoot);
      if (data.recommendation_id) {
        void qc.invalidateQueries({
          queryKey: queryKeys.recommendationPatches(repoRoot, data.recommendation_id),
        });
      }
    },
    onError: (err) => {
      if (!(err instanceof ApiError)) {
        toast.error("Unable to apply patch");
        return;
      }
      toast.error(applyErrorMessage(err));
    },
  });
}

export function useRollbackRecommendationPatch() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  const repoRoot = opts.repoRoot ?? "default";

  return useMutation({
    mutationFn: (input: { recommendationId: string; patchId?: string }) =>
      rollbackRecommendation(input.recommendationId, opts, {
        patch_id: input.patchId,
      }),
    onSuccess: (data) => {
      toast.success(data.message || "Patch rolled back");
      invalidateAfterPatchApply(qc, repoRoot);
    },
    onError: (err) => {
      toast.error(
        err instanceof ApiError ? applyErrorMessage(err) : "Unable to roll back patch",
      );
    },
  });
}

export function useResolveRecommendation() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  const repoRoot = opts.repoRoot ?? "default";
  return useMutation({
    mutationFn: (id: string) => resolveRecommendation(id, opts),
    onSuccess: (data) => {
      toast.success("Recommendation resolved");
      if (data.summary) {
        qc.setQueryData(queryKeys.recommendationStats(repoRoot), data.summary);
      }
      void qc.invalidateQueries({
        queryKey: [...queryKeys.repo(repoRoot), "recommendations"],
      });
      invalidateRecommendationTruth(qc, repoRoot);
      invalidateAnalysisMemory(qc, repoRoot);
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Resolve failed");
    },
  });
}

export function useIgnoreRecommendation() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  const repoRoot = opts.repoRoot ?? "default";
  return useMutation({
    mutationFn: (id: string) => ignoreRecommendation(id, opts),
    onSuccess: (data) => {
      toast.success("Recommendation ignored");
      if (data.summary) {
        qc.setQueryData(queryKeys.recommendationStats(repoRoot), data.summary);
      }
      void qc.invalidateQueries({
        queryKey: [...queryKeys.repo(repoRoot), "recommendations"],
      });
      invalidateRecommendationTruth(qc, repoRoot);
      invalidateAnalysisMemory(qc, repoRoot);
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Ignore failed");
    },
  });
}

export function useDeleteRecommendation() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  const repoRoot = opts.repoRoot ?? "default";
  return useMutation({
    mutationFn: (id: string) => deleteRecommendation(id, opts),
    onSuccess: () => {
      toast.success("Recommendation deleted");
      invalidateRecommendationTruth(qc, repoRoot);
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Delete failed");
    },
  });
}

export function useUpdateRecommendationPriority() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  const repoRoot = opts.repoRoot ?? "default";
  return useMutation({
    mutationFn: (input: { id: string; priority: string }) =>
      updateRecommendation(input.id, { priority: input.priority }, opts),
    onSuccess: (data) => {
      toast.success("Priority updated");
      if (data.summary) {
        qc.setQueryData(queryKeys.recommendationStats(repoRoot), data.summary);
      }
      invalidateRecommendationTruth(qc, repoRoot);
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Update failed");
    },
  });
}

export function useUpdateRecommendationNotes() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  const repoRoot = opts.repoRoot ?? "default";
  return useMutation({
    mutationFn: (input: { id: string; resolution_notes: string }) =>
      updateRecommendation(
        input.id,
        { resolution_notes: input.resolution_notes },
        opts,
      ),
    onSuccess: () => {
      toast.success("Notes saved");
      void qc.invalidateQueries({
        queryKey: [...queryKeys.repo(repoRoot), "recommendations"],
      });
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Unable to save notes");
    },
  });
}
