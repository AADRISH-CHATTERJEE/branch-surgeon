import type { LucideIcon } from "lucide-react";

import { MetricCard } from "@/components/data-display/metric-card";
import { cn } from "@/lib/utils";

export type MetricStripItem = {
  key: string;
  label: string;
  value: string | number;
  hint?: string;
  icon?: LucideIcon;
  variant?: "default" | "primary" | "danger" | "warn";
  onClick?: () => void;
  href?: string;
};

type MetricStripProps = {
  items: MetricStripItem[];
  compact?: boolean;
  className?: string;
  /** Tailwind grid cols classes */
  columnsClassName?: string;
};

export function MetricStrip({
  items,
  compact = true,
  className,
  columnsClassName,
}: MetricStripProps) {
  const cols =
    columnsClassName ??
    (items.length <= 4
      ? "sm:grid-cols-2 lg:grid-cols-4"
      : items.length <= 6
        ? "sm:grid-cols-3 lg:grid-cols-6"
        : "sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8");

  return (
    <div className={cn("grid gap-2", cols, className)}>
      {items.map((item) => (
        <MetricCard
          key={item.key}
          label={item.label}
          value={item.value}
          hint={item.hint}
          icon={item.icon}
          variant={item.variant}
          compact={compact}
          onClick={item.onClick}
          href={item.href}
        />
      ))}
    </div>
  );
}
