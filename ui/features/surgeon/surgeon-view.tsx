"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { DataTable } from "@/components/data-display/data-table";
import { StatusBadge } from "@/components/data-display/status-badge";
import { EmptyState } from "@/components/feedback/empty-state";
import { ErrorState } from "@/components/feedback/error-state";
import { ListSkeleton, MetricSkeleton } from "@/components/feedback/loading-skeletons";
import { ApiError } from "@/services/errors";
import { CollapsibleSection } from "@/components/layout/collapsible-section";
import { PageContainer } from "@/components/layout/page-container";
import { MarkdownViewer } from "@/components/markdown-viewer";
import { PageHeader } from "@/components/page-header";
import { RunReviewDialog } from "@/components/shared/run-review-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { formatRelativeTime, shortSha } from "@/lib/format";
import { useBranchSurgeon } from "@/queries/use-branch-surgeon";
import { useBuildGraph } from "@/queries/use-graph";
import {
  useGenerateRecommendations,
  useRecommendationStats,
} from "@/queries/use-recommendations";
import { useRepository, useRepositoryStatus } from "@/queries/use-repository";
import { useHistory } from "@/queries/use-history";
import { useRulesCheck } from "@/queries/use-rules";
import { getSurgeonAvailability } from "@/services/surgeon";
import { analysisTypeLabel, deepLinkFor } from "@/features/history/lib/history-meta";

import { SurgeonActionBar } from "./components/action-bar";
import { BlastRadiusPanel } from "./components/blast-radius";
import { BranchSummary } from "./components/branch-summary";
import { SurgeonDecisionStrip } from "./components/decision-strip";
import { SurgeryScoreCard } from "./components/surgery-score-card";
import { blastFocusFile, graphWorkspaceHref } from "./lib/graph-workspace-href";

export function SurgeonView() {
  const router = useRouter();
  const availability = getSurgeonAvailability();
  const workspace = useBranchSurgeon();
  /** Same React Query cache as Recommendations page — never a second counter. */
  const recStats = useRecommendationStats();
  const repo = useRepository();
  const status = useRepositoryStatus();
  const history = useHistory({ limit: 8 });
  const generateRecs = useGenerateRecommendations();
  const buildGraph = useBuildGraph();
  const rulesCheck = useRulesCheck();
  const [reviewOpen, setReviewOpen] = React.useState(false);

  const data = workspace.data;
  /** Prefer shared stats hook; fall back to workspace embed so tiles never flash null/0 while loading. */
  const recSummary = recStats.data ?? data?.recommendations ?? null;
  const latestReview = data?.reviews.latest ?? null;
  const criticalFiles = React.useMemo(
    () => data?.blast_radius.critical_files ?? [],
    [data?.blast_radius.critical_files],
  );
  const openGraphHref = React.useMemo(
    () => graphWorkspaceHref(blastFocusFile(data?.blast_radius)),
    [data?.blast_radius],
  );
  const timeline = data?.timeline ?? [];
  const historyItems = history.data ?? [];

  const attentionOrder = React.useMemo(() => {
    return criticalFiles.slice(0, 8).map((name, i) => ({
      order: i + 1,
      title: name,
      source: "blast radius · critical file",
      href: `/repository?file=${encodeURIComponent(name)}`,
    }));
  }, [criticalFiles]);

  const whatMightBreak = React.useMemo(() => {
    const cards: { title: string; detail: string; tone: string }[] = [];
    if ((recSummary?.critical ?? 0) > 0) {
      cards.push({
        title: `${recSummary?.critical} critical recommendations`,
        detail: "Address critical findings before merge.",
        tone: "critical",
      });
    }
    if ((recSummary?.high ?? 0) > 0) {
      cards.push({
        title: `${recSummary?.high} high recommendations`,
        detail: "High-priority items from the recommendation store.",
        tone: "high",
      });
    }
    if ((data?.rules.failed ?? 0) > 0) {
      cards.push({
        title: `${data?.rules.failed} blocking rule(s)`,
        detail: `Rules outcome: ${data?.rules.outcome ?? "block"}`,
        tone: "blocking",
      });
    }
    if ((data?.rules.warning_count ?? 0) > 0) {
      cards.push({
        title: `${data?.rules.warning_count} rule warning(s)`,
        detail: "Non-blocking policy warnings.",
        tone: "high",
      });
    }
    for (const file of criticalFiles.slice(0, 3)) {
      cards.push({
        title: file,
        detail: "High-connectivity file in repository graph.",
        tone: "high",
      });
    }
    return cards;
  }, [data, criticalFiles, recSummary]);

  const exportPayload = React.useMemo(
    () => ({
      exported_at: new Date().toISOString(),
      kind: "refactory.surgeon.workspace",
      source: "GET /branch-surgeon",
      workspace: data ?? null,
      availability,
    }),
    [data, availability],
  );

  return (
    <PageContainer variant="wide" className="space-y-6">
      <PageHeader
        title="Branch Surgeon"
        description="Comprehensive engineering decision workspace — repository health, recommendations, reviews, and deployment readiness."
        actions={
          <SurgeonActionBar
            onRunReview={() => setReviewOpen(true)}
            onGenerateRecs={() => generateRecs.mutate({})}
            onBuildGraph={() => buildGraph.mutate(true)}
            recsPending={generateRecs.isPending}
            graphPending={buildGraph.isPending}
            exportPayload={exportPayload}
            graphWorkspaceHref={openGraphHref}
          />
        }
      />

      <section className="flex flex-wrap items-center gap-2 rounded-lg border bg-card px-4 py-3">
        <StatusBadge label="Branch Surgeon API" tone="info" />
        <StatusBadge label={availability.status} tone="muted" />
        <p className="text-xs text-muted-foreground">{availability.message}</p>
      </section>

      {workspace.isError ? (
        <ErrorState
          title="Could not load Branch Surgeon"
          description={
            workspace.error instanceof ApiError ? workspace.error.message : undefined
          }
          onRetry={() => void workspace.refetch()}
        />
      ) : null}

      {workspace.isLoading && !data ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <MetricSkeleton />
          <MetricSkeleton />
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <BranchSummary
            branch={data?.branch}
            surgeryScore={data?.surgery.score}
          />
          <SurgeryScoreCard
            surgery={data?.surgery}
            healthOverall={data?.health.overall}
            criticalCount={recSummary?.critical}
          />
        </div>
      )}

      <CollapsibleSection
        title="Repository Health & Metrics"
        description="Comprehensive health scores from repository analysis"
        defaultOpen
      >
        {data?.health ? (
          <div className="space-y-4">
            <div className="grid gap-2 rounded-lg border p-4 sm:grid-cols-2 lg:grid-cols-4">
              <button
                type="button"
                onClick={() => router.push(`/recommendations?category=architecture`)}
                className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="text-muted-foreground">Architecture</span>
                <span className="font-medium tabular-nums">{data.health.architecture?.toFixed(0) ?? "—"}</span>
              </button>
              {data.health.maintainability != null ? (
                <button
                  type="button"
                  onClick={() => router.push(`/recommendations?category=maintainability`)}
                  className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span className="text-muted-foreground">Maintainability</span>
                  <span className="font-medium tabular-nums">{data.health.maintainability.toFixed(0)}</span>
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => router.push(`/recommendations?category=security`)}
                className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="text-muted-foreground">Security</span>
                <span className="font-medium tabular-nums">{data.health.security?.toFixed(0) ?? "—"}</span>
              </button>
              <button
                type="button"
                onClick={() => router.push(`/recommendations?category=testing`)}
                className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="text-muted-foreground">Testing</span>
                <span className="font-medium tabular-nums">{data.health.testing?.toFixed(0) ?? "—"}</span>
              </button>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Repository Info</CardTitle>
                  <CardDescription>Current repository state</CardDescription>
                </CardHeader>
                <CardContent>
                  {repo.isLoading && !repo.data ? (
                    <div className="grid grid-cols-2 gap-3">
                      {Array.from({ length: 6 }).map((_, i) => (
                        <MetricSkeleton key={i} />
                      ))}
                    </div>
                  ) : repo.isError ? (
                    <ErrorState
                      title="Repository unavailable"
                      description={repo.error instanceof ApiError ? repo.error.message : undefined}
                      onRetry={() => void repo.refetch()}
                    />
                  ) : (
                    <dl className="grid grid-cols-2 gap-3 text-sm">
                      <Item label="Repository" value={repo.data?.name} />
                      <Item label="Branch" value={repo.data?.current_branch} />
                      <Item label="Default" value={repo.data?.default_branch} />
                      <Item label="Provider" value={status.data?.ai_provider} />
                      <Item label="HEAD" value={shortSha(repo.data?.head_sha)} mono />
                      <Item label="Model" value={status.data?.ai_model ?? "—"} />
                    </dl>
                  )}
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Index Status</CardTitle>
                  <CardDescription>Repository indexing and graph state</CardDescription>
                </CardHeader>
                <CardContent>
                  <dl className="grid grid-cols-2 gap-3 text-sm">
                    <Item
                      label="Indexed files"
                      value={
                        status.data?.index_staleness?.indexed_files != null
                          ? `${status.data.index_staleness.indexed_files}`
                          : "—"
                      }
                    />
                    <Item
                      label="Index status"
                      value={
                        status.data?.index_staleness?.is_stale ? "Stale" : "Current"
                      }
                    />
                    <Item
                      label="Graph nodes"
                      value={data?.blast_radius.node_count?.toString() ?? "—"}
                    />
                    <Item
                      label="Graph edges"
                      value={data?.blast_radius.edge_count?.toString() ?? "—"}
                    />
                  </dl>
                </CardContent>
              </Card>
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Loading health metrics…</p>
        )}
      </CollapsibleSection>

      <SurgeonDecisionStrip
        healthError={null}
        healthScores={
          data
            ? {
                overall: data.health.overall,
                architecture: data.health.architecture,
                security: data.health.security,
                testing: data.health.testing,
                maintainability: data.health.maintainability ?? 0,
              }
            : null
        }
        recCount={recSummary?.total ?? "—"}
        criticalCount={recSummary?.critical ?? 0}
        blockerCount={data?.rules.failed ?? "—"}
        warningCount={data?.rules.warning_count ?? "—"}
        ruleCount={undefined}
        rulesPending={rulesCheck.isPending}
        onRunRules={() => rulesCheck.mutate()}
        mergeConflictRisk={data?.merge_conflict_risk ?? null}
        latestReview={
          latestReview
            ? {
                id: String(latestReview.id ?? ""),
                repository_id: "",
                pr_number: latestReview.pr_number ?? null,
                provider: "",
                model: "",
                risk: latestReview.risk ?? "unknown",
                confidence:
                  typeof latestReview.confidence === "number"
                    ? latestReview.confidence
                    : null,
                summary: latestReview.summary ?? "",
                created_at: latestReview.created_at ?? null,
                suggestion_count: latestReview.suggestion_count,
              }
            : null
        }
      />

      <CollapsibleSection
        title="Blast radius & connectivity"
        description="From GET /branch-surgeon blast_radius"
        defaultOpen
      >
        <BlastRadiusPanel
          blast={data?.blast_radius}
          loading={workspace.isLoading && !data}
        />
      </CollapsibleSection>

      <CollapsibleSection
        title="Dependency chain & critical files"
        description="Critical files from Branch Surgeon workspace"
        defaultOpen
      >
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Most connected</CardTitle>
              <CardDescription>
                From workspace blast_radius.most_connected
              </CardDescription>
            </CardHeader>
            <CardContent>
              {!(data?.blast_radius.most_connected ?? []).length ? (
                <EmptyState
                  className="py-8"
                  title="No connectivity data"
                  description="Build the repository graph, then refresh Branch Surgeon."
                  actionLabel="Open Full Graph Workspace"
                  onAction={() => router.push(openGraphHref)}
                />
              ) : (
                <ul className="space-y-2">
                  {(data?.blast_radius.most_connected ?? []).map((name) => (
                    <li key={name}>
                      <Link
                        href={`/repository?file=${encodeURIComponent(name)}`}
                        className="block truncate rounded-md border px-3 py-2 font-mono text-xs hover:bg-muted/40"
                      >
                        {name}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Critical Files</CardTitle>
              <CardDescription>
                High-connectivity files from workspace blast radius
              </CardDescription>
            </CardHeader>
            <CardContent>
              {!criticalFiles.length ? (
                <EmptyState
                  className="py-8"
                  title="No critical files"
                  description="Build the repository graph, then refresh Branch Surgeon."
                  actionLabel="Open Full Graph Workspace"
                  onAction={() => router.push(openGraphHref)}
                />
              ) : (
                <DataTable
                  columns={[
                    {
                      id: "file",
                      header: "File",
                      className: "max-w-[220px] truncate font-mono text-xs",
                      cell: (f: { name: string }) => f.name,
                    },
                    {
                      id: "signal",
                      header: "Signal",
                      cell: () => <StatusBadge label="graph" tone="muted" />,
                    },
                  ]}
                  data={criticalFiles.map((name) => ({ id: name, name }))}
                  getRowId={(f) => f.id}
                  onRowClick={(f) =>
                    router.push(`/repository?file=${encodeURIComponent(f.name)}`)
                  }
                />
              )}
              <p className="mt-3 text-xs text-muted-foreground">
                Changed files on branch: {data?.branch.changed_files ?? 0}
              </p>
            </CardContent>
          </Card>
        </div>
      </CollapsibleSection>

      <CollapsibleSection
        title="Review order & test plan"
        description="Priorities from blast radius + recommendation counts"
        defaultOpen
      >
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Suggested Review Order</CardTitle>
              <CardDescription>Critical files from Branch Surgeon blast radius</CardDescription>
            </CardHeader>
            <CardContent>
              {!attentionOrder.length ? (
                <EmptyState
                  className="py-6"
                  title="Nothing to prioritize yet"
                  description="Build the graph and refresh Branch Surgeon."
                  actionLabel="Open Recommendations"
                  onAction={() => router.push("/recommendations")}
                />
              ) : (
                <ol className="space-y-2">
                  {attentionOrder.map((item) => (
                    <li key={`${item.order}-${item.title}`}>
                      <Link
                        href={item.href}
                        className="flex items-start gap-3 rounded-md border px-3 py-2 text-sm transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold">
                          {item.order}
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate font-medium">{item.title}</span>
                          <span className="text-xs text-muted-foreground">{item.source}</span>
                        </span>
                      </Link>
                    </li>
                  ))}
                </ol>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Recommendation snapshot</CardTitle>
              <CardDescription>
                GET /recommendations/stats via RecommendationStatsService — same
                query cache as the Recommendations page
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <p>
                Total Recommendations:{" "}
                <strong>{recSummary?.total ?? 0}</strong>
              </p>
              <p>
                Critical: <strong>{recSummary?.critical ?? 0}</strong>
              </p>
              <p>
                High: <strong>{recSummary?.high ?? 0}</strong>
              </p>
              <p>
                Medium: <strong>{recSummary?.medium ?? 0}</strong>
              </p>
              <p>
                Low: <strong>{recSummary?.low ?? 0}</strong>
              </p>
              <p>
                Pending: <strong>{recSummary?.pending ?? 0}</strong>
              </p>
              <p>
                Resolved: <strong>{recSummary?.resolved ?? 0}</strong>
              </p>
              <p>
                Ignored: <strong>{recSummary?.ignored ?? 0}</strong>
              </p>
              <p className="text-2xs text-muted-foreground">
                Last Updated:{" "}
                {recSummary?.last_updated
                  ? formatRelativeTime(recSummary.last_updated)
                  : "—"}
                {" · "}
                Repository:{" "}
                {recSummary?.repository || data?.branch.repository || "—"}
                {" · "}
                Source:{" "}
                {recSummary?.source || "RecommendationStatsService"}
                {" · "}
                Recommendation Summary Version: {recSummary?.version || "1"}
              </p>
              <Button
                size="sm"
                variant="outline"
                onClick={() => router.push("/recommendations")}
              >
                Open Recommendations
              </Button>
            </CardContent>
          </Card>
        </div>
      </CollapsibleSection>

      <CollapsibleSection
        title="Transformations & AI summary"
        description="Reviews from Branch Surgeon workspace"
        defaultOpen={false}
      >
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Reviews</CardTitle>
              <CardDescription>Completed / pending from workspace</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <p>
                Completed: <strong>{data?.reviews.completed ?? 0}</strong>
              </p>
              <p>
                Pending: <strong>{data?.reviews.pending ?? 0}</strong>
              </p>
              <Button size="sm" variant="outline" onClick={() => router.push("/reviews")}>
                Open Reviews
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">AI Summary</CardTitle>
              <CardDescription>Latest review from workspace</CardDescription>
            </CardHeader>
            <CardContent>
              {workspace.isLoading && !latestReview ? (
                <p className="text-sm text-muted-foreground">Loading reviews…</p>
              ) : latestReview ? (
                <div className="space-y-2">
                  <div className="flex flex-wrap gap-2">
                    <StatusBadge label={latestReview.risk || "unknown"} />
                    <span className="text-xs text-muted-foreground">
                      {shortSha(latestReview.id)}
                    </span>
                  </div>
                  <ScrollArea className="h-48 rounded-md border p-3">
                    <MarkdownViewer content={latestReview.summary || "_No summary_"} />
                  </ScrollArea>
                  {latestReview.id ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => router.push(`/reviews?id=${latestReview.id}`)}
                    >
                      Open review workspace
                    </Button>
                  ) : null}
                </div>
              ) : (
                <EmptyState
                  className="py-6"
                  title="No AI summary yet"
                  description="Run a review to persist an AI summary for this repository."
                  actionLabel="Run Review"
                  onAction={() => setReviewOpen(true)}
                />
              )}
            </CardContent>
          </Card>
        </div>
      </CollapsibleSection>

      <CollapsibleSection
        title="What might break"
        description="Critical recommendations and blocking rules"
        defaultOpen
        badge={<StatusBadge label={`${whatMightBreak.length}`} tone="muted" />}
      >
        {!whatMightBreak.length ? (
          <p className="text-sm text-muted-foreground">
            No critical signals from recommendations or rule checks yet.
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {whatMightBreak.map((c, i) => (
              <div key={`${c.title}-${i}`} className="rounded-lg border p-3">
                <StatusBadge label={c.tone} />
                <p className="mt-2 text-sm font-medium">{c.title}</p>
                <p className="mt-1 line-clamp-3 text-xs text-muted-foreground">{c.detail}</p>
              </div>
            ))}
          </div>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title="Branch Timeline & Recent Activity"
        description="Combined activity feed from Branch Surgeon and repository-wide analyses"
        defaultOpen
      >
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Branch Timeline</CardTitle>
              <CardDescription>
                Activity + reviews from GET /branch-surgeon
              </CardDescription>
            </CardHeader>
            <CardContent>
              {workspace.isLoading && !data ? (
                <ListSkeleton rows={4} />
              ) : !timeline.length ? (
                <EmptyState
                  className="py-6"
                  title="No timeline events"
                  description="Reviews and analysis activity will appear here."
                />
              ) : (
                <ul className="space-y-2">
                  {timeline.slice(0, 10).map((run) => (
                    <li
                      key={`${run.kind}-${run.id}`}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm"
                    >
                      <div className="flex items-center gap-2">
                        <StatusBadge label={run.kind} tone="info" />
                        <StatusBadge label={run.label} tone="muted" />
                        {run.status ? (
                          <span className="text-2xs text-muted-foreground">{run.status}</span>
                        ) : null}
                      </div>
                      <span className="text-xs text-muted-foreground">
                        {formatRelativeTime(run.at)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-base">Recent Analyses</CardTitle>
                  <CardDescription>Latest repository-wide operations</CardDescription>
                </div>
                <Button size="sm" variant="ghost" asChild>
                  <Link href="/history">View All</Link>
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {history.isLoading && !historyItems.length ? (
                <ListSkeleton rows={4} />
              ) : (
                <ul className="space-y-2">
                  {historyItems.slice(0, 8).map((item) => {
                    const link = deepLinkFor(item);
                    return (
                      <li key={item.id}>
                        <Link
                          href={link?.href || "/history"}
                          className="flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm hover:bg-muted/40"
                        >
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <StatusBadge
                                label={analysisTypeLabel(item.analysis_type)}
                                tone="info"
                              />
                              <StatusBadge label={item.status} />
                            </div>
                            <p className="mt-0.5 truncate text-xs text-muted-foreground">
                              {item.summary || "—"}
                            </p>
                          </div>
                          <span className="shrink-0 text-xs text-muted-foreground">
                            {formatRelativeTime(item.timestamp)}
                          </span>
                        </Link>
                      </li>
                    );
                  })}
                  {!history.isLoading && !historyItems.length ? (
                    <EmptyState
                      className="py-6"
                      title="No analyses yet"
                      description="Results appear here after reviews, recommendations, and more."
                    />
                  ) : null}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>
      </CollapsibleSection>

      <RunReviewDialog
        open={reviewOpen}
        onOpenChange={setReviewOpen}
        description="POST /review — feeds AI Summary & confidence"
      />
    </PageContainer>
  );
}

function Item({
  label,
  value,
  mono,
}: {
  label: string;
  value?: string | null;
  mono?: boolean;
}) {
  return (
    <div>
      <dt className="text-2xs uppercase text-muted-foreground">{label}</dt>
      <dd className={mono ? "mt-1 truncate font-mono text-xs" : "mt-1 truncate font-medium"}>
        {value || "—"}
      </dd>
    </div>
  );
}
