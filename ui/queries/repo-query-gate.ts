import type { UseQueryResult } from "@tanstack/react-query";

/**
 * While RepoProvider has not finished reading localStorage, treat the query as
 * loading so existing `isLoading && !data` skeletons stay visible (no empty flash).
 */
export function gateRepoQuery<TData, TError>(
  hydrated: boolean,
  query: UseQueryResult<TData, TError>,
): UseQueryResult<TData, TError> {
  if (hydrated) return query;
  // Override loading flags for gated UI; cast keeps TanStack's result union happy.
  return {
    ...query,
    isLoading: true,
    isPending: true,
    isFetching: false,
  } as UseQueryResult<TData, TError>;
}
