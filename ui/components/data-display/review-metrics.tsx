import { MetricCard } from "@/components/data-display/metric-card";
import { Card } from "@/components/ui/card";

type ReviewMetricsProps = {
  filesReviewed: number;
  suggestionsCount: number;
  criticalCount: number;
  warningCount: number;
  duration?: string;
  className?: string;
};

export function ReviewMetrics({
  filesReviewed,
  suggestionsCount,
  criticalCount,
  warningCount,
  duration,
  className,
}: ReviewMetricsProps) {
  return (
    <Card className={className}>
      <div className="p-4">
        <h3 className="mb-3 text-sm font-semibold">Review Metrics</h3>
        <div className="grid gap-3 sm:grid-cols-4">
          <MetricCard label="Files" value={filesReviewed} compact />
          <MetricCard label="Suggestions" value={suggestionsCount} compact />
          <MetricCard label="Critical" value={criticalCount} variant="danger" compact />
          <MetricCard label="Warnings" value={warningCount} variant="warn" compact />
        </div>
        {duration && (
          <p className="mt-3 text-xs text-muted-foreground">Duration: {duration}</p>
        )}
      </div>
    </Card>
  );
}
