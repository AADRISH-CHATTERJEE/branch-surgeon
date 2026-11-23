import type { AnalysisRun } from "@/types/domain";

export type ActivityKind =
  | "review"
  | "recommend"
  | "transform"
  | "rollback"
  | "graph"
  | "index"
  | "rules"
  | "health"
  | "other";

export function classifyCommand(command: string): ActivityKind {
  const c = command.toLowerCase();
  if (c.includes("review")) return "review";
  if (c.includes("recommend")) return "recommend";
  if (c.includes("rollback")) return "rollback";
  if (c.includes("transform")) return "transform";
  if (c.includes("graph")) return "graph";
  if (c.includes("index") || c.includes("embed")) return "index";
  if (c.includes("rules")) return "rules";
  if (c.includes("health")) return "health";
  return "other";
}

export function kindLabel(kind: ActivityKind): string {
  switch (kind) {
    case "review":
      return "Review";
    case "recommend":
      return "Recommendation";
    case "transform":
      return "Transformation";
    case "rollback":
      return "Rollback";
    case "graph":
      return "Graph Build";
    case "index":
      return "Index";
    case "rules":
      return "Rules Check";
    case "health":
      return "Health Analysis";
    default:
      return "Analysis";
  }
}

export function kindColor(kind: ActivityKind): string {
  switch (kind) {
    case "review":
      return "var(--chart-series-1)";
    case "recommend":
      return "var(--chart-series-4)";
    case "transform":
      return "var(--chart-series-2)";
    case "rollback":
      return "var(--chart-series-5)";
    case "graph":
      return "var(--chart-series-3)";
    case "index":
      return "var(--chart-series-6)";
    case "rules":
      return "var(--chart-series-7)";
    case "health":
      return "var(--chart-series-2)";
    default:
      return "var(--muted-foreground)";
  }
}

export function linkForRun(run: AnalysisRun): { href: string; label: string } | null {
  const kind = classifyCommand(run.command);
  switch (kind) {
    case "review":
      return { href: "/reviews", label: "Open review" };
    case "recommend":
      return { href: "/recommendations", label: "Open recommendations" };
    case "graph":
      return { href: "/repository/graph", label: "Open graph" };
    case "transform":
    case "rollback":
      return { href: "/transform", label: "Open transform" };
    case "rules":
      return { href: "/rules", label: "Open rules" };
    case "index":
      return { href: "/repository", label: "Open repository" };
    case "health":
      return { href: "/repository/health", label: "Open health" };
    default:
      return null;
  }
}

export function isSameLocalDay(iso: string | null | undefined, now = new Date()): boolean {
  if (!iso) return false;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return false;
  return (
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  );
}

export function dailyCounts(runs: AnalysisRun[], days = 14): { key: string; label: string; value: number }[] {
  const buckets: { key: string; label: string; value: number }[] = [];
  const now = new Date();
  for (let i = days - 1; i >= 0; i -= 1) {
    const d = new Date(now);
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    buckets.push({
      key,
      label: `${d.getMonth() + 1}/${d.getDate()}`,
      value: 0,
    });
  }
  const index = new Map(buckets.map((b) => [b.key, b]));
  for (const run of runs) {
    if (!run.created_at) continue;
    const key = new Date(run.created_at).toISOString().slice(0, 10);
    const bucket = index.get(key);
    if (bucket) bucket.value += 1;
  }
  return buckets;
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "Unavailable";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}
