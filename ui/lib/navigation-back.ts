/** Logical parent routes for in-app Back when history cannot go back. */

const ROOTS = new Set(["/", "/surgeon", "/dashboard"]);

/** Exact path → parent. More specific paths win via longest-prefix matching below. */
const PARENT_BY_PREFIX: Array<{ prefix: string; parent: string }> = [
  { prefix: "/repository/graph", parent: "/repository" },
  { prefix: "/repository/health", parent: "/repository" },
  { prefix: "/repository/files", parent: "/repository" },
  { prefix: "/repository/symbols", parent: "/repository" },
  { prefix: "/repository/imports", parent: "/repository" },
  { prefix: "/repository", parent: "/surgeon" },
  { prefix: "/reviews", parent: "/surgeon" },
  { prefix: "/recommendations", parent: "/surgeon" },
  { prefix: "/surgeon", parent: "/surgeon" },
  { prefix: "/transform", parent: "/surgeon" },
  { prefix: "/rules", parent: "/surgeon" },
  { prefix: "/documentation", parent: "/surgeon" },
  { prefix: "/settings", parent: "/surgeon" },
  { prefix: "/activity", parent: "/surgeon" },
  { prefix: "/history", parent: "/surgeon" },
  { prefix: "/graph", parent: "/repository" },
];

export function isDashboardPath(pathname: string): boolean {
  const p = normalizePath(pathname);
  return ROOTS.has(p);
}

/** Whether the Back control should appear for this route. */
export function shouldShowBack(pathname: string): boolean {
  return !isDashboardPath(pathname);
}

/**
 * Logical parent when `router.back()` is not available.
 *
 * - Nested routes (e.g. /repository/graph → /repository)
 * - Detail query on a list page (?id=) → same path without search (Reviews list)
 * - Section roots → /surgeon (flagship landing; /dashboard removed)
 */
export function logicalParentPath(
  pathname: string,
  search?: string | null,
): string {
  const p = normalizePath(pathname);
  if (ROOTS.has(p)) return "/surgeon";

  const params = new URLSearchParams(search || "");
  // Drawer / detail deep-links: leave the detail, stay on the list route.
  if (params.has("id") || params.has("file") || params.has("doc")) {
    return p;
  }

  let best: { prefix: string; parent: string } | null = null;
  for (const entry of PARENT_BY_PREFIX) {
    if (p === entry.prefix || p.startsWith(`${entry.prefix}/`)) {
      if (!best || entry.prefix.length > best.prefix.length) {
        best = entry;
      }
    }
  }
  return best?.parent ?? "/surgeon";
}

/**
 * True when the session has in-app history we can safely go back through.
 * Uses Navigation API when available; otherwise treats history.length > 1
 * as a hint (may still fall back if same-origin stack is empty).
 */
export function canUseHistoryBack(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const nav = window.navigation;
    if (nav && typeof nav.canGoBack === "boolean") {
      return nav.canGoBack;
    }
  } catch {
    // Navigation API unavailable or restricted
  }
  return window.history.length > 1;
}

function normalizePath(pathname: string): string {
  if (!pathname) return "/";
  const trimmed = pathname.split("?")[0]?.split("#")[0] || "/";
  if (trimmed.length > 1 && trimmed.endsWith("/")) {
    return trimmed.slice(0, -1);
  }
  return trimmed || "/";
}

/** Extend Window for the experimental Navigation API. */
declare global {
  interface Window {
    navigation?: { canGoBack?: boolean };
  }
}
