"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { useApiOptions } from "@/hooks/use-api-options";
import { gateRepoQuery } from "@/queries/repo-query-gate";
import { queryKeys } from "@/queries/keys";
import { ApiError } from "@/services/errors";
import {
  buildGraph,
  fetchGraphFull,
  fetchGraphNode,
  fetchGraphSummary,
} from "@/services/graph";

export function useGraphSummary(enabled = true) {
  const opts = useApiOptions();
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: queryKeys.graphSummary(opts.repoRoot ?? "default"),
      queryFn: ({ signal }) => fetchGraphSummary({ ...opts, signal }),
      enabled: opts.hydrated && enabled,
      staleTime: 60_000,
      placeholderData: keepPreviousData,
    }),
  );
}

export function useGraphFull(enabled = true) {
  const opts = useApiOptions();
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: queryKeys.graphFull(opts.repoRoot ?? "default"),
      queryFn: ({ signal }) => fetchGraphFull({ ...opts, signal }),
      enabled: opts.hydrated && enabled,
      staleTime: 5 * 60_000,
      placeholderData: keepPreviousData,
    }),
  );
}

export function useGraphNode(id: string | null) {
  const opts = useApiOptions();
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: queryKeys.graphNode(opts.repoRoot ?? "default", id ?? ""),
      queryFn: ({ signal }) => fetchGraphNode(id!, { ...opts, signal }),
      enabled: opts.hydrated && Boolean(id),
      placeholderData: keepPreviousData,
    }),
  );
}

export function useBuildGraph() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (force: boolean = false) => buildGraph(force, opts),
    onSuccess: () => {
      toast.success("Graph built");
      const root = opts.repoRoot ?? "default";
      void qc.invalidateQueries({ queryKey: queryKeys.repo(root) });
      void qc.invalidateQueries({ queryKey: queryKeys.graphFull(root) });
      void qc.invalidateQueries({ queryKey: queryKeys.graphSummary(root) });
      // repo prefix already covers history/activity; keep explicit for clarity
      void qc.invalidateQueries({ queryKey: queryKeys.historyRoot(root) });
      void qc.invalidateQueries({ queryKey: queryKeys.activityRoot(root) });
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : "Graph build failed");
    },
  });
}
