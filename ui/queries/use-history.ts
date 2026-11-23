"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { useApiOptions } from "@/hooks/use-api-options";
import { gateRepoQuery } from "@/queries/repo-query-gate";
import { queryKeys } from "@/queries/keys";
import { ApiError } from "@/services/errors";
import {
  applyHistoryRetention,
  downloadHistoryExport,
  fetchHistory,
  fetchHistoryItem,
  fetchHistoryMetrics,
  type HistoryListParams,
} from "@/services/history";

export function useHistory(params: HistoryListParams = {}) {
  const opts = useApiOptions();
  const repoRoot = opts.repoRoot ?? "default";
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: [...queryKeys.historyRoot(repoRoot), "list", params],
      queryFn: ({ signal }) =>
        fetchHistory({ ...opts, signal }, { limit: 200, ...params }),
      enabled: opts.hydrated,
      staleTime: 20_000,
      placeholderData: keepPreviousData,
    }),
  );
}

export function useHistoryMetrics() {
  const opts = useApiOptions();
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: [...queryKeys.historyRoot(opts.repoRoot ?? "default"), "metrics"],
      queryFn: ({ signal }) => fetchHistoryMetrics({ ...opts, signal }),
      enabled: opts.hydrated,
      staleTime: 20_000,
    }),
  );
}

export function useHistoryItem(id: string | null) {
  const opts = useApiOptions();
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: [...queryKeys.historyRoot(opts.repoRoot ?? "default"), "item", id ?? ""],
      queryFn: ({ signal }) => fetchHistoryItem(id!, { ...opts, signal }),
      enabled: opts.hydrated && Boolean(id),
    }),
  );
}

export function useExportHistory() {
  const opts = useApiOptions();
  return useMutation({
    mutationFn: (format: "json" | "markdown" | "csv") =>
      downloadHistoryExport(format, opts),
    onSuccess: () => toast.success("History exported"),
    onError: (err) =>
      toast.error(err instanceof Error ? err.message : "Export failed"),
  });
}

export function useApplyHistoryRetention() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (days: number | null) => applyHistoryRetention(days, opts),
    onSuccess: (data) => {
      toast.success(
        data.deleted
          ? `Removed ${data.deleted} history item(s)`
          : "Retention policy saved (nothing to delete)",
      );
      void qc.invalidateQueries({
        queryKey: queryKeys.historyRoot(opts.repoRoot ?? "default"),
      });
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Retention failed"),
  });
}
