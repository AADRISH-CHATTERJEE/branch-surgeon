import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type ErrorStateProps = {
  title?: string;
  description?: string;
  errors?: string[];
  onRetry?: () => void;
  className?: string;
};

export function ErrorState({
  title = "Something went wrong",
  description,
  errors,
  onRetry,
  className,
}: ErrorStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-6 py-12 text-center",
        className,
      )}
    >
      <AlertTriangle className="size-5 text-destructive" />
      <div className="space-y-1">
        <h3 className="text-sm font-medium">{title}</h3>
        {description ? (
          <p className="max-w-md text-sm text-muted-foreground">{description}</p>
        ) : null}
        {errors?.length ? (
          <ul className="mt-2 space-y-0.5 text-left text-xs text-muted-foreground">
            {errors.map((err) => (
              <li key={err}>• {err}</li>
            ))}
          </ul>
        ) : null}
      </div>
      {onRetry ? (
        <Button size="sm" variant="outline" onClick={onRetry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}
