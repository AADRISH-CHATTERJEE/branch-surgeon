"use client";

import * as React from "react";
import { ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";

type CollapsibleSectionProps = {
  title: string;
  description?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
  className?: string;
  /** Optional badge / status next to title */
  badge?: React.ReactNode;
};

/** Lightweight progressive-disclosure section (no new design language). */
export function CollapsibleSection({
  title,
  description,
  defaultOpen = true,
  children,
  className,
  badge,
}: CollapsibleSectionProps) {
  const [open, setOpen] = React.useState(defaultOpen);
  const panelId = React.useId();

  return (
    <section className={cn("rounded-lg border bg-card", className)}>
      <button
        type="button"
        className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
      >
        <ChevronDown
          className={cn(
            "mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform duration-200 motion-reduce:transition-none",
            !open && "-rotate-90",
          )}
          aria-hidden
        />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold">{title}</span>
            {badge}
          </span>
          {description ? (
            <span className="mt-0.5 block text-xs text-muted-foreground">{description}</span>
          ) : null}
        </span>
      </button>
      {open ? (
        <div id={panelId} className="border-t px-4 py-4">
          {children}
        </div>
      ) : null}
    </section>
  );
}
