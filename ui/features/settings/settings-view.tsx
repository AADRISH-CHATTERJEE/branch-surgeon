"use client";

import Link from "next/link";
import * as React from "react";
import { useTheme } from "next-themes";
import { useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  Bell,
  Brain,
  Building2,
  Database,
  Download,
  HeartPulse,
  History,
  Info,
  Monitor,
  Moon,
  Palette,
  Settings2,
  Sun,
  Upload,
  Wrench,
} from "lucide-react";

import { MetricStrip } from "@/components/data-display/metric-strip";
import { StatusBadge } from "@/components/data-display/status-badge";
import { Unavailable } from "@/components/feedback/unavailable";
import { PageContainer } from "@/components/layout/page-container";
import { PageHeader } from "@/components/page-header";
import { SearchInput } from "@/components/search-input";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import { appToast } from "@/lib/app-toast";
import { DEFAULT_API_URL } from "@/lib/constants";
import {
  ACCENT_OPTIONS,
  applyPreferencesBundle,
  clearRecentRepositories,
  exportPreferencesBundle,
  HISTORY_RETENTION_OPTIONS,
  LANDING_PAGE_OPTIONS,
  resetAllLocalSettings,
  UI_BUILD,
  UI_ENVIRONMENT,
  UI_VERSION,
  type AccentColor,
  type LandingPage,
  type PreferencesBundle,
  type UiPreferences,
} from "@/lib/preferences";
import { cn } from "@/lib/utils";
import { usePreferences } from "@/providers/preferences-provider";
import { useRepoContext } from "@/providers/repo-context";
import { queryKeys } from "@/queries/keys";
import { useDocumentation } from "@/queries/use-documentation";
import { useApiHealth } from "@/queries/use-health";
import { useApplyHistoryRetention } from "@/queries/use-history";
import { useBuildIndex, useIndexStatus } from "@/queries/use-index";
import { useRepository, useRepositoryStatus } from "@/queries/use-repository";
import { useRules } from "@/queries/use-rules";
import { countLoadedDocs } from "@/features/documentation/lib/doc-catalog";
import { formatRelativeTime } from "@/lib/format";

import { ReadOnlyValue, SectionCard } from "./components/section-card";
import { PrefToggle, SettingRow } from "./components/setting-row";
import { SETTINGS_NAV, type SettingsSectionId } from "./lib/settings-nav";

const SECTION_ICONS: Record<SettingsSectionId, React.ComponentType<{ className?: string }>> = {
  workspace: Settings2,
  health: HeartPulse,
  ai: Brain,
  company: Building2,
  appearance: Palette,
  notifications: Bell,
  developer: Wrench,
  data: Database,
  about: Info,
  "import-export": Download,
};

const MANAGED = {
  emptyLabel: "Managed by Backend",
  emptyReason: "Configured on the Local API process (.env), not exposed as a UI setting.",
} as const;

export function SettingsView() {
  const {
    apiBaseUrl,
    setApiBaseUrl,
    repoRoot,
    setRepoRoot,
    sidebarCollapsed,
    setSidebarCollapsed,
  } = useRepoContext();
  const { preferences, setPreferences, updatePreference, resetPreferences } = usePreferences();
  const { theme, setTheme, resolvedTheme } = useTheme();
  const health = useApiHealth();
  const repo = useRepository();
  const status = useRepositoryStatus();
  const indexStatus = useIndexStatus();
  const buildIndex = useBuildIndex();
  const rules = useRules();
  const docs = useDocumentation();
  const qc = useQueryClient();
  const retentionMut = useApplyHistoryRetention();

  const [active, setActive] = React.useState<SettingsSectionId>("workspace");
  const [search, setSearch] = React.useState("");
  // null draft = follow hydrated RepoProvider values (avoids empty flash before hydrate).
  const [apiDraft, setApiDraft] = React.useState<string | null>(null);
  const [resetOpen, setResetOpen] = React.useState(false);
  const [importError, setImportError] = React.useState<string | null>(null);
  const [lastApiOkAt, setLastApiOkAt] = React.useState<number | null>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);

  const apiDraftValue = apiDraft ?? apiBaseUrl;

  // Workspace Save only tracks API URL — repository root is chosen in the app header.
  const dirty =
    apiDraftValue.trim().replace(/\/$/, "") !== apiBaseUrl.replace(/\/$/, "");

  React.useEffect(() => {
    if (health.isSuccess) setLastApiOkAt(Date.now());
  }, [health.isSuccess, health.dataUpdatedAt]);

  const visibleNav = React.useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return SETTINGS_NAV;
    return SETTINGS_NAV.filter(
      (item) =>
        item.label.toLowerCase().includes(q) ||
        item.keywords.some((k) => k.includes(q)),
    );
  }, [search]);

  const activeSection: SettingsSectionId =
    visibleNav.some((n) => n.id === active)
      ? active
      : (visibleNav[0]?.id ?? "workspace");

  const saveWorkspace = () => {
    const nextApi = apiDraftValue.trim().replace(/\/$/, "") || DEFAULT_API_URL;
    setApiBaseUrl(nextApi);
    setApiDraft(nextApi);
    appToast.success("Local API URL saved");
    void health.refetch();
    void qc.invalidateQueries({ queryKey: [...queryKeys.all, "repo"] });
  };

  const testConnection = async () => {
    const result = await health.refetch();
    if (result.isSuccess) {
      setLastApiOkAt(Date.now());
      appToast.success("Connected", `API ${result.data?.version ?? ""}`.trim());
    } else {
      appToast.error(
        "Connection failed",
        result.error instanceof Error ? result.error.message : "Local API unreachable",
      );
    }
  };

  const restoreDefaults = () => {
    resetPreferences();
    setTheme("system");
    appToast.message("Appearance & preference defaults restored");
  };

  const exportPrefs = () => {
    const bundle = exportPreferencesBundle({
      preferences,
      apiBaseUrl,
      repoRoot,
      sidebarCollapsed,
      theme,
    });
    const blob = new Blob([JSON.stringify(bundle, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `refactory-preferences-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    appToast.success("Preferences exported");
  };

  const onImportFile = async (file: File) => {
    setImportError(null);
    try {
      const text = await file.text();
      const parsed = JSON.parse(text) as PreferencesBundle;
      if (parsed.version !== 1 || !parsed.preferences || !parsed.workspace) {
        throw new Error("Unrecognized preferences bundle");
      }
      applyPreferencesBundle(parsed, {
        setPreferences,
        setApiBaseUrl,
        setRepoRoot,
        setSidebarCollapsed,
        setTheme,
      });
      setApiDraft(parsed.workspace.apiBaseUrl);
      appToast.success("Preferences imported");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Import failed";
      setImportError(msg);
      appToast.error(msg);
    }
  };

  const confirmResetAll = () => {
    resetAllLocalSettings({
      setPreferences,
      setApiBaseUrl,
      setRepoRoot,
      setSidebarCollapsed,
      setTheme,
    });
    setApiDraft(DEFAULT_API_URL);
    clearRecentRepositories();
    qc.clear();
    setResetOpen(false);
    appToast.success("All local settings reset");
  };

  const exportDiagnostics = () => {
    const payload = {
      exportedAt: new Date().toISOString(),
      ui: { version: UI_VERSION, build: UI_BUILD, environment: UI_ENVIRONMENT },
      workspace: { apiBaseUrl, repoRoot, sidebarCollapsed },
      preferences,
      theme: { theme, resolvedTheme },
      health: health.data ?? null,
      repository: repo.data ?? null,
      status: status.data ?? null,
      queryCacheSize: qc.getQueryCache().getAll().length,
      userAgent: typeof navigator !== "undefined" ? navigator.userAgent : null,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `refactory-diagnostics-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    appToast.success("Diagnostics exported");
  };

  const requestDesktopNotifications = async () => {
    if (typeof Notification === "undefined") {
      appToast.error("Desktop notifications are not supported in this browser");
      return;
    }
    const permission = await Notification.requestPermission();
    if (permission === "granted") {
      updatePreference("desktopNotifications", true);
      new Notification("Refactory", { body: "Desktop notifications enabled." });
      appToast.success("Desktop notifications enabled");
    } else {
      updatePreference("desktopNotifications", false);
      appToast.message("Notification permission denied");
    }
  };

  const loadedDocs = countLoadedDocs(docs.data);
  const ruleCount = rules.data?.rule_count ?? rules.data?.rules?.length ?? 0;

  return (
    <PageContainer variant="wide" className="space-y-4">
      <PageHeader
        title="Settings"
        description="Workspace connection, local preferences, and read-only Local API configuration."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {dirty ? (
              <StatusBadge label="Unsaved API URL" tone="warn" />
            ) : (
              <span className="text-xs text-muted-foreground">
                Preferences save automatically
              </span>
            )}
            <Button size="sm" variant="outline" onClick={restoreDefaults}>
              Restore defaults
            </Button>
            {dirty ? (
              <Button size="sm" onClick={saveWorkspace}>
                Save API URL
              </Button>
            ) : (
              <Button
                size="sm"
                variant="secondary"
                disabled
                title="Appearance and preference toggles save as you change them. Save appears only when the Local API URL is edited."
              >
                Settings are saved automatically
              </Button>
            )}
          </div>
        }
      />

      <MetricStrip
        items={[
          {
            key: "conn",
            label: "Connection",
            value: health.isSuccess ? "Online" : health.isLoading ? "…" : "Offline",
            variant: health.isSuccess ? "primary" : "danger",
          },
          {
            key: "api",
            label: "API version",
            value: health.data?.version ?? "—",
            hint: health.data?.service,
          },
          {
            key: "ai",
            label: "AI provider",
            value: status.data?.ai_provider ?? "—",
            hint: "GET /repository/status",
          },
          {
            key: "ui",
            label: "UI version",
            value: UI_VERSION,
            hint: UI_BUILD,
          },
        ]}
      />

      <div className="grid min-h-[min(70vh,48rem)] overflow-hidden rounded-lg border lg:grid-cols-[14rem_minmax(0,1fr)]">
        <aside className="border-b bg-card lg:border-r lg:border-b-0" aria-label="Settings categories">
          <div className="space-y-2 border-b p-3">
            <SearchInput
              value={search}
              onChange={setSearch}
              placeholder="Search settings…"
              id="settings-search"
            />
          </div>
          <ScrollArea className="h-[12rem] lg:h-[calc(100%-4.5rem)]">
            <nav className="sticky top-0 space-y-0.5 p-2">
              {visibleNav.map((item) => {
                const Icon = SECTION_ICONS[item.id];
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setActive(item.id)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm",
                      activeSection === item.id
                        ? "bg-accent text-accent-foreground"
                        : "hover:bg-muted/60",
                    )}
                    aria-current={activeSection === item.id ? "page" : undefined}
                  >
                    <Icon className="size-4 opacity-70" />
                    {item.label}
                  </button>
                );
              })}
              {!visibleNav.length ? (
                <p className="px-2 py-3 text-xs text-muted-foreground">No matching sections.</p>
              ) : null}
            </nav>
          </ScrollArea>
        </aside>

        <ScrollArea className="min-h-0">
          <div className="space-y-6 p-4 sm:p-6">
            {activeSection === "workspace" ? (
              <SectionCard
                title="Workspace"
                description="Local API connection and repository targeting. Persisted in localStorage."
              >
                <SettingRow
                  label="Connection health"
                  description="GET /health against the configured Local API URL."
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge
                      label={
                        health.isSuccess
                          ? "✓ Connected"
                          : health.isLoading
                            ? "Checking…"
                            : "Connection failed"
                      }
                      tone={
                        health.isSuccess ? "success" : health.isLoading ? "muted" : "danger"
                      }
                    />
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={health.isFetching}
                      onClick={() => void testConnection()}
                    >
                      {health.isFetching ? "Testing…" : "Test connection"}
                    </Button>
                    {preferences.apiInspector ? (
                      <Button size="sm" variant="ghost" asChild>
                        <a href={`${apiBaseUrl}/docs`} target="_blank" rel="noreferrer">
                          Open API docs
                        </a>
                      </Button>
                    ) : null}
                  </div>
                </SettingRow>

                <SettingRow
                  label="Local API URL"
                  description="Base URL for all Local API requests. Click Save API URL after editing."
                  help="Overrides NEXT_PUBLIC_REFACTORY_API_URL when set. Repository root is selected in the application header."
                  badge={{ label: "Local preference", tone: "info" }}
                >
                  <Input
                    id="settings-api-url"
                    value={apiDraftValue}
                    onChange={(e) => setApiDraft(e.target.value)}
                    placeholder={DEFAULT_API_URL}
                    className="font-mono text-sm"
                  />
                </SettingRow>

                <SettingRow
                  label="Active repository"
                  description="Resolved from GET /repository for the root selected in the app header."
                >
                  {repo.isLoading && !repo.data ? (
                    <div className="space-y-2">
                      <div className="h-4 w-40 animate-pulse rounded bg-muted" />
                      <div className="h-3 w-64 animate-pulse rounded bg-muted" />
                    </div>
                  ) : repo.data ? (
                    <div className="space-y-1 text-sm">
                      <p className="font-medium">{repo.data.name}</p>
                      <p className="font-mono text-xs text-muted-foreground">
                        {repo.data.root_path}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        Branch {repo.data.current_branch}
                        {repo.data.default_branch
                          ? ` · default ${repo.data.default_branch}`
                          : ""}
                      </p>
                    </div>
                  ) : (
                    <Unavailable
                      compact
                      title="Repository unavailable"
                      reason="Connect Local API and select a repository in the header."
                    />
                  )}
                </SettingRow>

                <SettingRow
                  label="Index status"
                  description="From GET /index/status and GET /repository/status."
                >
                  {(() => {
                    const idx = indexStatus.data as
                      | {
                          staleness?: {
                            is_stale?: boolean;
                            indexed_files?: number;
                            reason?: string;
                          };
                          last_index?: {
                            summary?: {
                              file_count?: number;
                              indexed_at?: string;
                              created_at?: string;
                            };
                            statistics?: { file_count?: number };
                          };
                        }
                      | undefined;
                    const stale = (status.data?.index_staleness ?? idx?.staleness) as
                      | {
                          is_stale?: boolean;
                          indexed_files?: number;
                          reason?: string;
                        }
                      | undefined;
                    const files =
                      stale?.indexed_files ??
                      idx?.last_index?.statistics?.file_count ??
                      idx?.last_index?.summary?.file_count;
                    const lastAt =
                      idx?.last_index?.summary?.indexed_at ||
                      idx?.last_index?.summary?.created_at;
                    const indexed = files != null && Number(files) > 0;
                    return (
                      <div className="space-y-2">
                        <div className="flex flex-wrap gap-2">
                          <StatusBadge
                            label={indexed ? "Repository Indexed" : "Not Indexed"}
                            tone={indexed ? "success" : "warn"}
                          />
                          <StatusBadge
                            label={
                              stale?.is_stale
                                ? "Stale"
                                : indexed
                                  ? "Up to date"
                                  : "Unknown"
                            }
                            tone={stale?.is_stale ? "warn" : indexed ? "success" : "muted"}
                          />
                          {status.data ? (
                            <StatusBadge
                              label={status.data.cache_enabled ? "Cache on" : "Cache off"}
                              tone={status.data.cache_enabled ? "success" : "muted"}
                            />
                          ) : null}
                        </div>
                        <dl className="grid gap-1 text-xs text-muted-foreground sm:grid-cols-2">
                          <div>
                            Files indexed:{" "}
                            <span className="text-foreground">{files ?? "Not Available"}</span>
                          </div>
                          <div>
                            Last index:{" "}
                            <span className="text-foreground">
                              {lastAt ? formatRelativeTime(lastAt) : "Not Available"}
                            </span>
                          </div>
                        </dl>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={buildIndex.isPending}
                          onClick={() => buildIndex.mutate(true)}
                        >
                          {buildIndex.isPending ? "Re-indexing…" : "Re-index repository"}
                        </Button>
                      </div>
                    );
                  })()}
                </SettingRow>
              </SectionCard>
            ) : null}

            {activeSection === "health" ? (
              <SectionCard
                title="UI Health"
                description="Frontend and Local API runtime signals for this session."
              >
                <SettingRow label="Frontend Version">
                  <ReadOnlyValue value={`${UI_VERSION} (${UI_BUILD})`} />
                </SettingRow>
                <SettingRow label="Backend Version">
                  <ReadOnlyValue
                    value={health.data?.version}
                    emptyLabel="Not Available"
                    emptyReason="GET /health did not return a version."
                  />
                </SettingRow>
                <SettingRow label="API Reachability">
                  <StatusBadge
                    label={
                      health.isSuccess
                        ? "✓ Connected"
                        : health.isLoading
                          ? "Checking…"
                          : "Connection failed"
                    }
                    tone={health.isSuccess ? "success" : health.isLoading ? "muted" : "danger"}
                  />
                </SettingRow>
                <SettingRow label="Current Provider">
                  <ReadOnlyValue value={status.data?.ai_provider} {...MANAGED} />
                </SettingRow>
                <SettingRow label="Current Model">
                  <ReadOnlyValue value={status.data?.ai_model} {...MANAGED} />
                </SettingRow>
                <SettingRow label="Last Successful API Call">
                  <ReadOnlyValue
                    value={
                      lastApiOkAt
                        ? formatRelativeTime(new Date(lastApiOkAt).toISOString())
                        : null
                    }
                    emptyLabel="Not Available"
                    emptyReason="No successful GET /health in this session yet."
                  />
                </SettingRow>
                <SettingRow label="Backend Uptime">
                  <ReadOnlyValue
                    value={null}
                    emptyLabel="Not Available"
                    emptyReason="Local API does not expose an uptime field."
                  />
                </SettingRow>
                <div className="pt-2">
                  <Button size="sm" variant="outline" onClick={() => void testConnection()}>
                    <Activity className="size-3.5" />
                    Refresh health
                  </Button>
                </div>
              </SectionCard>
            ) : null}

            {activeSection === "ai" ? (
              <SectionCard
                title="AI"
                description="Provider configuration is owned by the Local API process (.env). UI is read-only."
              >
                <SettingRow
                  label="Provider"
                  badge={{ label: "Managed by Backend", tone: "warn" }}
                  help="From GET /repository/status → ai_provider"
                >
                  <ReadOnlyValue value={status.data?.ai_provider} {...MANAGED} />
                </SettingRow>
                <SettingRow
                  label="Model"
                  badge={{ label: "Managed by Backend", tone: "warn" }}
                >
                  <ReadOnlyValue value={status.data?.ai_model} {...MANAGED} />
                </SettingRow>
                <SettingRow
                  label="Temperature"
                  badge={{ label: "Managed by Backend", tone: "warn" }}
                  description="Engine defaults live in Python providers."
                >
                  <ReadOnlyValue value={null} {...MANAGED} />
                </SettingRow>
                <SettingRow
                  label="Max Tokens"
                  badge={{ label: "Managed by Backend", tone: "warn" }}
                  description="PROMPT_MAX_TOKENS is process env on the Local API."
                >
                  <ReadOnlyValue value={null} {...MANAGED} />
                </SettingRow>
                <SettingRow
                  label="Context Size"
                  badge={{ label: "Managed by Backend", tone: "warn" }}
                >
                  <ReadOnlyValue value={null} {...MANAGED} />
                </SettingRow>
                <SettingRow
                  label="Streaming"
                  badge={{ label: "Managed by Backend", tone: "warn" }}
                  description="Local API review/recommend responses are non-streaming JSON."
                >
                  <ReadOnlyValue value="Disabled (JSON responses)" />
                </SettingRow>
                <SettingRow
                  label="Prompt Version"
                  badge={{ label: "Managed by Backend", tone: "warn" }}
                >
                  <ReadOnlyValue value={null} {...MANAGED} />
                </SettingRow>
              </SectionCard>
            ) : null}

            {activeSection === "company" ? (
              <SectionCard
                title="Company Policies"
                description="Organization rules are persisted in SQLite and edited in Rules Center. Built-in rules remain read-only repository files."
              >
                <SettingRow
                  label="Organization rules"
                  badge={{ label: "Editable", tone: "success" }}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge
                      label={
                        rules.isSuccess
                          ? `${rules.data?.organization_rule_count ?? 0} org policies`
                          : "Unavailable"
                      }
                      tone={rules.isSuccess ? "success" : "muted"}
                    />
                    <Button size="sm" variant="outline" asChild>
                      <Link href="/rules">Open Organization Rules</Link>
                    </Button>
                  </div>
                </SettingRow>
                <SettingRow label="Built-in rules" badge={{ label: "Read-only", tone: "info" }}>
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge
                      label={rules.isSuccess ? `${ruleCount} built-in` : "Unavailable"}
                      tone={rules.isSuccess ? "success" : "muted"}
                    />
                    <Button size="sm" variant="outline" asChild>
                      <Link href="/rules">Open Rules Center</Link>
                    </Button>
                  </div>
                </SettingRow>
                <SettingRow
                  label="Documentation status"
                  badge={{ label: "Repository files", tone: "info" }}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge
                      label={docs.isSuccess ? `${loadedDocs}/4 loaded` : "Unavailable"}
                      tone={loadedDocs > 0 ? "success" : "muted"}
                    />
                    <Button size="sm" variant="outline" asChild>
                      <Link href="/documentation">Open Documentation</Link>
                    </Button>
                  </div>
                </SettingRow>
                {(
                  [
                    ["Architecture", "architecture", "/documentation?doc=architecture"],
                    ["Coding standards", "coding_guidelines", "/documentation?doc=coding_guidelines"],
                    ["Security", "security_guidelines", "/documentation?doc=security_guidelines"],
                    ["Testing", "testing_guidelines", "/documentation?doc=testing_guidelines"],
                  ] as const
                ).map(([label, key, href]) => {
                  const ok = Boolean(docs.data?.[key]?.trim());
                  return (
                    <SettingRow key={key} label={label}>
                      <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge
                          label={ok ? "Present" : "Missing"}
                          tone={ok ? "success" : "warn"}
                        />
                        <Button size="sm" variant="ghost" asChild>
                          <Link href={href}>View</Link>
                        </Button>
                      </div>
                    </SettingRow>
                  );
                })}
              </SectionCard>
            ) : null}

            {activeSection === "appearance" ? (
              <SectionCard
                title="Appearance"
                description="Client-only presentation preferences. Theme uses next-themes."
              >
                <SettingRow label="Theme" badge={{ label: "Local preference", tone: "info" }}>
                  <div className="flex flex-wrap gap-2">
                    {(
                      [
                        ["system", "System", Monitor],
                        ["light", "Light", Sun],
                        ["dark", "Dark", Moon],
                      ] as const
                    ).map(([value, label, Icon]) => (
                      <Button
                        key={value}
                        size="sm"
                        variant={theme === value ? "secondary" : "outline"}
                        onClick={() => setTheme(value)}
                      >
                        <Icon className="size-4" />
                        {label}
                      </Button>
                    ))}
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">
                    Resolved: {resolvedTheme ?? "—"}
                  </p>
                </SettingRow>

                <SettingRow
                  label="Accent color"
                  description="Client-only token override."
                  badge={{ label: "Local preference", tone: "info" }}
                >
                  <Select
                    value={preferences.accent}
                    onValueChange={(v) => updatePreference("accent", v as AccentColor)}
                  >
                    <SelectTrigger className="max-w-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ACCENT_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </SettingRow>

                <SettingRow label="Compact mode" badge={{ label: "Local preference", tone: "info" }}>
                  <PrefToggle
                    label="Compact mode"
                    checked={preferences.compactMode}
                    onChange={(v) => updatePreference("compactMode", v)}
                  />
                </SettingRow>

                <SettingRow
                  label="Sidebar collapsed"
                  description="Current sidebar state (also toggleable from the sidebar)."
                  badge={{ label: "Local preference", tone: "info" }}
                >
                  <PrefToggle
                    label="Sidebar collapsed"
                    checked={sidebarCollapsed}
                    onChange={setSidebarCollapsed}
                  />
                </SettingRow>

                <SettingRow
                  label="Sidebar auto-collapse hint"
                  description="Stored preference for future responsive behavior. Does not force collapse today."
                  badge={{ label: "Local preference", tone: "info" }}
                >
                  <PrefToggle
                    label="Sidebar auto-collapse"
                    checked={preferences.sidebarAutoCollapse}
                    onChange={(v) => updatePreference("sidebarAutoCollapse", v)}
                  />
                </SettingRow>

                <SettingRow
                  label="Default landing page"
                  description="Used when opening the app root (/)."
                  badge={{ label: "Local preference", tone: "info" }}
                >
                  <Select
                    value={preferences.landingPage}
                    onValueChange={(v) => updatePreference("landingPage", v as LandingPage)}
                  >
                    <SelectTrigger className="max-w-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {LANDING_PAGE_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </SettingRow>

                <SettingRow label="Animations" badge={{ label: "Local preference", tone: "info" }}>
                  <PrefToggle
                    label="Animations"
                    checked={preferences.animations}
                    onChange={(v) => updatePreference("animations", v)}
                  />
                </SettingRow>
              </SectionCard>
            ) : null}

            {activeSection === "notifications" ? (
              <SectionCard
                title="Notifications"
                description="Toast behavior is client-side (sonner). There is no notification center API."
              >
                <SettingRow
                  label="Toast duration"
                  badge={{ label: "Local preference", tone: "info" }}
                >
                  <div className="flex max-w-xs items-center gap-3">
                    <Input
                      type="number"
                      min={1000}
                      max={15000}
                      step={500}
                      value={preferences.toastDurationMs}
                      onChange={(e) =>
                        updatePreference(
                          "toastDurationMs",
                          Math.min(15000, Math.max(1000, Number(e.target.value) || 4000)),
                        )
                      }
                    />
                    <span className="text-xs text-muted-foreground">ms</span>
                  </div>
                </SettingRow>
                <SettingRow label="Success toasts" badge={{ label: "Local preference", tone: "info" }}>
                  <PrefToggle
                    label="Success toasts"
                    checked={preferences.toastSuccess}
                    onChange={(v) => updatePreference("toastSuccess", v)}
                  />
                </SettingRow>
                <SettingRow label="Warning toasts" badge={{ label: "Local preference", tone: "info" }}>
                  <PrefToggle
                    label="Warning toasts"
                    checked={preferences.toastWarnings}
                    onChange={(v) => updatePreference("toastWarnings", v)}
                  />
                </SettingRow>
                <SettingRow label="Error toasts" badge={{ label: "Local preference", tone: "info" }}>
                  <PrefToggle
                    label="Error toasts"
                    checked={preferences.toastErrors}
                    onChange={(v) => updatePreference("toastErrors", v)}
                  />
                </SettingRow>
                <SettingRow
                  label="Desktop notifications"
                  description="Browser Notification API only — no backend push."
                  badge={{ label: "Client capability", tone: "info" }}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <PrefToggle
                      label="Desktop notifications"
                      checked={preferences.desktopNotifications}
                      onChange={(v) => {
                        if (v) void requestDesktopNotifications();
                        else updatePreference("desktopNotifications", false);
                      }}
                    />
                    <Button size="sm" variant="outline" onClick={() => void requestDesktopNotifications()}>
                      Request permission
                    </Button>
                  </div>
                </SettingRow>
              </SectionCard>
            ) : null}

            {activeSection === "developer" ? (
              <SectionCard
                title="Developer"
                description="Local diagnostics and experimental client flags."
              >
                <SettingRow label="Debug mode" badge={{ label: "Local preference", tone: "info" }}>
                  <PrefToggle
                    label="Debug mode"
                    checked={preferences.debugMode}
                    onChange={(v) => updatePreference("debugMode", v)}
                  />
                </SettingRow>
                <SettingRow
                  label="API inspector"
                  description="Shows a shortcut to Local API OpenAPI docs when connected."
                  badge={{ label: "Local preference", tone: "info" }}
                >
                  <PrefToggle
                    label="API inspector"
                    checked={preferences.apiInspector}
                    onChange={(v) => updatePreference("apiInspector", v)}
                  />
                </SettingRow>
                <SettingRow label="React Query cache">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge
                      label={`${qc.getQueryCache().getAll().length} queries`}
                      tone="muted"
                    />
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        qc.clear();
                        appToast.success("React Query cache cleared");
                      }}
                    >
                      Clear cache
                    </Button>
                  </div>
                </SettingRow>
                <SettingRow label="Export diagnostics">
                  <Button size="sm" variant="outline" onClick={exportDiagnostics}>
                    <Download className="size-4" />
                    Download JSON
                  </Button>
                </SettingRow>
                <SettingRow
                  label="Reset preferences"
                  description="Resets appearance/notification/developer prefs only (not API URL)."
                >
                  <Button size="sm" variant="outline" onClick={restoreDefaults}>
                    Reset preferences
                  </Button>
                </SettingRow>
                <SettingRow
                  label="Experimental features"
                  description="Reserved client flag. No experimental surfaces are gated yet."
                  badge={{ label: "Local preference", tone: "info" }}
                >
                  <PrefToggle
                    label="Experimental features"
                    checked={preferences.experimentalFeatures}
                    onChange={(v) => updatePreference("experimentalFeatures", v)}
                  />
                </SettingRow>
              </SectionCard>
            ) : null}

            {activeSection === "data" ? (
              <SectionCard
                title="Data & History"
                description="Retention for Analysis History. Activity runs are unaffected. Applying a finite policy deletes older history rows for the current repository."
              >
                <SettingRow
                  label="History retention"
                  description="Unlimited keeps every analysis. Choosing 30 / 90 / 365 days purges older entries when applied."
                  badge={{ label: "Local API", tone: "warn" }}
                  help="Preference is stored locally; Apply Retention calls POST /history/retention."
                >
                  <div className="flex max-w-md flex-wrap items-center gap-2">
                    <Select
                      value={String(preferences.historyRetentionDays)}
                      onValueChange={(v) =>
                        updatePreference(
                          "historyRetentionDays",
                          Number(v) as UiPreferences["historyRetentionDays"],
                        )
                      }
                    >
                      <SelectTrigger className="max-w-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {HISTORY_RETENTION_OPTIONS.map((opt) => (
                          <SelectItem key={opt.value} value={String(opt.value)}>
                            {opt.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={retentionMut.isPending}
                      onClick={() => {
                        const days = preferences.historyRetentionDays;
                        retentionMut.mutate(days === 0 ? null : days);
                      }}
                    >
                      <History className="size-4" />
                      Apply retention
                    </Button>
                  </div>
                </SettingRow>
                <SettingRow label="Open History">
                  <Button size="sm" variant="outline" asChild>
                    <Link href="/history">History timeline</Link>
                  </Button>
                </SettingRow>
              </SectionCard>
            ) : null}

            {activeSection === "about" ? (
              <SectionCard title="About" description="Build identity and useful links.">
                <SettingRow label="UI version">
                  <ReadOnlyValue value={UI_VERSION} />
                </SettingRow>
                <SettingRow label="Build">
                  <ReadOnlyValue value={UI_BUILD} />
                </SettingRow>
                <SettingRow label="Environment">
                  <ReadOnlyValue value={UI_ENVIRONMENT} />
                </SettingRow>
                <SettingRow label="Local API URL">
                  <ReadOnlyValue value={apiBaseUrl} mono />
                </SettingRow>
                <SettingRow
                  label="Backend URL"
                  badge={{ label: "Managed by Backend", tone: "warn" }}
                  help="Control-plane URL from GET /repository/status → backend_url"
                >
                  <ReadOnlyValue value={status.data?.backend_url} mono />
                </SettingRow>
                <SettingRow label="Local API version">
                  <ReadOnlyValue
                    value={
                      health.data
                        ? `${health.data.service} ${health.data.version}`
                        : null
                    }
                  />
                </SettingRow>
                <SettingRow label="Links">
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="outline" asChild>
                      <Link href="/documentation">Documentation</Link>
                    </Button>
                    <Button size="sm" variant="outline" asChild>
                      <a
                        href="https://github.com"
                        target="_blank"
                        rel="noreferrer"
                      >
                        GitHub
                      </a>
                    </Button>
                    <Button size="sm" variant="outline" disabled>
                      License (unavailable)
                    </Button>
                  </div>
                </SettingRow>
              </SectionCard>
            ) : null}

            {activeSection === "import-export" ? (
              <SectionCard
                title="Import / Export"
                description="Backup and restore client preferences. Does not modify Local API process config."
              >
                <SettingRow label="Export preferences">
                  <Button size="sm" onClick={exportPrefs}>
                    <Download className="size-4" />
                    Export JSON
                  </Button>
                </SettingRow>
                <SettingRow label="Import preferences">
                  <div className="space-y-2">
                    <input
                      ref={fileRef}
                      type="file"
                      accept="application/json,.json"
                      className="hidden"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) void onImportFile(file);
                        e.target.value = "";
                      }}
                    />
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => fileRef.current?.click()}
                    >
                      <Upload className="size-4" />
                      Import JSON
                    </Button>
                    {importError ? (
                      <p className="text-xs text-destructive">{importError}</p>
                    ) : null}
                  </div>
                </SettingRow>
                <SettingRow
                  label="Reset all settings"
                  description="Clears localStorage preferences, workspace connection, theme, and React Query cache."
                  badge={{ label: "Destructive", tone: "danger" }}
                >
                  <Button size="sm" variant="destructive" onClick={() => setResetOpen(true)}>
                    Reset all…
                  </Button>
                </SettingRow>
              </SectionCard>
            ) : null}
          </div>
        </ScrollArea>
      </div>

      <Dialog open={resetOpen} onOpenChange={setResetOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reset all local settings?</DialogTitle>
            <DialogDescription>
              This clears API URL, repository root, theme, preferences, recent repos, and
              feature view modes from localStorage. Local API process configuration is not
              changed.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setResetOpen(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={confirmResetAll}>
              Reset everything
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageContainer>
  );
}

