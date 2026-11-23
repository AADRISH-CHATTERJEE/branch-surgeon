import { MetricCard } from "@/components/data-display/metric-card";

import type { GraphStats } from "../lib/graph-analytics";

type GraphStatsBarProps = {
  stats: GraphStats;
  fromSummary?: boolean;
};

export function GraphStatsBar({ stats, fromSummary }: GraphStatsBarProps) {
  const items = [
    { label: "Nodes", value: stats.nodes },
    { label: "Edges", value: stats.edges },
    { label: "Files", value: stats.files },
    { label: "Classes", value: stats.classes },
    { label: "Functions", value: stats.functions },
    { label: "Dependencies", value: stats.dependencies },
    { label: "Largest component", value: stats.largestComponent },
  ];

  return (
    <div className="space-y-1">
      <div className="grid gap-2 sm:grid-cols-4 lg:grid-cols-7">
        {items.map((item) => (
          <MetricCard key={item.label} label={item.label} value={item.value} compact />
        ))}
      </div>
      {fromSummary ? (
        <p className="text-2xs text-muted-foreground">
          Counts derived from GET /graph/full (and GET /graph summary when available).
        </p>
      ) : null}
    </div>
  );
}
