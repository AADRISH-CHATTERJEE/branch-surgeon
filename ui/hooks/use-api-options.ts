"use client";

import * as React from "react";

import { useOptionalOrgContext } from "@/providers/org-context";
import { useRepoContext } from "@/providers/repo-context";

/** Shared Local API options for React Query / services (stable identity). */
export function useApiOptions() {
  const { apiBaseUrl, repoRoot, hydrated } = useRepoContext();
  const org = useOptionalOrgContext();
  const orgId = org?.organizationId ?? null;
  const teamId = org?.teamId ?? null;
  return React.useMemo(
    () => ({ baseUrl: apiBaseUrl, repoRoot, orgId, teamId, hydrated }),
    [apiBaseUrl, repoRoot, orgId, teamId, hydrated],
  );
}
