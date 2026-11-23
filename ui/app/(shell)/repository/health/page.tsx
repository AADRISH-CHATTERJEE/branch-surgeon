"use client";

import { MetricStrip } from "@/components/data-display/metric-strip";
import { ErrorState } from "@/components/feedback/error-state";
import { MetricSkeleton } from "@/components/feedback/loading-skeletons";
import { PageContainer } from "@/components/layout/page-container";
import { PageHeader } from "@/components/page-header";
import { riskFromHealth, scoreLabel } from "@/lib/format";
import { useRepositoryHealth } from "@/queries/use-repository";
import { ApiError } from "@/services/errors";

export default function RepositoryHealthPage() {
  const health = useRepositoryHealth();

  const scores = health.data?.scores;
  const overall = scores?.overall ?? 0;

  return (
    <PageContainer className="space-y-6">
      <PageHeader
        title="Repository Health"
        description="Latest health scan from GET /repository/health — recommendation counts are scan findings, not persisted DB totals."
      />

      {health.isLoading && !health.data ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <MetricSkeleton key={i} />
          ))}
        </div>
      ) : health.isError ? (
        <ErrorState
          title="Health unavailable"
          description={health.error instanceof ApiError ? health.error.message : undefined}
          onRetry={() => void health.refetch()}
        />
      ) : (
        <>
          <MetricStrip
            compact={false}
            items={[
              {
                key: "overall",
                label: "Overall",
                value: overall.toFixed(0),
                hint: scoreLabel(overall),
              },
              {
                key: "risk",
                label: "Risk",
                value: riskFromHealth(overall, health.data?.critical_count ?? 0),
              },
              {
                key: "recs",
                label: "Scan findings",
                value: health.data?.recommendations_count ?? 0,
                hint: "This health scan",
              },
              {
                key: "critical",
                label: "Scan critical",
                value: health.data?.critical_count ?? 0,
                hint: "This health scan",
              },
            ]}
          />
          {scores ? (
            <div className="grid gap-2 rounded-lg border p-4 sm:grid-cols-2">
              {Object.entries(scores)
                .filter(([k]) => k !== "overall")
                .map(([k, v]) => (
                  <div key={k} className="flex justify-between text-sm">
                    <span className="capitalize text-muted-foreground">
                      {k.replace("_", " ")}
                    </span>
                    <span className="font-medium tabular-nums">{Number(v).toFixed(0)}</span>
                  </div>
                ))}
            </div>
          ) : null}
        </>
      )}
    </PageContainer>
  );
}
