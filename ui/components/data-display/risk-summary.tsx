import { MetricCard } from "@/components/data-display/metric-card";
import { formatHealthScore } from "@/lib/format";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type RiskScores = {
  overall?: number;
  security?: number;
  architecture?: number;
  maintainability?: number;
  testing?: number;
};

type RiskSummaryProps = {
  scores: RiskScores;
  className?: string;
  /** When true, show muted "Not evaluated" for missing categories (Option B). Default hides them (Option A). */
  showUnevaluated?: boolean;
};

const CATEGORIES: { key: keyof RiskScores; label: string }[] = [
  { key: "overall", label: "Overall" },
  { key: "security", label: "Security" },
  { key: "architecture", label: "Architecture" },
  { key: "maintainability", label: "Maintainability" },
  { key: "testing", label: "Testing" },
];

export function RiskSummary({
  scores,
  className,
  showUnevaluated = false,
}: RiskSummaryProps) {
  const metrics = CATEGORIES.map((metric) => ({
    ...metric,
    value: scores[metric.key],
  })).filter((metric) => {
    if (metric.value != null) return true;
    // Prefer hiding unavailable category cards; Overall always shown when present.
    if (metric.key === "overall") return scores.overall != null;
    return showUnevaluated;
  });

  if (!metrics.length) {
    return (
      <Card className={className}>
        <div className="p-4">
          <h3 className="mb-1 text-sm font-semibold">Risk Assessment</h3>
          <p className="text-sm text-muted-foreground">Not evaluated</p>
        </div>
      </Card>
    );
  }

  const cols =
    metrics.length <= 1
      ? "sm:grid-cols-1 max-w-xs"
      : metrics.length <= 2
        ? "sm:grid-cols-2"
        : metrics.length <= 3
          ? "sm:grid-cols-3"
          : "sm:grid-cols-5";

  return (
    <Card className={className}>
      <div className="p-4">
        <h3 className="mb-3 text-sm font-semibold">Risk Assessment</h3>
        <div className={cn("grid gap-3", cols)}>
          {metrics.map((metric) => (
            <MetricCard
              key={metric.key}
              label={metric.label}
              value={
                metric.value != null
                  ? formatHealthScore(metric.value)
                  : "Not evaluated"
              }
              variant={metric.key === "overall" ? "primary" : "default"}
              compact
              className={
                metric.value == null ? "opacity-70 [&_*]:text-muted-foreground" : undefined
              }
            />
          ))}
        </div>
      </div>
    </Card>
  );
}
