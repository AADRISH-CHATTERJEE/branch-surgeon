import { StatusBadge } from "@/components/data-display/status-badge";
import { Card } from "@/components/ui/card";
import { formatRelativeTime } from "@/lib/format";
import { reviewSuggestionCount } from "@/lib/review-metrics";
import type { PersistedReview } from "@/types/domain";

type ReviewCardProps = {
  review: PersistedReview;
  onClick?: () => void;
  selected?: boolean;
};

export function ReviewCard({ review, onClick, selected }: ReviewCardProps) {
  const suggestionCount = reviewSuggestionCount(review);

  return (
    <Card
      className={`cursor-pointer transition-colors hover:bg-muted/50 ${
        selected ? "border-primary bg-muted" : ""
      }`}
      onClick={onClick}
    >
      <div className="p-4">
        <div className="flex items-center justify-between gap-2">
          <span className="font-semibold">
            {review.pr_number != null ? `PR #${review.pr_number}` : review.id.slice(0, 8)}
          </span>
          <StatusBadge label={review.risk || "unknown"} />
        </div>
        <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">
          {review.summary}
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>{formatRelativeTime(review.created_at)}</span>
          <span>•</span>
          <span>
            {suggestionCount} suggestion{suggestionCount === 1 ? "" : "s"}
          </span>
          <span>•</span>
          <span>
            {review.provider} · {review.model}
          </span>
        </div>
      </div>
    </Card>
  );
}
