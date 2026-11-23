import { MetricCard } from "@/components/data-display/metric-card";
import { StatusBadge } from "@/components/data-display/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatHealthScore, scoreLabel } from "@/lib/format";
import type { BranchSurgeonWorkspace } from "@/services/surgeon";

type SurgeryScoreCardProps = {
  surgery?: BranchSurgeonWorkspace["surgery"] | null;
  healthOverall?: number | null;
  criticalCount?: number;
};

export function SurgeryScoreCard({
  surgery,
  healthOverall,
  criticalCount,
}: SurgeryScoreCardProps) {
  const score = surgery?.score;
  const grade = surgery?.grade;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-base">Surgery Score</CardTitle>
          {grade ? <StatusBadge label={grade} tone="info" /> : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="rounded-lg border px-4 py-6 text-center">
          <p className="text-4xl font-semibold tabular-nums">
            {score != null ? score : "—"}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {grade || "No score"} · GET /branch-surgeon
          </p>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <MetricCard
            label="Repo health"
            value={
              healthOverall != null ? formatHealthScore(healthOverall) : "—"
            }
            hint={
              healthOverall != null
                ? `${scoreLabel(healthOverall)} · from workspace health`
                : "Health unavailable"
            }
            compact
          />
          <MetricCard
            label="Critical recs"
            value={criticalCount ?? "—"}
            hint="From workspace recommendations"
            variant={criticalCount && criticalCount > 0 ? "danger" : "default"}
            compact
          />
        </div>
      </CardContent>
    </Card>
  );
}
