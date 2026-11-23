"use client";

import Link from "next/link";
import * as React from "react";
import {
  Activity,
  GitBranch,
  HeartPulse,
  Layers,
  RefreshCw,
  Scale,
  Sparkles,
  Undo2,
  FileSearch,
} from "lucide-react";

import { DistributionChart } from "@/components/data-display/distribution-chart";
import { MetricStrip } from "@/components/data-display/metric-strip";
import { StatusBadge } from "@/components/data-display/status-badge";
import { EmptyState } from "@/components/feedback/empty-state";
import { ErrorState } from "@/components/feedback/error-state";
import { ListSkeleton } from "@/components/feedback/loading-skeletons";
import { FilterBar } from "@/components/filter-bar";
import { PageContainer } from "@/components/layout/page-container";
import { PageHeader } from "@/components/page-header";
import { SearchInput } from "@/components/search-input";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatRelativeTime, shortSha } from "@/lib/format";
import { useListFilters } from "@/hooks/use-list-filters";
import { useActivity } from "@/queries/use-activity";
import { useGraphSummary } from "@/queries/use-graph";
import { useRecommendations } from "@/queries/use-recommendations";
import { useRepository } from "@/queries/use-repository";
import { useReviews } from "@/queries/use-reviews";
import { ApiError } from "@/services/errors";
import type { AnalysisRun } from "@/types/domain";

import {
  classifyCommand,
  dailyCounts,
  formatDuration,
  isSameLocalDay,
  kindColor,
  kindLabel,
  linkForRun,
  type ActivityKind,
} from "./lib/activity-meta";

const COMMANDS = [
  "review",
  "recommend",
  "transform",
  "index",
  "graph",
  "rules-check",
].map((v) => ({ value: v, label: v }));

const STATUSES = ["success", "failed", "error", "running", "completed"].map((v) => ({
  value: v,
  label: v,
}));

const DATE_FILTERS = [
  { value: "today", label: "Today" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
];

function KindIcon({ kind }: { kind: ActivityKind }) {
  const className = "size-3.5";
  switch (kind) {
    case "review":
      return <FileSearch className={className} />;
    case "recommend":
      return <Sparkles className={className} />;
    case "transform":
      return <RefreshCw className={className} />;
    case "rollback":
      return <Undo2 className={className} />;
    case "graph":
      return <GitBranch className={className} />;
    case "index":
      return <Layers className={className} />;
    case "rules":
      return <Scale className={className} />;
    case "health":
      return <HeartPulse className={className} />;
    default:
      return <Activity className={className} />;
  }
}

export function ActivityView() {
  const repo = useRepository();
  const { filters, setSearch, setStatus, setExtra } = useListFilters();
  const command = filters.extra.command ?? null;
  const setCommand = (v: string | null) => setExtra("command", v);
  const status = filters.status;
  const dateFilter = filters.extra.date ?? null;
  const setDateFilter = (v: string | null) => setExtra("date", v);
  const q = filters.search;
  const [expanded, setExpanded] = React.useState<string | null>(null);

  const activity = useActivity({
    limit: 200,
    command: command ?? undefined,
    status: status ?? undefined,
  });
  const reviews = useReviews(5);
  const recs = useRecommendations({ limit: 5 });
  /** Avoid waterfall/contention — summary after the activity list settles. */
  const graphSummary = useGraphSummary(Boolean(activity.isFetched || activity.isError));

  const runs = React.useMemo(() => activity.data ?? [], [activity.data]);

  const filtered = React.useMemo(() => {
    const cutoffMs =
      dateFilter === "7d"
        ? 7 * 24 * 60 * 60 * 1000
        : dateFilter === "30d"
          ? 30 * 24 * 60 * 60 * 1000
          : null;
    // Anchor to latest run timestamp (stable) instead of Date.now() during render.
    const anchor = runs.reduce((max, run) => {
      const t = run.created_at ? new Date(run.created_at).getTime() : 0;
      return t > max ? t : max;
    }, 0);

    return runs.filter((run) => {
      if (dateFilter === "today" && !isSameLocalDay(run.created_at)) return false;
      if (cutoffMs != null) {
        if (!run.created_at || !anchor) return false;
        const t = new Date(run.created_at).getTime();
        if (anchor - t > cutoffMs) return false;
      }
      if (q) {
        const hay =
          `${run.command} ${run.status} ${run.git_commit ?? ""} ${run.branch ?? ""} ${run.id}`.toLowerCase();
        if (!hay.includes(q.toLowerCase())) return false;
      }
      return true;
    });
  }, [runs, dateFilter, q]);

  const stats = React.useMemo(() => {
    const today = runs.filter((r) => isSameLocalDay(r.created_at));
    return {
      total: runs.length,
      reviewsToday: today.filter((r) => classifyCommand(r.command) === "review").length,
      recsToday: today.filter((r) => classifyCommand(r.command) === "recommend").length,
      transforms: runs.filter((r) => {
        const k = classifyCommand(r.command);
        return k === "transform" || k === "rollback";
      }).length,
      rulesChecks: runs.filter((r) => classifyCommand(r.command) === "rules").length,
    };
  }, [runs]);

  const byCommand = React.useMemo(() => {
    const map = new Map<string, number>();
    for (const r of runs) {
      const label = kindLabel(classifyCommand(r.command));
      map.set(label, (map.get(label) ?? 0) + 1);
    }
    return [...map.entries()].map(([label, value]) => ({
      key: label,
      label,
      value,
    }));
  }, [runs]);

  const trend = React.useMemo(() => dailyCounts(runs, 14), [runs]);

  const latestByKind = React.useMemo(() => {
    const pick = (pred: (r: AnalysisRun) => boolean) => runs.find(pred) ?? null;
    return {
      review: reviews.data?.[0] ?? null,
      recommendation: recs.data?.[0] ?? null,
      graphRun: pick((r) => classifyCommand(r.command) === "graph"),
      index: pick((r) => classifyCommand(r.command) === "index"),
      transform: pick((r) => {
        const k = classifyCommand(r.command);
        return k === "transform" || k === "rollback";
      }),
    };
  }, [runs, reviews.data, recs.data]);

  return (
    <PageContainer className="space-y-6">
      <PageHeader
        title="Activity Timeline"
        description="Engineering operations feed from GET /activity — enriched with reviews, recommendations, and graph summary."
      />

      <MetricStrip
        items={[
          { key: "total", label: "Activity count", value: stats.total },
          { key: "reviews", label: "Reviews today", value: stats.reviewsToday },
          { key: "recs", label: "Recommendations today", value: stats.recsToday },
          { key: "transforms", label: "Transforms", value: stats.transforms },
          { key: "rules", label: "Rules checks", value: stats.rulesChecks },
        ]}
        columnsClassName="sm:grid-cols-2 lg:grid-cols-5"
      />

      <section className="grid gap-3 lg:grid-cols-2">
        <DistributionChart title="By operation type" items={byCommand} variant="stack" />
        <DistributionChart
          title="14-day trend"
          items={trend.map((t) => ({ key: t.key, label: t.label, value: t.value }))}
          variant="bar"
          emptyLabel="Not enough activity timestamps to trend"
        />
      </section>

      {/* Recent Operations */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Recent Operations</CardTitle>
          <CardDescription>
            Latest signals from GET /reviews, /recommendations, /graph, /activity
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          <RecentTile
            label="Latest review"
            value={
              latestByKind.review
                ? `Risk ${latestByKind.review.risk || "—"} · ${formatRelativeTime(latestByKind.review.created_at)}`
                : "Unavailable"
            }
            href="/reviews"
          />
          <RecentTile
            label="Latest recommendation"
            value={
              latestByKind.recommendation
                ? `${latestByKind.recommendation.title} · ${formatRelativeTime(latestByKind.recommendation.created_at)}`
                : "Unavailable"
            }
            href="/recommendations"
          />
          <RecentTile
            label="Latest graph build"
            value={
              latestByKind.graphRun
                ? formatRelativeTime(latestByKind.graphRun.created_at)
                : graphSummary.data
                  ? `Summary · ${graphSummary.data.nodes ?? "—"} nodes`
                  : "Unavailable"
            }
            href="/repository/graph"
          />
          <RecentTile
            label="Latest index"
            value={
              latestByKind.index
                ? formatRelativeTime(latestByKind.index.created_at)
                : "Unavailable"
            }
            href="/repository"
          />
          <RecentTile
            label="Latest transform"
            value={
              latestByKind.transform
                ? `${latestByKind.transform.command} · ${formatRelativeTime(latestByKind.transform.created_at)}`
                : "Unavailable"
            }
            href="/transform"
          />
        </CardContent>
      </Card>

      <div className="flex flex-col gap-3">
        <SearchInput value={q} onChange={setSearch} placeholder="Search activity…" />
        <div className="flex flex-col gap-2 lg:flex-row lg:flex-wrap lg:items-center">
          <FilterBar
            options={COMMANDS}
            value={command}
            onChange={setCommand}
            allLabel="All operations"
          />
          <FilterBar
            options={STATUSES}
            value={status}
            onChange={setStatus}
            allLabel="All statuses"
          />
          <FilterBar
            options={DATE_FILTERS}
            value={dateFilter}
            onChange={setDateFilter}
            allLabel="All dates"
          />
          <StatusBadge
            label={repo.data?.name || "repository"}
            tone="muted"
          />
        </div>
      </div>

      {activity.isLoading ? (
        <ListSkeleton rows={8} />
      ) : activity.isError ? (
        <ErrorState
          title="Could not load activity"
          description={
            activity.error instanceof ApiError ? activity.error.message : undefined
          }
          onRetry={() => void activity.refetch()}
        />
      ) : !filtered.length ? (
        <EmptyState
          title="No activity yet"
          description="Engine runs appear here after reviews, recommendations, transforms, graph, index, or rules checks."
        />
      ) : (
        <ol className="relative space-y-0 border-l pl-6">
          {filtered.map((run) => {
            const kind = classifyCommand(run.command);
            const open = expanded === run.id;
            const link = linkForRun(run);
            return (
              <li key={run.id} className="mb-5 ml-2">
                <span
                  className="absolute -left-1.5 mt-2 flex size-3 items-center justify-center rounded-full border-2 border-background"
                  style={{ background: kindColor(kind) }}
                />
                <button
                  type="button"
                  onClick={() => setExpanded(open ? null : run.id)}
                  className="w-full rounded-lg border bg-card p-3 text-left transition-colors hover:bg-muted/30"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className="inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs"
                      style={{ color: kindColor(kind) }}
                    >
                      <KindIcon kind={kind} />
                      {kindLabel(kind)}
                    </span>
                    <StatusBadge label={run.command} tone="info" />
                    <StatusBadge label={run.status} />
                    <span className="text-xs text-muted-foreground">
                      {formatRelativeTime(run.created_at)}
                    </span>
                  </div>
                  {(() => {
                    const rd =
                      run.result_data && typeof run.result_data === "object"
                        ? (run.result_data as Record<string, unknown>)
                        : null;
                    const headline =
                      typeof rd?.summary === "string" ? rd.summary.trim() : "";
                    return headline ? (
                      <p className="mt-2 text-sm font-medium">{headline}</p>
                    ) : null;
                  })()}
                  <p className="mt-2 font-mono text-xs text-muted-foreground">
                    {repo.data?.name ?? "repo"} ·{" "}
                    {run.git_commit ? shortSha(run.git_commit) : "no commit"} ·{" "}
                    {run.id.slice(0, 8)}
                  </p>
                </button>

                {open ? (
                  <div className="mt-2 space-y-2 rounded-lg border bg-muted/20 p-3 text-sm">
                    <dl className="grid gap-2 sm:grid-cols-2">
                      <Meta label="Operation" value={run.command} />
                      <Meta label="Status" value={run.status} />
                      <Meta label="Branch" value={run.branch || "Not persisted"} />
                      <Meta
                        label="Duration"
                        value={
                          run.duration_ms != null
                            ? formatDuration(run.duration_ms)
                            : "Unavailable — not set on this run"
                        }
                      />
                      <Meta
                        label="Result type"
                        value={run.result_type || "Not persisted"}
                      />
                      <Meta
                        label="Repository"
                        value={repo.data?.name || run.repository_id.slice(0, 8)}
                      />
                    </dl>
                    {run.error_message ? (
                      <p className="text-xs text-destructive">{run.error_message}</p>
                    ) : null}
                    {run.metadata && Object.keys(run.metadata).length ? (
                      <pre className="max-h-40 overflow-auto rounded-md border bg-background p-2 font-mono text-2xs">
                        {JSON.stringify(run.metadata, null, 2)}
                      </pre>
                    ) : (
                      <p className="text-xs text-muted-foreground">
                        Metadata: empty or not persisted for this run.
                      </p>
                    )}
                    {link ? (
                      <Button size="sm" variant="outline" asChild>
                        <Link href={link.href}>{link.label}</Link>
                      </Button>
                    ) : null}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}
    </PageContainer>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-2xs uppercase text-muted-foreground">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

function RecentTile({
  label,
  value,
  href,
}: {
  label: string;
  value: string;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="rounded-md border p-3 transition-colors hover:bg-muted/40"
    >
      <p className="text-2xs uppercase text-muted-foreground">{label}</p>
      <p className="mt-1 line-clamp-2 text-xs font-medium">{value}</p>
    </Link>
  );
}
