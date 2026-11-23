import { LifecycleBadge } from "@/components/data-display/lifecycle-badge";
import { StatusBadge } from "@/components/data-display/status-badge";
import { Card } from "@/components/ui/card";
import { formatRelativeTime } from "@/lib/format";
import type { PersistedRecommendation } from "@/types/domain";

type RecommendationCardProps = {
  recommendation: PersistedRecommendation;
  onClick?: () => void;
};

export function RecommendationCard({
  recommendation,
  onClick,
}: RecommendationCardProps) {
  return (
    <Card
      className="cursor-pointer transition-colors hover:border-primary/50 hover:shadow-sm"
      onClick={onClick}
    >
      <div className="p-4">
        <div className="flex items-start justify-between gap-2">
          <h3 className="flex-1 font-semibold leading-tight">
            {recommendation.title}
          </h3>
          <StatusBadge label={recommendation.priority} />
        </div>

        <p className="mt-2 line-clamp-3 text-sm text-muted-foreground">
          {recommendation.description}
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <StatusBadge label={recommendation.type} tone="info" />
          <LifecycleBadge status={recommendation.status} />
          {recommendation.effort ? (
            <StatusBadge label={recommendation.effort} tone="muted" />
          ) : null}
          {recommendation.confidence != null ? (
            <StatusBadge
              label={`${Math.round(recommendation.confidence * 100)}%`}
              tone="muted"
            />
          ) : null}
        </div>

        <div className="mt-3 text-xs text-muted-foreground">
          {formatRelativeTime(recommendation.created_at)}
        </div>
      </div>
    </Card>
  );
}
