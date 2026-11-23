"use client";

import Link from "next/link";
import * as React from "react";
import { Download } from "lucide-react";

import { MetricStrip } from "@/components/data-display/metric-strip";
import { StatusBadge } from "@/components/data-display/status-badge";
import { EmptyState } from "@/components/feedback/empty-state";
import { ErrorState } from "@/components/feedback/error-state";
import { ListSkeleton } from "@/components/feedback/loading-skeletons";
import { FilterBar } from "@/components/filter-bar";
import { PageContainer } from "@/components/layout/page-container";
import { PageHeader } from "@/components/page-header";
import { SearchInput } from "@/components/search-input";
import { DetailDrawer } from "@/components/shared/detail-drawer";
import { DetailSection } from "@/components/shared/detail-section";
import { Button } from "@/components/ui/button";
import { formatRelativeTime } from "@/lib/format";
import { ApiError } from "@/services/errors";
import type { HistoryItem } from "@/types/domain";
import {
  useExportHistory,
  useHistory,
  useHistoryMetrics,
} from "@/queries/use-history";

import {
  ANALYSIS_TYPE_OPTIONS,
  analysisTypeLabel,
  deepLinkFor,
  statusTone,
} from "./lib/history-meta";

const STATUS_OPTIONS = [
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "error", label: "Error" },
  { value: "pass", label: "Pass" },
  { value: "warn", label: "Warn" },
  { value: "block", label: "Block" },
];

const DATE_OPTIONS = [
  { value: "today", label: "Today" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
  { value: "90d", label: "90 days" },
];

function sinceIso(key: string | null): string | undefined {
  if (!key) return undefined;
  const now = new Date();
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  if (key === "today") return start.toISOString();
  const days = key === "7d" ? 7 : key === "30d" ? 30 : key === "90d" ? 90 : 0;
  if (!days) return undefined;
  start.setDate(start.getDate() - (days - 1));
  return start.toISOString();
}

export function HistoryView() {
  const [search, setSearch] = React.useState("");
  const [branch, setBranch] = React.useState("");
  const [analysisType, setAnalysisType] = React.useState<string | null>(null);
  const [status, setStatus] = React.useState<string | null>(null);
  const [dateRange, setDateRange] = React.useState<string | null>(null);
  const [selected, setSelected] = React.useState<HistoryItem | null>(null);
  const [compareIds, setCompareIds] = React.useState<string[]>([]);

  const list = useHistory({
    search: search || undefined,
    branch: branch.trim() || undefined,
    analysis_type: analysisType || undefined,
    status: status || undefined,
    since: sinceIso(dateRange),
    limit: 200,
  });
  const metrics = useHistoryMetrics();
  const exportMut = useExportHistory();

  const items = list.data ?? [];

  const toggleCompare = (id: string) => {
    setCompareIds((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= 2) return [prev[1], id];
      return [...prev, id];
    });
  };

  const metricItems = React.useMemo(() => {
    const m = metrics.data;
    return [
      { key: "total", label: "Total Analyses", value: m?.total_analyses ?? "—" },
      { key: "today", label: "Today", value: m?.today ?? "—" },
      { key: "week", label: "This Week", value: m?.this_week ?? "—" },
      {
        key: "avg",
        label: "Average Duration",
        value: m ? `${Math.round(m.average_duration_ms)} ms` : "—",
      },
      { key: "fail", label: "Failures", value: m?.failures ?? "—", variant: "danger" as const },
      {
        key: "rate",
        label: "Success Rate",
        value: m ? `${m.success_rate}%` : "—",
        variant: "primary" as const,
      },
    ];
  }, [metrics.data]);

  return (
    <PageContainer className="space-y-6">
      <PageHeader
        title="History"
        description="Searchable memory of analysis results — Reviews, Recommendations, Graph, Patches, Rules, and more."
        actions={
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={exportMut.isPending}
              onClick={() => exportMut.mutate("json")}
            >
              <Download className="size-3" aria-hidden />
              JSON
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={exportMut.isPending}
              onClick={() => exportMut.mutate("markdown")}
            >
              Markdown
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={exportMut.isPending}
              onClick={() => exportMut.mutate("csv")}
            >
              CSV
            </Button>
            <Button size="sm" variant="secondary" disabled title="Compare requires backend support">
              Compare{compareIds.length ? ` (${compareIds.length})` : ""}
            </Button>
          </div>
        }
      />

      <MetricStrip items={metricItems} />

      <div className="flex flex-col gap-3 lg:flex-row lg:flex-wrap lg:items-center">
        <SearchInput
          className="lg:max-w-xs"
          value={search}
          onChange={setSearch}
          placeholder="Search summary, repository, commit…"
        />
        <SearchInput
          className="lg:max-w-[12rem]"
          value={branch}
          onChange={setBranch}
          placeholder="Branch filter…"
        />
        <FilterBar
          options={ANALYSIS_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
          value={analysisType}
          onChange={setAnalysisType}
          allLabel="All types"
        />
        <FilterBar
          options={STATUS_OPTIONS}
          value={status}
          onChange={setStatus}
          allLabel="All statuses"
        />
        <FilterBar
          options={DATE_OPTIONS}
          value={dateRange}
          onChange={setDateRange}
          allLabel="All dates"
        />
      </div>

      <p className="text-xs text-muted-foreground">
        History stores analysis <em>results</em>. Activity answers &quot;what happened&quot; —{" "}
        <Link href="/activity" className="underline-offset-2 hover:underline">
          open Activity
        </Link>
        .
      </p>

      {list.isError ? (
        <ErrorState
          title="Unable to load history"
          description={list.error instanceof ApiError ? list.error.message : undefined}
          onRetry={() => void list.refetch()}
        />
      ) : list.isLoading ? (
        <ListSkeleton rows={8} />
      ) : !items.length ? (
        <EmptyState
          title="No analyses yet"
          description="Run a review, recommendations, index, graph, or rules check — results are saved automatically."
        />
      ) : (
        <ul className="space-y-2">
          {items.map((item) => {
            const link = deepLinkFor(item);
            const comparing = compareIds.includes(item.id);
            return (
              <li key={item.id}>
                <div className="flex gap-2 rounded-lg border p-3 hover:bg-muted/30">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={comparing}
                    onChange={() => toggleCompare(item.id)}
                    aria-label="Select for compare"
                  />
                  <button
                    type="button"
                    className="min-w-0 flex-1 text-left"
                    onClick={() => setSelected(item)}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge label={analysisTypeLabel(item.analysis_type)} tone="info" />
                      <StatusBadge label={item.status} tone={statusTone(item.status)} />
                      <StatusBadge
                        label={item.created_by || item.created_by_user || "local"}
                        tone="muted"
                      />
                      <span className="text-xs text-muted-foreground">
                        {formatRelativeTime(item.timestamp)}
                      </span>
                      {item.duration_ms != null ? (
                        <span className="text-xs text-muted-foreground tabular-nums">
                          {Math.round(item.duration_ms)} ms
                        </span>
                      ) : null}
                    </div>
                    <p className="mt-1 text-sm font-medium">{item.summary || "—"}</p>
                    <p className="mt-1 text-2xs text-muted-foreground">
                      <span className="font-mono">
                        {(item.repository || item.repository_name || "repo") +
                          (item.branch ? ` · ${item.branch}` : "") +
                          (item.commit ? ` · ${item.commit.slice(0, 8)}` : "")}
                      </span>
                      <span className="mx-1.5 opacity-50">·</span>
                      Module {analysisTypeLabel(item.analysis_type)}
                      <span className="mx-1.5 opacity-50">·</span>
                      Undo not available
                    </p>
                  </button>
                  {link ? (
                    <Button size="sm" variant="ghost" asChild className="shrink-0 self-center">
                      <Link href={link.href}>{link.label}</Link>
                    </Button>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <DetailDrawer
        open={Boolean(selected)}
        onOpenChange={(o) => !o && setSelected(null)}
        title={selected ? analysisTypeLabel(selected.analysis_type) : ""}
        description={selected?.summary || "Analysis detail"}
        badges={
          selected ? (
            <>
              <StatusBadge label={selected.status} tone={statusTone(selected.status)} />
              <StatusBadge label={selected.created_by || "local"} tone="muted" />
            </>
          ) : null
        }
        footer={
          selected && deepLinkFor(selected) ? (
            <Button size="sm" asChild>
              <Link href={deepLinkFor(selected)!.href}>{deepLinkFor(selected)!.label}</Link>
            </Button>
          ) : null
        }
      >
        {selected ? (
          <div className="space-y-4">
            <DetailSection title="Metadata">
              <dl className="grid gap-1 text-sm">
                <Row label="Timestamp" value={selected.timestamp || "—"} />
                <Row label="Repository" value={selected.repository || selected.repository_name || "—"} />
                <Row label="Branch" value={selected.branch || "—"} />
                <Row label="Commit" value={selected.commit || "—"} />
                <Row
                  label="Duration"
                  value={
                    selected.duration_ms != null
                      ? `${Math.round(selected.duration_ms)} ms`
                      : "—"
                  }
                />
              </dl>
            </DetailSection>
            <DetailSection title="Summary">
              <p className="whitespace-pre-wrap text-sm">{selected.summary || "—"}</p>
            </DetailSection>
            <DetailSection title="Outputs / result data">
              <pre className="max-h-64 overflow-auto rounded-md bg-muted/40 p-2 text-2xs">
                {JSON.stringify(selected.result_data ?? {}, null, 2)}
              </pre>
            </DetailSection>
            <DetailSection title="Metadata JSON">
              <pre className="max-h-40 overflow-auto rounded-md bg-muted/40 p-2 text-2xs">
                {JSON.stringify(selected.metadata ?? {}, null, 2)}
              </pre>
            </DetailSection>
            <DetailSection title="Compare">
              <p className="text-xs text-muted-foreground">
                Select two timeline items, then use Compare (disabled until backend comparison
                ships).
              </p>
            </DetailSection>
          </div>
        ) : null}
      </DetailDrawer>
    </PageContainer>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-mono text-xs">{value}</dd>
    </div>
  );
}
