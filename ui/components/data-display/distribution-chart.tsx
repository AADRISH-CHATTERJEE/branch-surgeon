import { CHART_SERIES } from "@/lib/chart-colors";
import { cn } from "@/lib/utils";

export type DistributionItem = {
  key: string;
  label: string;
  value: number;
  color?: string;
};

type DistributionChartProps = {
  title?: string;
  items: DistributionItem[];
  /** bar = horizontal bars (default); stack = segmented bar approximating a pie */
  variant?: "bar" | "stack";
  className?: string;
  emptyLabel?: string;
};

const PALETTE = [...CHART_SERIES];

/**
 * Lightweight CSS distribution charts.
 * No chart library is installed in this project — do not add one for Phase 10.8/10.9.
 */
export function DistributionChart({
  title,
  items,
  variant = "bar",
  className,
  emptyLabel = "No data",
}: DistributionChartProps) {
  const total = items.reduce((s, i) => s + i.value, 0);
  const colored = items.map((item, i) => ({
    ...item,
    color: item.color ?? PALETTE[i % PALETTE.length]!,
  }));

  if (!total) {
    return (
      <div className={cn("rounded-lg border p-3", className)}>
        {title ? <p className="mb-2 text-xs font-semibold">{title}</p> : null}
        <p className="text-xs text-muted-foreground">{emptyLabel}</p>
      </div>
    );
  }

  return (
    <div className={cn("rounded-lg border p-3", className)}>
      {title ? <p className="mb-3 text-xs font-semibold">{title}</p> : null}

      {variant === "stack" ? (
        <div className="mb-3 flex h-3 overflow-hidden rounded-full bg-muted">
          {colored.map((item) => (
            <div
              key={item.key}
              title={`${item.label}: ${item.value}`}
              style={{
                width: `${(item.value / total) * 100}%`,
                background: item.color,
              }}
            />
          ))}
        </div>
      ) : null}

      <ul className="space-y-2">
        {colored.map((item) => {
          const pct = Math.round((item.value / total) * 100);
          return (
            <li key={item.key}>
              <div className="mb-0.5 flex items-center justify-between gap-2 text-xs">
                <span className="flex items-center gap-1.5 truncate">
                  <span
                    className="inline-block size-2 shrink-0 rounded-sm"
                    style={{ background: item.color }}
                  />
                  {item.label}
                </span>
                <span className="shrink-0 tabular-nums text-muted-foreground">
                  {item.value} · {pct}%
                </span>
              </div>
              {variant === "bar" ? (
                <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{ width: `${pct}%`, background: item.color }}
                  />
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
