"use client";

import { cn } from "@/lib/utils";

export type FilterOption = {
  value: string;
  label: string;
};

type FilterBarProps = {
  options: FilterOption[];
  value: string | null;
  onChange: (value: string | null) => void;
  allLabel?: string;
  className?: string;
};

export function FilterBar({
  options,
  value,
  onChange,
  allLabel = "All",
  className,
}: FilterBarProps) {
  return (
    <div className={cn("flex flex-wrap gap-1.5", className)}>
      <FilterChip active={value === null} onClick={() => onChange(null)} label={allLabel} />
      {options.map((opt) => (
        <FilterChip
          key={opt.value}
          active={value === opt.value}
          onClick={() => onChange(opt.value)}
          label={opt.label}
        />
      ))}
    </div>
  );
}

function FilterChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
        active
          ? "border-foreground/20 bg-foreground text-background"
          : "border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      {label}
    </button>
  );
}
