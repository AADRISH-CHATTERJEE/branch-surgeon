"use client";

import { useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { useApiOptions } from "@/hooks/use-api-options";
import {
  ACTIVITY_FETCH_LIMIT,
  RECOMMENDATIONS_FETCH_LIMIT,
  REVIEWS_FETCH_LIMIT,
} from "@/lib/query-limits";
import { queryKeys } from "@/queries/keys";
import { fetchActivity } from "@/services/activity";
import { fetchGraphFull } from "@/services/graph";
import { fetchRecommendations } from "@/services/recommendations";
import { fetchRepository, fetchRepositoryStatus } from "@/services/repository";
import { fetchReviews } from "@/services/reviews";

/** Module-level set so hover prefetch runs at most once per repo+href. */
const prefetched = new Set<string>();

/**
 * Prefetch Local API data on nav hover. Safe to call repeatedly — network
 * fires once per (repoRoot, href) for the session.
 */
export function useNavPrefetch() {
  const qc = useQueryClient();
  const opts = useApiOptions();
  const repoRoot = opts.repoRoot ?? "default";

  return React.useCallback(
    (href: string) => {
      if (!opts.hydrated) return;
      const token = `${repoRoot}:${href}`;
      if (prefetched.has(token)) return;

      if (href === "/repository/graph") {
        prefetched.add(token);
        void qc.prefetchQuery({
          queryKey: queryKeys.graphFull(repoRoot),
          queryFn: ({ signal }) => fetchGraphFull({ ...opts, signal }),
          staleTime: 5 * 60_000,
        });
        return;
      }

      if (href === "/reviews") {
        prefetched.add(token);
        void qc.prefetchQuery({
          queryKey: queryKeys.reviews(repoRoot),
          queryFn: ({ signal }) =>
            fetchReviews({ ...opts, signal }, REVIEWS_FETCH_LIMIT),
          staleTime: 30_000,
        });
        return;
      }

      if (href === "/recommendations") {
        prefetched.add(token);
        void qc.prefetchQuery({
          queryKey: queryKeys.recommendations(repoRoot, "all"),
          queryFn: ({ signal }) =>
            fetchRecommendations(
              { ...opts, signal },
              { limit: RECOMMENDATIONS_FETCH_LIMIT },
            ),
          staleTime: 30_000,
        });
        return;
      }

      if (href === "/repository") {
        prefetched.add(token);
        void qc.prefetchQuery({
          queryKey: queryKeys.repository(repoRoot),
          queryFn: ({ signal }) => fetchRepository({ ...opts, signal }),
          staleTime: 60_000,
        });
        void qc.prefetchQuery({
          queryKey: queryKeys.repositoryStatus(repoRoot),
          queryFn: ({ signal }) => fetchRepositoryStatus({ ...opts, signal }),
          staleTime: 30_000,
        });
        return;
      }

      if (href === "/activity") {
        prefetched.add(token);
        void qc.prefetchQuery({
          queryKey: queryKeys.activity(repoRoot, { command: null, status: null }),
          queryFn: ({ signal }) =>
            fetchActivity({ ...opts, signal }, { limit: ACTIVITY_FETCH_LIMIT }),
          staleTime: 30_000,
        });
      }
    },
    [qc, opts, repoRoot],
  );
}
