"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { MetricStrip } from "@/components/data-display/metric-strip";
import { EmptyState } from "@/components/feedback/empty-state";
import { ErrorState } from "@/components/feedback/error-state";
import { MetricSkeleton } from "@/components/feedback/loading-skeletons";
import { PageContainer } from "@/components/layout/page-container";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { useApiOptions } from "@/hooks/use-api-options";
import { useOrgContext } from "@/providers/org-context";
import { fetchOrganizationDashboard } from "@/services/organizations";

export function OrganizationDashboardView() {
  const { organizationId, organization } = useOrgContext();
  const opts = useApiOptions();
  const dash = useQuery({
    queryKey: ["org-dashboard", organizationId ?? "none", opts.repoRoot ?? "default"],
    queryFn: ({ signal }) =>
      fetchOrganizationDashboard(organizationId!, { ...opts, signal }),
    enabled: opts.hydrated && Boolean(organizationId),
    staleTime: 20_000,
  });

  if (!organizationId) {
    return (
      <PageContainer>
        <EmptyState
          title="No organization selected"
          description="Create or select an organization to view multi-repo metrics."
        />
      </PageContainer>
    );
  }

  if (dash.isError) {
    return (
      <PageContainer>
        <ErrorState
          title="Organization dashboard unavailable"
          description={
            dash.error instanceof Error
              ? dash.error.message
              : "Unable to load organization dashboard"
          }
          onRetry={() => void dash.refetch()}
        />
      </PageContainer>
    );
  }

  const data = dash.data;

  return (
    <PageContainer>
      <PageHeader
        title={organization?.name ?? "Organization"}
        description="Repositories, teams, reviews, and rule health across the org."
        actions={
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline" size="sm">
              <Link href="/organization/teams">Teams</Link>
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link href="/organization/members">Members</Link>
            </Button>
            <Button asChild size="sm">
              <Link href="/organization/settings">Settings</Link>
            </Button>
          </div>
        }
      />

      {dash.isLoading || !data ? (
        <MetricSkeleton />
      ) : (
        <MetricStrip
          items={[
            {
              key: "repos",
              label: "Repositories",
              value: String(data.counts.repositories),
            },
            {
              key: "devs",
              label: "Developers",
              value: String(data.counts.developers),
            },
            { key: "teams", label: "Teams", value: String(data.counts.teams) },
            {
              key: "reviews",
              label: "Open reviews",
              value: String(data.open_reviews),
            },
            {
              key: "recs",
              label: "Open recommendations",
              value: String(data.open_recommendations),
            },
            {
              key: "violations",
              label: "Rule violations",
              value: String(data.rule_violations),
            },
            {
              key: "patch",
              label: "Patch success %",
              value:
                data.patch_success_pct == null
                  ? "—"
                  : `${data.patch_success_pct}%`,
            },
            {
              key: "review-pct",
              label: "Review success %",
              value:
                data.review_success_pct == null
                  ? "—"
                  : `${data.review_success_pct}%`,
            },
          ]}
        />
      )}

      <section className="mt-8 grid gap-6 lg:grid-cols-2">
        <div>
          <h2 className="mb-3 text-sm font-semibold tracking-tight">Repositories</h2>
          {!data?.repositories.length ? (
            <p className="text-sm text-muted-foreground">
              No repositories linked. Add paths under Organization Settings.
            </p>
          ) : (
            <ul className="space-y-2 text-sm">
              {data.repositories.map((r) => (
                <li key={r.id} className="rounded-md border px-3 py-2">
                  <div className="font-medium">{r.repository_name}</div>
                  <div className="truncate font-mono text-2xs text-muted-foreground">
                    {r.repository_root_path}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h2 className="mb-3 text-sm font-semibold tracking-tight">Teams</h2>
          {!data?.teams.length ? (
            <p className="text-sm text-muted-foreground">No teams yet.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {data.teams.map((t) => (
                <li key={t.id} className="rounded-md border px-3 py-2">
                  <div className="font-medium">{t.name}</div>
                  <div className="text-muted-foreground">
                    {(t.member_ids?.length ?? 0)} members ·{" "}
                    {(t.repository_ids?.length ?? 0)} repos
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </PageContainer>
  );
}
