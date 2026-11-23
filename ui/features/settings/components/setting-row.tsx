"use client";

import type { ReactNode } from "react";

import { StatusBadge } from "@/components/data-display/status-badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { HelpCircle } from "lucide-react";
import { cn } from "@/lib/utils";

type SettingRowProps = {
  label: string;
  description?: string;
  help?: string;
  badge?: { label: string; tone?: "muted" | "info" | "warn" | "success" | "danger" };
  children: ReactNode;
  className?: string;
};

export function SettingRow({
  label,
  description,
  help,
  badge,
  children,
  className,
}: SettingRowProps) {
  return (
    <div
      className={cn(
        "grid gap-3 border-b py-4 last:border-0 sm:grid-cols-[minmax(0,14rem)_1fr] sm:items-start",
        className,
      )}
    >
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-medium">{label}</p>
          {badge ? <StatusBadge label={badge.label} tone={badge.tone ?? "muted"} /> : null}
          {help ? (
            <TooltipProvider delayDuration={200}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    className="text-muted-foreground hover:text-foreground"
                    aria-label={`Help: ${label}`}
                  >
                    <HelpCircle className="size-3.5" />
                  </button>
                </TooltipTrigger>
                <TooltipContent className="max-w-xs">{help}</TooltipContent>
              </Tooltip>
            </TooltipProvider>
          ) : null}
        </div>
        {description ? (
          <p className="text-xs text-muted-foreground">{description}</p>
        ) : null}
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function PrefToggle({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-7 w-12 shrink-0 items-center rounded-full border transition-colors",
        checked ? "border-primary bg-primary" : "border-border bg-muted",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      <span
        className={cn(
          "pointer-events-none size-5 translate-x-1 rounded-full bg-background shadow transition-transform",
          checked && "translate-x-6",
        )}
      />
    </button>
  );
}
