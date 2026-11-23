import { DEFAULT_API_URL, STORAGE_KEYS } from "@/lib/constants";

export type AccentColor = "default" | "blue" | "teal" | "amber" | "rose";

export type LandingPage =
  | "/surgeon"
  | "/repository"
  | "/reviews"
  | "/recommendations"
  | "/history"
  | "/activity"
  | "/documentation"
  | "/settings";

export type UiPreferences = {
  accent: AccentColor;
  compactMode: boolean;
  animations: boolean;
  landingPage: LandingPage;
  /** When true, sidebar starts collapsed on narrow viewports preference (client hint) */
  sidebarAutoCollapse: boolean;
  toastDurationMs: number;
  toastSuccess: boolean;
  toastWarnings: boolean;
  toastErrors: boolean;
  desktopNotifications: boolean;
  debugMode: boolean;
  apiInspector: boolean;
  experimentalFeatures: boolean;
  /** History retention in days; 0 = unlimited */
  historyRetentionDays: 0 | 30 | 90 | 365;
};

export const DEFAULT_PREFERENCES: UiPreferences = {
  accent: "default",
  compactMode: false,
  animations: true,
  landingPage: "/surgeon",
  sidebarAutoCollapse: false,
  toastDurationMs: 4000,
  toastSuccess: true,
  toastWarnings: true,
  toastErrors: true,
  desktopNotifications: false,
  debugMode: false,
  apiInspector: false,
  experimentalFeatures: false,
  historyRetentionDays: 0,
};

export const HISTORY_RETENTION_OPTIONS: {
  value: UiPreferences["historyRetentionDays"];
  label: string;
}[] = [
  { value: 0, label: "Unlimited" },
  { value: 30, label: "30 days" },
  { value: 90, label: "90 days" },
  { value: 365, label: "365 days" },
];

export const LANDING_PAGE_OPTIONS: { value: LandingPage; label: string }[] = [
  { value: "/surgeon", label: "Branch Surgeon (Flagship)" },
  { value: "/repository", label: "Repository" },
  { value: "/reviews", label: "Reviews" },
  { value: "/recommendations", label: "Recommendations" },
  { value: "/history", label: "History" },
  { value: "/activity", label: "Activity" },
  { value: "/documentation", label: "Documentation" },
  { value: "/settings", label: "Settings" },
];

export const ACCENT_OPTIONS: { value: AccentColor; label: string }[] = [
  { value: "default", label: "Default" },
  { value: "blue", label: "Blue" },
  { value: "teal", label: "Teal" },
  { value: "amber", label: "Amber" },
  { value: "rose", label: "Rose" },
];

function readRaw(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeRaw(key: string, value: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (value == null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}

const RETENTION_DAYS = new Set<UiPreferences["historyRetentionDays"]>([0, 30, 90, 365]);

export function loadPreferences(): UiPreferences {
  const raw = readRaw(STORAGE_KEYS.preferences);
  if (!raw) return { ...DEFAULT_PREFERENCES };
  try {
    const parsed = JSON.parse(raw) as Partial<UiPreferences>;
    const merged = { ...DEFAULT_PREFERENCES, ...parsed };
    if (!RETENTION_DAYS.has(merged.historyRetentionDays)) {
      merged.historyRetentionDays = DEFAULT_PREFERENCES.historyRetentionDays;
    }
    return merged;
  } catch {
    return { ...DEFAULT_PREFERENCES };
  }
}

export function savePreferences(prefs: UiPreferences) {
  writeRaw(STORAGE_KEYS.preferences, JSON.stringify(prefs));
}

export function getRecentRepositories(): string[] {
  const raw = readRaw(STORAGE_KEYS.recentRepos);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed)
      ? parsed.filter((x): x is string => typeof x === "string")
      : [];
  } catch {
    return [];
  }
}

export function pushRecentRepository(root: string, limit = 8): string[] {
  const trimmed = root.trim();
  if (!trimmed) return getRecentRepositories();
  const next = [trimmed, ...getRecentRepositories().filter((r) => r !== trimmed)].slice(
    0,
    limit,
  );
  writeRaw(STORAGE_KEYS.recentRepos, JSON.stringify(next));
  return next;
}

export function clearRecentRepositories() {
  writeRaw(STORAGE_KEYS.recentRepos, null);
}

export type PreferencesBundle = {
  version: 1;
  exportedAt: string;
  preferences: UiPreferences;
  workspace: {
    apiBaseUrl: string;
    repoRoot: string | null;
    sidebarCollapsed: boolean;
  };
  theme: string | null;
  recentRepos: string[];
  featurePrefs: Record<string, string | null>;
};

export function exportPreferencesBundle(input: {
  preferences: UiPreferences;
  apiBaseUrl: string;
  repoRoot: string | null;
  sidebarCollapsed: boolean;
  theme: string | undefined;
}): PreferencesBundle {
  return {
    version: 1,
    exportedAt: new Date().toISOString(),
    preferences: input.preferences,
    workspace: {
      apiBaseUrl: input.apiBaseUrl,
      repoRoot: input.repoRoot,
      sidebarCollapsed: input.sidebarCollapsed,
    },
    theme: input.theme ?? null,
    recentRepos: getRecentRepositories(),
    featurePrefs: {
      reviewsView: readRaw(STORAGE_KEYS.reviewsView),
      recommendationsView: readRaw(STORAGE_KEYS.recommendationsView),
      docsFavorites: readRaw(STORAGE_KEYS.docsFavorites),
      docsRecent: readRaw(STORAGE_KEYS.docsRecent),
      docsNavCollapsed: readRaw(STORAGE_KEYS.docsNavCollapsed),
    },
  };
}

export function applyPreferencesBundle(
  bundle: PreferencesBundle,
  apply: {
    setPreferences: (p: UiPreferences) => void;
    setApiBaseUrl: (url: string) => void;
    setRepoRoot: (root: string | null) => void;
    setSidebarCollapsed: (v: boolean) => void;
    setTheme?: (theme: string) => void;
  },
): void {
  apply.setPreferences({ ...DEFAULT_PREFERENCES, ...bundle.preferences });
  apply.setApiBaseUrl(bundle.workspace.apiBaseUrl || DEFAULT_API_URL);
  apply.setRepoRoot(bundle.workspace.repoRoot);
  apply.setSidebarCollapsed(Boolean(bundle.workspace.sidebarCollapsed));
  if (bundle.theme && apply.setTheme) apply.setTheme(bundle.theme);
  writeRaw(STORAGE_KEYS.recentRepos, JSON.stringify(bundle.recentRepos ?? []));
  for (const [key, value] of Object.entries(bundle.featurePrefs ?? {})) {
    const storageKey =
      key === "reviewsView"
        ? STORAGE_KEYS.reviewsView
        : key === "recommendationsView"
          ? STORAGE_KEYS.recommendationsView
          : key === "docsFavorites"
            ? STORAGE_KEYS.docsFavorites
            : key === "docsRecent"
              ? STORAGE_KEYS.docsRecent
              : key === "docsNavCollapsed"
                ? STORAGE_KEYS.docsNavCollapsed
                : null;
    if (storageKey) writeRaw(storageKey, value);
  }
}

export function resetAllLocalSettings(apply: {
  setPreferences: (p: UiPreferences) => void;
  setApiBaseUrl: (url: string) => void;
  setRepoRoot: (root: string | null) => void;
  setSidebarCollapsed: (v: boolean) => void;
  setTheme?: (theme: string) => void;
}) {
  apply.setPreferences({ ...DEFAULT_PREFERENCES });
  apply.setApiBaseUrl(DEFAULT_API_URL);
  apply.setRepoRoot(null);
  apply.setSidebarCollapsed(false);
  apply.setTheme?.("system");
  const keys = Object.values(STORAGE_KEYS);
  for (const key of keys) writeRaw(key, null);
  writeRaw("theme", null);
}

export function applyDocumentPreferences(prefs: UiPreferences) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.dataset.accent = prefs.accent;
  root.dataset.density = prefs.compactMode ? "compact" : "comfortable";
  root.dataset.animations = prefs.animations ? "on" : "off";
  root.classList.toggle("debug-mode", prefs.debugMode);
}

export const UI_VERSION = "0.1.0";
export const UI_BUILD = "phase-10.11.5B";
export const UI_ENVIRONMENT =
  process.env.NODE_ENV === "production" ? "production" : "development";
