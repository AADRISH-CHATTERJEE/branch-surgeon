"use client";

import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";

import { DataTable } from "@/components/data-display/data-table";
import { DistributionChart } from "@/components/data-display/distribution-chart";
import { MetricStrip } from "@/components/data-display/metric-strip";
import { StatusBadge } from "@/components/data-display/status-badge";
import { EmptyState } from "@/components/feedback/empty-state";
import { ErrorState } from "@/components/feedback/error-state";
import { FilterBar } from "@/components/filter-bar";
import { PageContainer } from "@/components/layout/page-container";
import { PageHeader } from "@/components/page-header";
import { SearchInput } from "@/components/search-input";
import { DetailDrawer } from "@/components/shared/detail-drawer";
import { DetailSection } from "@/components/shared/detail-section";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatRelativeTime } from "@/lib/format";
import { useListFilters } from "@/hooks/use-list-filters";
import { useActivity } from "@/queries/use-activity";
import { useDocumentation } from "@/queries/use-documentation";
import { useRules, useRulesCheck } from "@/queries/use-rules";
import { ApiError } from "@/services/errors";
import type { RuleItem, RulesCheckResult, RuleViolation } from "@/types/domain";

import {
  blockingDistribution,
  categoryBucketCounts,
  checkStatusDistribution,
  countByField,
  outcomeTone,
} from "./lib/rule-stats";
import { OrganizationRulesPanel } from "./organization-rules-panel";

export function RulesView() {
  const rulesQuery = useRules();
  const check = useRulesCheck();
  const docs = useDocumentation();
  const activity = useActivity({ limit: 50, command: "rules-check" });

  const [catalogTab, setCatalogTab] = React.useState<"organization" | "builtin">(
    "organization",
  );
  const [result, setResult] = React.useState<RulesCheckResult | null>(null);
  const [detailsExpanded, setDetailsExpanded] = React.useState(true);
  const { filters, setSearch, setCategory, setSeverity, setExtra } = useListFilters();
  const q = filters.search;
  const category = filters.category;
  const severity = filters.severity;
  const blocking = filters.extra.blocking ?? null;
  const setBlocking = (v: string | null) => setExtra("blocking", v);
  const [expanded, setExpanded] = React.useState<string | null>(null);
  const [drawerRule, setDrawerRule] = React.useState<RuleItem | null>(null);
  const [selectedViolation, setSelectedViolation] = React.useState<RuleViolation | null>(
    null,
  );

  const builtinList = React.useMemo(
    () => rulesQuery.data?.builtin_rules ?? rulesQuery.data?.rules ?? [],
    [rulesQuery.data?.builtin_rules, rulesQuery.data?.rules],
  );
  const orgList = React.useMemo(
    () => rulesQuery.data?.organization_rules ?? [],
    [rulesQuery.data?.organization_rules],
  );
  const ruleList = catalogTab === "builtin" ? builtinList : orgList;
  const standards = rulesQuery.data?.standards ?? null;
  const buckets = React.useMemo(() => categoryBucketCounts(ruleList), [ruleList]);

  const categories = React.useMemo(() => {
    const set = new Set(ruleList.map((r) => r.category).filter(Boolean));
    return [...set].sort().map((v) => ({ value: v, label: v }));
  }, [ruleList]);

  const severities = React.useMemo(() => {
    const set = new Set(ruleList.map((r) => r.severity).filter(Boolean));
    return [...set].sort().map((v) => ({ value: v, label: v }));
  }, [ruleList]);

  const filtered = React.useMemo(() => {
    return ruleList.filter((r) => {
      if (category && r.category !== category) return false;
      if (severity && r.severity !== severity) return false;
      if (blocking === "blocking" && !r.blocking) return false;
      if (blocking === "advisory" && r.blocking) return false;
      if (q) {
        const hay = `${r.name} ${r.category} ${r.message}`.toLowerCase();
        if (!hay.includes(q.toLowerCase())) return false;
      }
      return true;
    });
  }, [ruleList, category, severity, blocking, q]);

  const expandedRule = React.useMemo(
    () => filtered.find((r) => r.name === expanded) ?? null,
    [filtered, expanded],
  );

  const latestEval = activity.data?.[0] ?? null;

  const latestPersistedEval = React.useMemo(() => {
    if (!latestEval) return null;
    const data =
      latestEval.result_data && typeof latestEval.result_data === "object"
        ? (latestEval.result_data as Record<string, unknown>)
        : {};
    const outcome =
      (typeof data.outcome === "string" && data.outcome) ||
      latestEval.status ||
      "unknown";
    const summary =
      (typeof data.summary === "string" && data.summary) ||
      `Rules check · ${formatRelativeTime(latestEval.created_at)}`;
    return { outcome, summary, created_at: latestEval.created_at };
  }, [latestEval]);

  const groupedViolations = React.useMemo(() => {
    const violations = result?.violations ?? [];
    // Align with API gate semantics: BLOCK = blocking flag only.
    // Severity "error" with blocking=false is advisory → WARN, not BLOCK.
    return {
      blocking: violations.filter((v) => v.blocking),
      warning: violations.filter(
        (v) =>
          !v.blocking &&
          (v.severity === "warning" ||
            v.severity === "error" ||
            v.severity === "critical"),
      ),
      info: violations.filter(
        (v) =>
          !v.blocking &&
          v.severity !== "warning" &&
          v.severity !== "error" &&
          v.severity !== "critical",
      ),
    };
  }, [result]);

  const hasDocs = Boolean(
    docs.data?.architecture ||
      docs.data?.coding_guidelines ||
      docs.data?.security_guidelines ||
      docs.data?.testing_guidelines,
  );

  const runCheck = () => {
    check.mutate(
      {},
      {
        onSuccess: (data) => {
          setResult(data);
          setDetailsExpanded(true);
        },
      },
    );
  };

  const copyResults = async () => {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(result, null, 2));
      toast.success("Results copied");
    } catch {
      toast.error("Could not copy results");
    }
  };

  const downloadResults = () => {
    if (!result) return;
    const blob = new Blob([JSON.stringify(result, null, 2)], {
      type: "application/json;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `rules-check-${result.outcome || "result"}.json`;
    a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
  };

  const metricItems = React.useMemo(
    () => [
      {
        key: "pass",
        label: "PASS",
        value: result?.outcome?.toUpperCase() === "PASS" ? "Yes" : result ? "—" : "—",
        hint: result ? `Outcome ${result.outcome}` : "Run check",
        variant:
          result?.outcome?.toUpperCase() === "PASS"
            ? ("primary" as const)
            : ("default" as const),
      },
      {
        key: "warn",
        label: "WARN",
        value: result?.warning_count ?? "—",
        variant: "warn" as const,
      },
      {
        key: "block",
        label: "BLOCK",
        value: result?.blocker_count ?? "—",
        variant: "danger" as const,
      },
      { key: "count", label: "Rule count", value: ruleList.length },
      {
        key: "company",
        label: "Company",
        value: buckets.company,
        hint: "branch/commit/PR",
      },
      { key: "architecture", label: "Architecture", value: buckets.architecture },
      { key: "security", label: "Security", value: buckets.security },
      { key: "testing", label: "Testing", value: buckets.testing },
    ],
    [result, ruleList.length, buckets],
  );

  return (
    <PageContainer className="space-y-6">
      <PageHeader
        title="Rules Center"
        description="Organization policies and built-in rules — additive company standards for reviews, recommendations, and Branch Surgeon."
        actions={
          <Button size="sm" disabled={check.isPending} onClick={runCheck}>
            Run Rule Check
          </Button>
        }
      />

      <MetricStrip items={metricItems} />

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Latest evaluation</CardTitle>
          <CardDescription>
            From session check result and GET /activity?command=rules-check when persisted
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3 text-sm">
          {result ? (
            <>
              <StatusBadge label={result.outcome} tone={outcomeTone(result.outcome)} />
              <span className="text-muted-foreground">{result.summary}</span>
              <span className="text-2xs text-muted-foreground">This session</span>
            </>
          ) : latestPersistedEval ? (
            <>
              <StatusBadge
                label={latestPersistedEval.outcome}
                tone={outcomeTone(latestPersistedEval.outcome)}
              />
              <span className="text-muted-foreground">{latestPersistedEval.summary}</span>
              <span className="text-2xs text-muted-foreground">
                Latest persisted evaluation ·{" "}
                {formatRelativeTime(latestPersistedEval.created_at)}
              </span>
            </>
          ) : (
            <span className="text-muted-foreground">
              No rules evaluation yet. Run a rule check to see PASS / WARN / BLOCK.
            </span>
          )}
        </CardContent>
      </Card>

      <section className="grid gap-3 lg:grid-cols-4">
        <DistributionChart
          title="By severity"
          items={countByField(ruleList, "severity")}
          variant="stack"
        />
        <DistributionChart
          title="By category"
          items={countByField(ruleList, "category").slice(0, 8)}
          variant="bar"
        />
        <DistributionChart
          title="Blocking vs advisory"
          items={blockingDistribution(ruleList)}
          variant="stack"
        />
        <DistributionChart
          title="Last check status"
          items={checkStatusDistribution(result)}
          variant="bar"
          emptyLabel="Run POST /rules/check to populate"
        />
      </section>

      <Card>
        <CardHeader className="pb-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <CardTitle className="text-base">Rule Check Workspace</CardTitle>
              <CardDescription>POST /rules/check → PASS / WARN / BLOCK</CardDescription>
            </div>
            <Button size="sm" variant="outline" disabled={check.isPending} onClick={runCheck}>
              {check.isPending ? "Checking…" : "Evaluate"}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {!result ? (
            <EmptyState
              className="py-10"
              title="No evaluation yet"
              description="Run a rules check against the current git context."
              actionLabel="Run Rule Check"
              onAction={runCheck}
            />
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge label={result.outcome} tone={outcomeTone(result.outcome)} />
                <span className="text-sm text-muted-foreground">
                  Blocking {result.blocker_count} · Warnings {result.warning_count}
                </span>
                <div className="ml-auto flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={() => void copyResults()}>
                    Copy Results
                  </Button>
                  <Button size="sm" variant="outline" onClick={downloadResults}>
                    Download Results
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setDetailsExpanded((v) => !v)}
                  >
                    {detailsExpanded ? "Collapse Details" : "Expand Details"}
                  </Button>
                </div>
              </div>
              <p className="text-sm text-muted-foreground whitespace-pre-wrap">
                {result.summary}
              </p>
              {detailsExpanded
                ? (
                    [
                      ["BLOCK", groupedViolations.blocking],
                      ["WARN", groupedViolations.warning],
                      ["INFO", groupedViolations.info],
                    ] as const
                  ).map(([label, items]) => (
                    <div key={label}>
                      <h3 className="mb-2 text-sm font-medium">
                        {label} ({items.length})
                      </h3>
                      {!items.length ? (
                        <p className="text-xs text-muted-foreground">None</p>
                      ) : (
                        <ul className="space-y-2">
                          {items.map((v, i) => (
                            <li key={`${v.rule}-${i}`}>
                              <button
                                type="button"
                                onClick={() => setSelectedViolation(v)}
                                className="w-full rounded-md border p-3 text-left text-sm hover:bg-muted/40"
                              >
                                <div className="flex flex-wrap gap-2">
                                  <StatusBadge label={v.severity} />
                                  {v.blocking ? (
                                    <StatusBadge label="blocking" tone="danger" />
                                  ) : null}
                                  <StatusBadge
                                    label={
                                      v.source === "organization"
                                        ? "Organization"
                                        : "Built-in"
                                    }
                                    tone={
                                      v.source === "organization" ? "info" : "muted"
                                    }
                                  />
                                  <span className="font-medium">{v.rule}</span>
                                </div>
                                <p className="mt-1 text-muted-foreground">{v.message}</p>
                                {v.file_path ? (
                                  <p className="mt-1 font-mono text-xs">{v.file_path}</p>
                                ) : null}
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))
                : null}
            </div>
          )}
        </CardContent>
      </Card>

      <Tabs
        value={catalogTab}
        onValueChange={(v) => setCatalogTab(v as "organization" | "builtin")}
      >
        <TabsList>
          <TabsTrigger value="organization">
            Organization Rules ({orgList.length})
          </TabsTrigger>
          <TabsTrigger value="builtin">Built-in Rules ({builtinList.length})</TabsTrigger>
        </TabsList>

        <TabsContent value="organization" className="space-y-3">
          <OrganizationRulesPanel />
        </TabsContent>

        <TabsContent value="builtin" className="space-y-3">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
            <SearchInput
              className="lg:max-w-xs"
              value={q}
              onChange={setSearch}
              placeholder="Search built-in rules…"
            />
            <FilterBar
              options={categories}
              value={category}
              onChange={setCategory}
              allLabel="All categories"
            />
            <FilterBar
              options={severities}
              value={severity}
              onChange={setSeverity}
              allLabel="All severities"
            />
            <FilterBar
              options={[
                { value: "blocking", label: "Blocking" },
                { value: "advisory", label: "Advisory" },
              ]}
              value={blocking}
              onChange={setBlocking}
              allLabel="All modes"
            />
          </div>

          {rulesQuery.isError ? (
            <ErrorState
              title="Could not load rules"
              description={
                rulesQuery.error instanceof ApiError ? rulesQuery.error.message : undefined
              }
              onRetry={() => void rulesQuery.refetch()}
            />
          ) : (
            <>
              <DataTable
                columns={[
                  {
                    id: "name",
                    header: "Name",
                    className: "font-medium",
                    cell: (r) => r.name,
                  },
                  {
                    id: "category",
                    header: "Category",
                    cell: (r) => r.category,
                  },
                  {
                    id: "severity",
                    header: "Severity",
                    cell: (r) => <StatusBadge label={r.severity} />,
                  },
                  {
                    id: "blocking",
                    header: "Blocking",
                    cell: (r) => (r.blocking ? "Yes" : "No"),
                  },
                  {
                    id: "source",
                    header: "Source",
                    cell: () => <StatusBadge label="Built-in" tone="muted" />,
                  },
                  {
                    id: "enabled",
                    header: "Enabled",
                    cell: (r) => (
                      <StatusBadge
                        label={r.enabled === false ? "disabled" : "enabled"}
                        tone={r.enabled === false ? "muted" : "success"}
                      />
                    ),
                  },
                ]}
                data={filtered}
                getRowId={(r) => r.name}
                onRowClick={(r) => setExpanded(expanded === r.name ? null : r.name)}
                selectedId={expanded}
                isLoading={rulesQuery.isLoading}
                emptyTitle="No rules match"
                emptyDescription={
                  rulesQuery.data?.rules_error ||
                  "Adjust filters or add .refactory/rules.yaml."
                }
              />

              {expandedRule ? (
                <div className="rounded-lg border bg-muted/20 p-3">
                  <p className="text-sm text-muted-foreground">
                    {expandedRule.message || expandedRule.description || "No description."}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setDrawerRule(expandedRule)}
                    >
                      Open details
                    </Button>
                  </div>
                  <p className="mt-2 text-2xs text-muted-foreground">
                    Built-in rules are read-only. Edit organization policies in the Organization
                    Rules tab.
                  </p>
                </div>
              ) : null}
            </>
          )}
        </TabsContent>
      </Tabs>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Company Standards</CardTitle>
          <CardDescription>
            From GET /rules standards (company.yaml and/or organization rules).
            Markdown docs under .refactory/ are optional.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {standards && Object.keys(standards).length ? (
            <div className="grid gap-2 sm:grid-cols-2">
              <StandardChip
                label="Organization"
                value={String(
                  (standards as { organization_name?: string }).organization_name ?? "—",
                )}
                hint={
                  typeof (standards as { standards_source?: string }).standards_source ===
                  "string"
                    ? `Source: ${(standards as { standards_source?: string }).standards_source}`
                    : undefined
                }
              />
              <StandardChip
                label="Branch policy"
                value={policyChipLabel((standards as { branch?: unknown }).branch)}
                hint={policyChipHint((standards as { branch?: unknown }).branch)}
              />
              <StandardChip
                label="Commit policy"
                value={policyChipLabel((standards as { commit?: unknown }).commit)}
                hint={policyChipHint((standards as { commit?: unknown }).commit)}
              />
              <StandardChip
                label="Architecture policy"
                value={policyChipLabel(
                  (standards as { architecture?: unknown }).architecture,
                )}
                hint={policyChipHint(
                  (standards as { architecture?: unknown }).architecture,
                )}
              />
              <StandardChip
                label="Testing policy"
                value={policyChipLabel((standards as { testing?: unknown }).testing)}
                hint={policyChipHint((standards as { testing?: unknown }).testing)}
              />
            </div>
          ) : (
            <p className="text-muted-foreground">No company.yaml standards loaded (or empty).</p>
          )}
          {hasDocs ? (
            <Button size="sm" variant="outline" asChild>
              <Link href="/documentation?doc=architecture">Open Documentation</Link>
            </Button>
          ) : (
            <p className="text-xs text-muted-foreground">
              Optional documentation: no{" "}
              <code className="text-2xs">.refactory/*.md</code> files loaded via GET
              /documentation. Organization rules still apply without them.
            </p>
          )}
        </CardContent>
      </Card>

      <DetailDrawer
        open={Boolean(drawerRule)}
        onOpenChange={(o) => !o && setDrawerRule(null)}
        title={drawerRule?.name ?? ""}
        description="Rule metadata from GET /rules"
        badges={
          drawerRule ? (
            <>
              <StatusBadge label={drawerRule.severity} />
              <StatusBadge label={drawerRule.category} tone="info" />
              <StatusBadge
                label={drawerRule.blocking ? "blocking" : "advisory"}
                tone={drawerRule.blocking ? "danger" : "muted"}
              />
            </>
          ) : null
        }
        footer={
          hasDocs ? (
            <Button size="sm" variant="outline" asChild>
              <Link href="/documentation?doc=architecture">View company documentation</Link>
            </Button>
          ) : null
        }
      >
        {drawerRule ? (
          <div className="space-y-4">
            <DetailSection title="Description">
              <p className="whitespace-pre-wrap">{drawerRule.message || "—"}</p>
            </DetailSection>
            <DetailSection title="Configuration">
              Not exposed on GET /rules. Rule engine conditions live in .refactory/rules.yaml /
              company.yaml.
            </DetailSection>
            <DetailSection title="Documentation">
              Unavailable from Local API. Link company docs when loaded.
            </DetailSection>
            <DetailSection title="Recommended fix">
              Not persisted on rule catalog. Use violation detail after POST /rules/check.
            </DetailSection>
            <DetailSection title="Configuration source">
              .refactory/rules.yaml (RuleEngine) and/or .refactory/company.yaml
              (CompanyRulesChecker)
            </DetailSection>
          </div>
        ) : null}
      </DetailDrawer>

      <DetailDrawer
        open={Boolean(selectedViolation)}
        onOpenChange={(o) => !o && setSelectedViolation(null)}
        title={selectedViolation?.rule ?? ""}
        description="Violation from POST /rules/check"
        badges={
          selectedViolation ? (
            <>
              <StatusBadge label={selectedViolation.severity} />
              {selectedViolation.blocking ? (
                <StatusBadge label="blocking" tone="danger" />
              ) : null}
              <StatusBadge
                label={
                  selectedViolation.source === "organization"
                    ? "Organization"
                    : "Built-in"
                }
                tone={
                  selectedViolation.source === "organization" ? "info" : "muted"
                }
              />
            </>
          ) : null
        }
      >
        {selectedViolation ? (
          <div className="space-y-3">
            <DetailSection title="Message">
              <p className="whitespace-pre-wrap">{selectedViolation.message || "—"}</p>
            </DetailSection>
            <DetailSection title="Reason / detail">
              <p className="whitespace-pre-wrap">{selectedViolation.detail || "—"}</p>
            </DetailSection>
            <DetailSection title="File">
              {selectedViolation.file_path || "Not provided for this violation"}
            </DetailSection>
            {selectedViolation.documentation_url ? (
              <DetailSection title="Documentation">
                <Button size="sm" variant="outline" asChild>
                  <Link href={selectedViolation.documentation_url}>Open policy docs</Link>
                </Button>
              </DetailSection>
            ) : null}
          </div>
        ) : null}
      </DetailDrawer>
    </PageContainer>
  );
}

function policyChipLabel(policy: unknown): string {
  if (!policy) return "Not configured";
  if (typeof policy === "object" && policy !== null) {
    const row = policy as { rule_count?: number; configured?: boolean; pattern?: string };
    if (row.configured === false) return "Not configured";
    const n = typeof row.rule_count === "number" ? row.rule_count : 0;
    if (n > 0) return `Configured (${n} rule${n === 1 ? "" : "s"})`;
  }
  return "Configured";
}

function policyChipHint(policy: unknown): string | undefined {
  if (!policy || typeof policy !== "object") return undefined;
  const row = policy as { rule_names?: unknown; source?: unknown };
  const names = Array.isArray(row.rule_names)
    ? row.rule_names.filter((n): n is string => typeof n === "string" && n.trim().length > 0)
    : [];
  if (names.length) {
    const preview = names.slice(0, 2).join(", ");
    return names.length > 2 ? `${preview} +${names.length - 2} more` : preview;
  }
  if (typeof row.source === "string" && row.source) return row.source;
  return undefined;
}

function StandardChip({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-md border px-3 py-2">
      <p className="text-2xs uppercase text-muted-foreground">{label}</p>
      <p className="font-medium">{value}</p>
      {hint ? <p className="mt-0.5 text-2xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}
