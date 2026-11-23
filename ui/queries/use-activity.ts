"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { useApiOptions } from "@/hooks/use-api-options";
import { ACTIVITY_FETCH_LIMIT } from "@/lib/query-limits";
import { gateRepoQuery } from "@/queries/repo-query-gate";
import { queryKeys } from "@/queries/keys";
import { fetchActivity } from "@/services/activity";
import type { AnalysisRun } from "@/types/domain";

/**
 * Shared activity feed. Fetches a canonical page; `limit` slices client-side
 * so Dashboard / Surgeon / Activity share one request when filters match.
 */
export function useActivity(
  params: { limit?: number; command?: string; status?: string } = {},
) {
  const opts = useApiOptions();
  const command = params.command ?? null;
  const status = params.status ?? null;
  const slice = Math.min(
    Math.max(1, params.limit ?? ACTIVITY_FETCH_LIMIT),
    ACTIVITY_FETCH_LIMIT,
  );

  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: queryKeys.activity(opts.repoRoot ?? "default", { command, status }),
      queryFn: ({ signal }) =>
        fetchActivity(
          { ...opts, signal },
          {
            limit: ACTIVITY_FETCH_LIMIT,
            command: command ?? undefined,
            status: status ?? undefined,
          },
        ),
      enabled: opts.hydrated,
      staleTime: 30_000,
      placeholderData: keepPreviousData,
      select: (rows: AnalysisRun[]) => rows.slice(0, slice),
    }),
  );
}
