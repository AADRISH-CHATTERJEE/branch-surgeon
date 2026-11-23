"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

export type ListFiltersState = {
  search: string;
  sort: string | null;
  status: string | null;
  severity: string | null;
  priority: string | null;
  category: string | null;
  extra: Record<string, string | null>;
};

type UseListFiltersOptions = {
  /** Sync selected keys to URL search params */
  urlKeys?: (keyof ListFiltersState | string)[];
  /** Persist a single string value (e.g. view mode) */
  storageKey?: string;
  storageField?: string;
  defaults?: Partial<ListFiltersState>;
};

function readStorage(key: string | undefined): string | null {
  if (!key || typeof window === "undefined") return null;
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

/**
 * Shared list filtering state for Reviews / Recommendations / Rules / Activity.
 * URL sync is opt-in per key; localStorage is optional for one field (e.g. view).
 */
export function useListFilters(options: UseListFiltersOptions = {}) {
  const { urlKeys = [], storageKey, storageField, defaults } = options;
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const [state, setState] = React.useState<ListFiltersState>(() => {
    const stored =
      storageKey && storageField ? readStorage(storageKey) : null;
    return {
      search: defaults?.search ?? "",
      sort: defaults?.sort ?? null,
      status: defaults?.status ?? null,
      severity: defaults?.severity ?? null,
      priority: defaults?.priority ?? (params.get("priority") || null),
      category: defaults?.category ?? null,
      extra: {
        ...(defaults?.extra ?? {}),
        ...(storageField && stored ? { [storageField]: stored } : {}),
        id: params.get("id"),
      },
    };
  });

  const setFilter = React.useCallback(
    <K extends keyof ListFiltersState>(key: K, value: ListFiltersState[K]) => {
      setState((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const setExtra = React.useCallback((key: string, value: string | null) => {
    setState((prev) => ({
      ...prev,
      extra: { ...prev.extra, [key]: value },
    }));
    if (storageKey && storageField === key && value != null) {
      try {
        localStorage.setItem(storageKey, value);
      } catch {
        /* ignore */
      }
    }
  }, [storageKey, storageField]);

  // Sync selected keys to URL without wiping unrelated params
  React.useEffect(() => {
    if (!urlKeys.length) return;
    const next = new URLSearchParams(params.toString());
    let changed = false;

    const apply = (key: string, value: string | null | undefined) => {
      const current = next.get(key);
      const normalized = value && value.length ? value : null;
      if (normalized == null && current != null) {
        next.delete(key);
        changed = true;
      } else if (normalized != null && current !== normalized) {
        next.set(key, normalized);
        changed = true;
      }
    };

    for (const key of urlKeys) {
      if (key === "search") apply("q", state.search || null);
      else if (key === "extra") {
        /* skip blob */
      } else if (key in state && key !== "extra") {
        const v = state[key as keyof ListFiltersState];
        if (typeof v === "string" || v === null) apply(key, v);
      } else if (key in state.extra) {
        apply(key, state.extra[key] ?? null);
      }
    }

    // Always allow id in extra when listed
    if (urlKeys.includes("id")) {
      apply("id", state.extra.id ?? null);
    }

    if (changed) {
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sync from state only
  }, [state, urlKeys, pathname, router]);

  return {
    filters: state,
    setFilter,
    setExtra,
    setSearch: (v: string) => setFilter("search", v),
    setSort: (v: string | null) => setFilter("sort", v),
    setStatus: (v: string | null) => setFilter("status", v),
    setSeverity: (v: string | null) => setFilter("severity", v),
    setPriority: (v: string | null) => setFilter("priority", v),
    setCategory: (v: string | null) => setFilter("category", v),
  };
}
