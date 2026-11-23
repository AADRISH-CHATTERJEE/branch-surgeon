"use client";

import { useQuery } from "@tanstack/react-query";

import { useRepoContext } from "@/providers/repo-context";
import { fetchHealth } from "@/services/health";
import { queryKeys } from "@/queries/keys";

export function useApiHealth() {
  const { apiBaseUrl } = useRepoContext();

  return useQuery({
    queryKey: queryKeys.health(apiBaseUrl),
    queryFn: ({ signal }) => fetchHealth({ baseUrl: apiBaseUrl, signal }),
    staleTime: 15_000,
    retry: (count, error) => {
      if (error && typeof error === "object" && "isClient" in error) {
        return false;
      }
      return count < 1;
    },
  });
}
