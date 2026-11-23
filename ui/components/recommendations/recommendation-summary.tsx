import { LifecycleLegend } from "@/components/data-display/lifecycle-badge";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/format";
import type { RecommendationRepositorySummary } from "@/types/domain";

type RecommendationSummaryProps = {
  critical: number;
  high: number;
  medium: number;
  low: number;
  pending?: number;
  applied?: number;
  resolved?: number;
  ignored?: number;
  selectedPriority?: string | null;
  onSelectPriority?: (priority: string | null) => void;
  /** Clarifies aggregation (e.g. loaded page vs repository totals). */
  caption?: string;
  /** Canonical summary provenance footer. */
  summaryMeta?: Pick<
    RecommendationRepositorySummary,
    | "last_updated"
    | "repository"
    | "repo_root"
    | "source"
    | "version"
    | "repository_id"
  > | null;
  className?: string;
};

export function RecommendationSummary({
  critical,
  high,
  medium,
  low,
  pending,
  applied,
  resolved,
  ignored,
  selectedPriority,
  onSelectPriority,
  caption,
  summaryMeta,
  className,
}: RecommendationSummaryProps) {
  const priorityCards = [
    { key: "critical", label: "Critical", value: critical },
    { key: "high", label: "High", value: high },
    { key: "medium", label: "Medium", value: medium },
    { key: "low", label: "Low", value: low },
  ];

  const statusCards = [
    ...(pending != null ? [{ key: "pending", label: "Pending", value: pending }] : []),
    ...(applied != null ? [{ key: "applied", label: "Applied", value: applied }] : []),
    ...(resolved != null ? [{ key: "resolved", label: "Resolved", value: resolved }] : []),
    ...(ignored != null ? [{ key: "ignored", label: "Ignored", value: ignored }] : []),
  ];

  return (
    <div className={cn("space-y-4", className)}>
      {caption ? (
        <p className="text-xs text-muted-foreground">{caption}</p>
      ) : null}
      <p className="text-2xs text-muted-foreground">
        Severity tiles count pending (open) recommendations only. Applied / Resolved /
        Ignored belong in lifecycle totals below.
      </p>
      <div className="grid gap-2 sm:grid-cols-4">
        {priorityCards.map((card) => (
          <button
            key={card.key}
            type="button"
            onClick={() =>
              onSelectPriority?.(
                selectedPriority === card.key ? null : card.key
              )
            }
            className={cn(
              "rounded-lg border p-3 text-left transition-colors hover:bg-muted/40",
              selectedPriority === card.key && "border-primary bg-muted"
            )}
          >
            <p className="text-xs capitalize text-muted-foreground">
              {card.label}
            </p>
            <p className="text-2xl font-semibold tabular-nums">{card.value}</p>
          </button>
        ))}
      </div>

      {statusCards.length > 0 && (
        <div
          className={cn(
            "grid gap-2",
            statusCards.length >= 4 ? "sm:grid-cols-4" : "sm:grid-cols-3",
          )}
        >
          {statusCards.map((card) => (
            <div
              key={card.key}
              className="rounded-lg border bg-card p-3 text-center"
            >
              <p className="text-xs capitalize text-muted-foreground">
                {card.label}
              </p>
              <p className="text-xl font-semibold tabular-nums">{card.value}</p>
            </div>
          ))}
        </div>
      )}

      <LifecycleLegend />

      {summaryMeta ? (
        <p className="text-2xs text-muted-foreground">
          Last Updated:{" "}
          {summaryMeta.last_updated
            ? formatRelativeTime(summaryMeta.last_updated)
            : "—"}
          {" · "}
          Repository: {summaryMeta.repository || summaryMeta.repo_root || "—"}
          {" · "}
          Source: {summaryMeta.source || "RecommendationStatsService"}
          {" · "}
          Recommendation Summary Version: {summaryMeta.version || "2"}
        </p>
      ) : null}
    </div>
  );
}
