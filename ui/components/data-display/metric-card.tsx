import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

type MetricCardProps = {
  label: string;
  value: string | number;
  hint?: string;
  icon?: LucideIcon;
  variant?: "default" | "primary" | "danger" | "warn";
  compact?: boolean;
  className?: string;
  onClick?: () => void;
  href?: string;
};

export function MetricCard({
  label,
  value,
  hint,
  icon: Icon,
  variant = "default",
  compact = false,
  className,
  onClick,
  href,
}: MetricCardProps) {
  const variantClasses = {
    default: "",
    primary: "border-primary/50 bg-primary/5",
    danger: "border-destructive/50 bg-destructive/5",
    warn: "border-yellow-500/50 bg-yellow-500/5",
  };

  const interactive = Boolean(onClick || href);
  const classNames = cn(
    "rounded-lg border bg-card text-card-foreground text-left",
    compact ? "p-2" : "p-4",
    variantClasses[variant],
    interactive &&
      "transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
    className,
  );

  const body = (
    <>
      <div className="flex items-start justify-between gap-2">
        <p
          className={cn(
            "font-medium tracking-wide text-muted-foreground uppercase",
            compact ? "text-2xs" : "text-xs",
          )}
        >
          {label}
        </p>
        {Icon ? <Icon className="size-4 text-muted-foreground" /> : null}
      </div>
      <p
        className={cn(
          "font-semibold tracking-tight tabular-nums",
          compact ? "mt-1 text-lg" : "mt-2 text-2xl",
        )}
      >
        {value}
      </p>
      {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
    </>
  );

  if (href) {
    return (
      <a href={href} className={cn(classNames, "block")} onClick={onClick}>
        {body}
      </a>
    );
  }

  if (onClick) {
    return (
      <button type="button" className={classNames} onClick={onClick}>
        {body}
      </button>
    );
  }

  return <div className={classNames}>{body}</div>;
}
