import { StatusBadge } from "@/components/data-display/status-badge";
import type { StatusTone } from "@/lib/severity";
import { cn } from "@/lib/utils";

export type LifecycleStatus = "pending" | "applied" | "resolved" | "ignored" | string;

const LIFECYCLE_TONE: Record<string, StatusTone> = {
  pending: "warn",
  applied: "info",
  resolved: "success",
  ignored: "muted",
};

const LIFECYCLE_DOT: Record<string, string> = {
  pending: "bg-amber-400",
  applied: "bg-sky-500",
  resolved: "bg-emerald-500",
  ignored: "bg-zinc-400",
};

export const LIFECYCLE_LEGEND = [
  {
    status: "pending",
    label: "Pending",
    description: "Not addressed yet.",
  },
  {
    status: "applied",
    label: "Applied",
    description: "AI patch applied, awaiting verification.",
  },
  {
    status: "resolved",
    label: "Resolved",
    description: "Verified fixed.",
  },
  {
    status: "ignored",
    label: "Ignored",
    description: "Intentionally dismissed.",
  },
] as const;

export function lifecycleTone(status: string): StatusTone {
  return LIFECYCLE_TONE[status.toLowerCase()] ?? "muted";
}

export function LifecycleBadge({
  status,
  className,
}: {
  status: LifecycleStatus;
  className?: string;
}) {
  const normalized = (status || "pending").toLowerCase();
  return (
    <StatusBadge
      label={normalized}
      tone={lifecycleTone(normalized)}
      className={className}
    />
  );
}

export function LifecycleLegend({
  className,
  compact = false,
}: {
  className?: string;
  /** Single-column legend for narrow side panels. */
  compact?: boolean;
}) {
  return (
    <ul
      className={cn(
        "grid gap-1.5 text-xs text-muted-foreground",
        compact ? "grid-cols-1" : "sm:grid-cols-2 xl:grid-cols-4",
        className,
      )}
    >
      {LIFECYCLE_LEGEND.map((item) => (
        <li key={item.status} className="flex min-w-0 items-start gap-2">
          <span
            className={cn(
              "mt-1 size-2.5 shrink-0 rounded-full",
              LIFECYCLE_DOT[item.status],
            )}
            aria-hidden
          />
          <span className="min-w-0 break-words">
            <span className="font-medium text-foreground">{item.label}</span>
            {" – "}
            {item.description}
          </span>
        </li>
      ))}
    </ul>
  );
}
