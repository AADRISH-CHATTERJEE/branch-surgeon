"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { useApiOptions } from "@/hooks/use-api-options";
import { invalidateRecommendationTruth } from "@/queries/invalidate-recommendation-truth";
import { gateRepoQuery } from "@/queries/repo-query-gate";
import { queryKeys } from "@/queries/keys";
import { ApiError } from "@/services/errors";
import { buildIndex, fetchIndexStatus } from "@/services/index-api";

export function useIndexStatus(enabled = true) {
  const opts = useApiOptions();
  const repoRoot = opts.repoRoot ?? "default";
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: [...queryKeys.repo(repoRoot), "index-status"],
      queryFn: ({ signal }) => fetchIndexStatus({ ...opts, signal }),
      enabled: opts.hydrated && enabled,
      staleTime: 30_000,
      placeholderData: keepPreviousData,
    }),
  );
}

export function useBuildIndex() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  const repoRoot = opts.repoRoot ?? "default";
  return useMutation({
    mutationFn: (force: boolean = false) => buildIndex(force, opts),
    onSuccess: () => {
      toast.success("Index built");
      void qc.invalidateQueries({ queryKey: queryKeys.repo(repoRoot) });
      void qc.invalidateQueries({ queryKey: queryKeys.files(repoRoot) });
      void qc.invalidateQueries({ queryKey: queryKeys.activityRoot(repoRoot) });
      void qc.invalidateQueries({ queryKey: queryKeys.historyRoot(repoRoot) });
      invalidateRecommendationTruth(qc, repoRoot);
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Index failed");
    },
  });
}
