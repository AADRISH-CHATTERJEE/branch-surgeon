"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { useApiOptions } from "@/hooks/use-api-options";
import { invalidateAnalysisMemory } from "@/queries/invalidate-analysis-memory";
import { invalidateRecommendationTruth } from "@/queries/invalidate-recommendation-truth";
import { gateRepoQuery } from "@/queries/repo-query-gate";
import { queryKeys } from "@/queries/keys";
import { ApiError } from "@/services/errors";
import { checkRules, fetchRules } from "@/services/rules";

export function useRules() {
  const opts = useApiOptions();
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: queryKeys.rules(opts.repoRoot ?? "default"),
      queryFn: ({ signal }) => fetchRules({ ...opts, signal }),
      enabled: opts.hydrated,
      staleTime: 60_000,
      placeholderData: keepPreviousData,
    }),
  );
}

export function useRulesCheck() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (
      body?: {
        branch?: string | null;
        commit?: string | null;
        base?: string | null;
        changed_files?: string[] | null;
      } | void,
    ) => checkRules(body ?? {}, opts),
    onSuccess: (data) => {
      toast.message(`Rules check: ${data.outcome}`);
      const repoRoot = opts.repoRoot ?? "default";
      invalidateRecommendationTruth(qc, repoRoot);
      invalidateAnalysisMemory(qc, repoRoot);
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Rules check failed");
    },
  });
}
