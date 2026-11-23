import type { LucideIcon } from "lucide-react";
import { CircleSlash } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type UnavailableProps = {
  title?: string;
  description?: string;
  reason?: string;
  icon?: LucideIcon;
  actionLabel?: string;
  onAction?: () => void;
  compact?: boolean;
  className?: string;
};

/** Honest placeholder for missing API / persistence fields — never invents values. */
export function Unavailable({
  title = "Unavailable",
  description,
  reason,
  icon: Icon = CircleSlash,
  actionLabel,
  onAction,
  compact,
  className,
}: UnavailableProps) {
  return (
    <div
      className={cn(
        "rounded-md border border-dashed bg-muted/20 text-muted-foreground",
        compact ? "px-2 py-1.5" : "px-3 py-2.5",
        className,
      )}
    >
      <div className={cn("flex items-start gap-2", compact && "gap-1.5")}>
        <Icon className={cn("shrink-0 opacity-70", compact ? "size-3" : "size-4")} />
        <div className="min-w-0 flex-1">
          <p className={cn("font-medium", compact ? "text-2xs" : "text-xs")}>{title}</p>
          {description ? (
            <p className={cn("mt-0.5 opacity-90", compact ? "text-2xs" : "text-xs")}>
              {description}
            </p>
          ) : null}
          {reason ? (
            <p className={cn("mt-0.5 opacity-80", compact ? "text-2xs" : "text-xs")}>{reason}</p>
          ) : null}
          {actionLabel && onAction ? (
            <Button
              size="sm"
              variant="outline"
              className="mt-2"
              onClick={onAction}
            >
              {actionLabel}
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
