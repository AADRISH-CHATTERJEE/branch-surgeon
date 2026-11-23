"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { useApiOptions } from "@/hooks/use-api-options";
import { gateRepoQuery } from "@/queries/repo-query-gate";
import { queryKeys } from "@/queries/keys";
import { fetchDocumentation } from "@/services/documentation";

/** Pass `enabled: false` until the Documentation page or command palette needs it. */
export function useDocumentation(enabled = true) {
  const opts = useApiOptions();
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: queryKeys.documentation(opts.repoRoot ?? "default"),
      queryFn: ({ signal }) => fetchDocumentation({ ...opts, signal }),
      enabled: opts.hydrated && enabled,
      // Seeded docs can appear on first GET — avoid long stale empty caches.
      staleTime: 30_000,
      refetchOnMount: "always",
      placeholderData: keepPreviousData,
    }),
  );
}
