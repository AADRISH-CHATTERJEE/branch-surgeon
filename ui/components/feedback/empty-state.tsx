import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type EmptyStateProps = {
  title: string;
  description?: string;
  icon?: LucideIcon;
  actionLabel?: string;
  onAction?: () => void;
  className?: string;
};

export function EmptyState({
  title,
  description,
  icon: Icon = Inbox,
  actionLabel,
  onAction,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed px-6 py-16 text-center",
        className,
      )}
    >
      <div className="flex size-10 items-center justify-center rounded-md border bg-muted/40">
        <Icon className="size-5 text-muted-foreground" />
      </div>
      <div className="space-y-1">
        <h3 className="text-sm font-medium">{title}</h3>
        {description ? (
          <p className="max-w-sm text-sm text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {actionLabel && onAction ? (
        <Button size="sm" onClick={onAction}>
          {actionLabel}
        </Button>
      ) : null}
    </div>
  );
}
