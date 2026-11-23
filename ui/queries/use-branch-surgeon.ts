"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { useApiOptions } from "@/hooks/use-api-options";
import { gateRepoQuery } from "@/queries/repo-query-gate";
import { queryKeys } from "@/queries/keys";
import { fetchBranchSurgeon } from "@/services/surgeon";

export function useBranchSurgeon() {
  const opts = useApiOptions();
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: queryKeys.branchSurgeon(opts.repoRoot ?? "default"),
      queryFn: ({ signal }) => fetchBranchSurgeon({ ...opts, signal }),
      enabled: opts.hydrated,
      staleTime: 10_000,
      refetchInterval: 20_000,
      refetchOnWindowFocus: true,
      placeholderData: keepPreviousData,
    }),
  );
}
