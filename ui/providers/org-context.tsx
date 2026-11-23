"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";

import { STORAGE_KEYS } from "@/lib/constants";
import { useRepoContext } from "@/providers/repo-context";
import {
  fetchOrganizationRepositories,
  fetchOrganizations,
  fetchOrganizationTeams,
  type Organization,
  type OrgRepository,
  type OrgTeam,
} from "@/services/organizations";

type OrgContextValue = {
  organizations: Organization[];
  organizationId: string | null;
  setOrganizationId: (id: string | null) => void;
  organization: Organization | null;
  teams: OrgTeam[];
  teamId: string | null;
  setTeamId: (id: string | null) => void;
  repositories: OrgRepository[];
  selectRepository: (rootPath: string) => void;
  isLoading: boolean;
};

const OrgContext = React.createContext<OrgContextValue | null>(null);

function readStorage(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function OrgProvider({ children }: { children: React.ReactNode }) {
  const { apiBaseUrl, repoRoot, setRepoRoot, hydrated } = useRepoContext();
  // SSR-safe nulls; restore from localStorage after mount (same pattern as RepoProvider).
  const [organizationIdState, setOrganizationIdState] = React.useState<string | null>(
    null,
  );
  const [teamId, setTeamIdState] = React.useState<string | null>(null);

  React.useEffect(() => {
    // Client-only hydrate from localStorage (SSR-safe nulls on first paint).
    const storedOrg = readStorage(STORAGE_KEYS.organizationId);
    const storedTeam = readStorage(STORAGE_KEYS.teamId);
    /* eslint-disable react-hooks/set-state-in-effect -- intentional post-mount storage hydrate */
    if (storedOrg) setOrganizationIdState(storedOrg);
    if (storedTeam) setTeamIdState(storedTeam);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, []);

  const setOrganizationId = React.useCallback((id: string | null) => {
    setOrganizationIdState(id);
    try {
      if (id) window.localStorage.setItem(STORAGE_KEYS.organizationId, id);
      else window.localStorage.removeItem(STORAGE_KEYS.organizationId);
    } catch {
      /* ignore */
    }
  }, []);

  const setTeamId = React.useCallback((id: string | null) => {
    setTeamIdState(id);
    try {
      if (id) window.localStorage.setItem(STORAGE_KEYS.teamId, id);
      else window.localStorage.removeItem(STORAGE_KEYS.teamId);
    } catch {
      /* ignore */
    }
  }, []);

  const orgsQuery = useQuery({
    queryKey: ["organizations", apiBaseUrl, repoRoot ?? "default"],
    queryFn: ({ signal }) =>
      fetchOrganizations({ baseUrl: apiBaseUrl, repoRoot, signal }),
    enabled: hydrated,
    staleTime: 30_000,
  });

  const organizations = React.useMemo(
    () => orgsQuery.data ?? [],
    [orgsQuery.data],
  );

  const organizationId = React.useMemo(() => {
    if (!organizations.length) return organizationIdState;
    if (
      organizationIdState &&
      organizations.some((o) => o.id === organizationIdState)
    ) {
      return organizationIdState;
    }
    const preferred =
      organizations.find((o) => o.is_default) ?? organizations[0] ?? null;
    return preferred?.id ?? null;
  }, [organizations, organizationIdState]);

  React.useEffect(() => {
    if (!organizationId) return;
    try {
      window.localStorage.setItem(STORAGE_KEYS.organizationId, organizationId);
    } catch {
      /* ignore */
    }
  }, [organizationId]);

  const organization =
    organizations.find((o) => o.id === organizationId) ?? null;

  const teamsQuery = useQuery({
    queryKey: ["org-teams", apiBaseUrl, organizationId ?? "none"],
    queryFn: ({ signal }) =>
      fetchOrganizationTeams(organizationId!, {
        baseUrl: apiBaseUrl,
        repoRoot,
        signal,
      }),
    enabled: hydrated && Boolean(organizationId),
    staleTime: 30_000,
  });

  const reposQuery = useQuery({
    queryKey: ["org-repos", apiBaseUrl, organizationId ?? "none"],
    queryFn: ({ signal }) =>
      fetchOrganizationRepositories(organizationId!, {
        baseUrl: apiBaseUrl,
        repoRoot,
        signal,
      }),
    enabled: hydrated && Boolean(organizationId),
    staleTime: 30_000,
  });

  const teams = React.useMemo(() => teamsQuery.data ?? [], [teamsQuery.data]);
  const repositories = React.useMemo(
    () => reposQuery.data ?? [],
    [reposQuery.data],
  );

  const selectRepository = React.useCallback(
    (rootPath: string) => {
      setRepoRoot(rootPath);
    },
    [setRepoRoot],
  );

  const value = React.useMemo(
    () => ({
      organizations,
      organizationId,
      setOrganizationId,
      organization,
      teams,
      teamId,
      setTeamId,
      repositories,
      selectRepository,
      isLoading: orgsQuery.isLoading,
    }),
    [
      organizations,
      organizationId,
      setOrganizationId,
      organization,
      teams,
      teamId,
      setTeamId,
      repositories,
      selectRepository,
      orgsQuery.isLoading,
    ],
  );

  return <OrgContext.Provider value={value}>{children}</OrgContext.Provider>;
}

export function useOrgContext() {
  const ctx = React.useContext(OrgContext);
  if (!ctx) {
    throw new Error("useOrgContext must be used within OrgProvider");
  }
  return ctx;
}

/** Safe access when OrgProvider may be absent (tests / early mount). */
export function useOptionalOrgContext() {
  return React.useContext(OrgContext);
}
