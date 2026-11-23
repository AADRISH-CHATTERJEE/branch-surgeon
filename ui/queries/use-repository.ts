"use client";

import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";

import { useApiOptions } from "@/hooks/use-api-options";
import { invalidateRecommendationTruth } from "@/queries/invalidate-recommendation-truth";
import { gateRepoQuery } from "@/queries/repo-query-gate";
import { queryKeys } from "@/queries/keys";
import {
  fetchRepository,
  fetchRepositoryFileContent,
  fetchRepositoryFiles,
  fetchRepositoryHealth,
  fetchRepositoryImports,
  fetchRepositoryStatus,
  fetchRepositorySymbols,
} from "@/services/repository";

export function useRepository() {
  const opts = useApiOptions();
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: queryKeys.repository(opts.repoRoot ?? "default"),
      queryFn: ({ signal }) => fetchRepository({ ...opts, signal }),
      enabled: opts.hydrated,
      staleTime: 60_000,
      placeholderData: keepPreviousData,
    }),
  );
}

export function useRepositoryStatus() {
  const opts = useApiOptions();
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: queryKeys.repositoryStatus(opts.repoRoot ?? "default"),
      queryFn: ({ signal }) => fetchRepositoryStatus({ ...opts, signal }),
      enabled: opts.hydrated,
      staleTime: 30_000,
      placeholderData: keepPreviousData,
    }),
  );
}

export function useRepositoryHealth() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  const repoRoot = opts.repoRoot ?? "default";
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: queryKeys.repositoryHealth(repoRoot),
      queryFn: async ({ signal }) => {
        const report = await fetchRepositoryHealth({ ...opts, signal });
        // Health scan invalidates backend stats; refresh shared UI truth.
        invalidateRecommendationTruth(qc, repoRoot);
        return report;
      },
      enabled: opts.hydrated,
      staleTime: 60_000,
      placeholderData: keepPreviousData,
    }),
  );
}

export function useRepositoryFiles(params: { language?: string; limit?: number } = {}) {
  const opts = useApiOptions();
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: queryKeys.files(opts.repoRoot ?? "default", params),
      queryFn: ({ signal }) => fetchRepositoryFiles({ ...opts, signal }, params),
      enabled: opts.hydrated,
      staleTime: 60_000,
      placeholderData: keepPreviousData,
    }),
  );
}

export function useRepositoryFileContent(params: {
  path?: string | null;
  enabled?: boolean;
} = {}) {
  const opts = useApiOptions();
  const path = params.path ?? "";
  const enabled = params.enabled ?? Boolean(path);
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: queryKeys.fileContent(opts.repoRoot ?? "default", path),
      queryFn: ({ signal }) =>
        fetchRepositoryFileContent({ ...opts, signal }, { path }),
      enabled: opts.hydrated && enabled && Boolean(path),
      staleTime: 60_000,
    }),
  );
}

export function useRepositorySymbols(params: {
  file_id?: string;
  path?: string;
  limit?: number;
  enabled?: boolean;
} = {}) {
  const opts = useApiOptions();
  const { enabled = true, ...rest } = params;
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: queryKeys.symbols(opts.repoRoot ?? "default", rest),
      queryFn: ({ signal }) => fetchRepositorySymbols({ ...opts, signal }, rest),
      enabled: opts.hydrated && enabled,
      staleTime: 60_000,
    }),
  );
}

export function useRepositoryImports(params: {
  file_id?: string;
  path?: string;
  limit?: number;
  enabled?: boolean;
} = {}) {
  const opts = useApiOptions();
  const { enabled = true, ...rest } = params;
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: queryKeys.imports(opts.repoRoot ?? "default", rest),
      queryFn: ({ signal }) => fetchRepositoryImports({ ...opts, signal }, rest),
      enabled: opts.hydrated && enabled,
      staleTime: 60_000,
    }),
  );
}
