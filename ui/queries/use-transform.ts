"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { useApiOptions } from "@/hooks/use-api-options";
import { invalidateAnalysisMemory } from "@/queries/invalidate-analysis-memory";
import { invalidateRecommendationTruth } from "@/queries/invalidate-recommendation-truth";
import { queryKeys } from "@/queries/keys";
import { ApiError, formatApiErrorMessage } from "@/services/errors";
import {
  applyTransform,
  fetchRecentTransforms,
  planTransform,
  previewTransform,
  rollbackTransform,
  rollbackTransformById,
  type TransformBody,
} from "@/services/transform";

function invalidateTransformQueries(
  qc: ReturnType<typeof useQueryClient>,
  repoRoot: string,
) {
  // PostTransformationPipeline regenerates recommendations + index + surgeon.
  invalidateRecommendationTruth(qc, repoRoot);
  invalidateAnalysisMemory(qc, repoRoot);
  void qc.invalidateQueries({ queryKey: queryKeys.files(repoRoot) });
  void qc.invalidateQueries({
    queryKey: [...queryKeys.repo(repoRoot), "transforms"],
  });
  void qc.invalidateQueries({ queryKey: queryKeys.repo(repoRoot) });
  void qc.invalidateQueries({ queryKey: [...queryKeys.all, "health"] });
}

function toastTransformError(err: unknown, fallback: string) {
  if (err instanceof ApiError) {
    const payload = err.body ?? {
      status: "error",
      message: err.message,
      errors: err.errors,
      meta: err.meta,
    };
    // Log status and full body (stringified so DevTools never shows a misleading {}).
    console.error(`[transform] HTTP ${err.status}\n${JSON.stringify(payload, null, 2)}`);
  } else {
    console.error("[transform] request failed", err);
  }
  toast.error(formatApiErrorMessage(err, fallback));
}

export function usePlanTransform() {
  const opts = useApiOptions();
  return useMutation({
    mutationFn: (body: TransformBody) => planTransform(body, opts),
    onError: (err) => toastTransformError(err, "Plan failed"),
  });
}

export function usePreviewTransform() {
  const opts = useApiOptions();
  return useMutation({
    mutationFn: (body: TransformBody) => previewTransform(body, opts),
    onError: (err) => toastTransformError(err, "Preview failed"),
  });
}

export function useApplyTransform() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: TransformBody) => applyTransform(body, opts),
    onSuccess: () => {
      toast.success("Transformation applied");
      invalidateTransformQueries(qc, opts.repoRoot ?? "default");
    },
    onError: (err) => toastTransformError(err, "Apply failed"),
  });
}

function toastRollbackError(err: unknown) {
  if (err instanceof ApiError && err.status === 409) {
    console.error(`[transform] HTTP ${err.status}\n${JSON.stringify(err.body, null, 2)}`);
    const bodyMsg =
      typeof err.body?.message === "string" ? err.body.message.trim() : "";
    toast.error(bodyMsg || "Transformation already rolled back.");
    return;
  }
  toastTransformError(err, "Rollback failed");
}

export function useRollbackTransform() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => rollbackTransform(opts),
    onSuccess: () => {
      toast.success("Transformation rolled back.");
      invalidateTransformQueries(qc, opts.repoRoot ?? "default");
    },
    onError: (err) => toastRollbackError(err),
  });
}

export function useRollbackTransformById() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (historyId: string) => rollbackTransformById(historyId, opts),
    onSuccess: () => {
      toast.success("Transformation rolled back.");
      invalidateTransformQueries(qc, opts.repoRoot ?? "default");
    },
    onError: (err) => toastRollbackError(err),
  });
}

export function useRecentTransforms(limit = 5) {
  const opts = useApiOptions();
  const repoRoot = opts.repoRoot ?? "default";
  return useQuery({
    queryKey: [...queryKeys.repo(repoRoot), "transforms", "recent", limit],
    queryFn: ({ signal }) =>
      fetchRecentTransforms({ ...opts, signal, limit }),
    enabled: opts.hydrated,
  });
}
