"use client";

import * as React from "react";

import { DEFAULT_API_URL, STORAGE_KEYS } from "@/lib/constants";

type RepoContextValue = {
  apiBaseUrl: string;
  setApiBaseUrl: (url: string) => void;
  repoRoot: string | null;
  setRepoRoot: (root: string | null) => void;
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (collapsed: boolean) => void;
  /** True after localStorage has been read once (Phase 11.5A). */
  hydrated: boolean;
};

const RepoContext = React.createContext<RepoContextValue | null>(null);

function readStorage(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function RepoProvider({ children }: { children: React.ReactNode }) {
  // SSR-safe defaults — must match server + first client render (no localStorage).
  const [apiBaseUrl, setApiBaseUrlState] = React.useState(DEFAULT_API_URL);
  const [repoRoot, setRepoRootState] = React.useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsedState] = React.useState(false);
  const [hydrated, setHydrated] = React.useState(false);

  React.useEffect(() => {
    // Client-only hydrate from localStorage (must stay null on SSR for hydration match).
    const storedApi = readStorage(STORAGE_KEYS.apiBaseUrl);
    const storedRoot = readStorage(STORAGE_KEYS.repoRoot);
    const storedCollapsed = readStorage(STORAGE_KEYS.sidebarCollapsed) === "1";
    /* eslint-disable react-hooks/set-state-in-effect -- intentional post-mount storage hydrate */
    if (storedApi) {
      setApiBaseUrlState(storedApi.replace(/\/$/, "") || DEFAULT_API_URL);
    }
    if (storedRoot) {
      setRepoRootState(storedRoot);
    }
    setSidebarCollapsedState(storedCollapsed);
    setHydrated(true);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, []);

  const setApiBaseUrl = React.useCallback((url: string) => {
    const next = url.replace(/\/$/, "") || DEFAULT_API_URL;
    setApiBaseUrlState(next);
    try {
      window.localStorage.setItem(STORAGE_KEYS.apiBaseUrl, next);
    } catch {
      /* ignore */
    }
  }, []);

  const setRepoRoot = React.useCallback((root: string | null) => {
    const next = root?.trim() || null;
    setRepoRootState(next);
    try {
      if (next) window.localStorage.setItem(STORAGE_KEYS.repoRoot, next);
      else window.localStorage.removeItem(STORAGE_KEYS.repoRoot);
    } catch {
      /* ignore */
    }
  }, []);

  const setSidebarCollapsed = React.useCallback((collapsed: boolean) => {
    setSidebarCollapsedState(collapsed);
    try {
      window.localStorage.setItem(STORAGE_KEYS.sidebarCollapsed, collapsed ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, []);

  const value = React.useMemo(
    () => ({
      apiBaseUrl,
      setApiBaseUrl,
      repoRoot,
      setRepoRoot,
      sidebarCollapsed,
      setSidebarCollapsed,
      hydrated,
    }),
    [
      apiBaseUrl,
      setApiBaseUrl,
      repoRoot,
      setRepoRoot,
      sidebarCollapsed,
      setSidebarCollapsed,
      hydrated,
    ],
  );

  return <RepoContext.Provider value={value}>{children}</RepoContext.Provider>;
}

export function useRepoContext() {
  const ctx = React.useContext(RepoContext);
  if (!ctx) {
    throw new Error("useRepoContext must be used within RepoProvider");
  }
  return ctx;
}
