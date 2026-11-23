"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";

import { BackButton } from "@/components/navigation/back-button";
import { shouldShowBack } from "@/lib/navigation-back";
import { cn } from "@/lib/utils";
import { useBackNav } from "@/providers/back-nav-provider";

type PageHeaderProps = {
  title: string;
  description?: string;
  actions?: ReactNode;
  className?: string;
  /**
   * Show in-app Back above the title.
   * - `auto` (default): feature pages only; skipped when shell chrome already shows Back
   * - `true` / `false`: force
   */
  showBack?: boolean | "auto";
  /** Override logical parent for Back fallback. */
  backFallbackHref?: string;
};

export function PageHeader({
  title,
  description,
  actions,
  className,
  showBack = "auto",
  backFallbackHref,
}: PageHeaderProps) {
  const pathname = usePathname() || "/";
  const { chromeProvidesBack } = useBackNav();

  // Shell chrome already places Back before breadcrumbs — avoid a second control.
  // Outside the shell (or when forced), feature pages still get PageHeader Back.
  const autoShow = shouldShowBack(pathname) && !chromeProvidesBack;
  const visible = showBack === true || (showBack === "auto" && autoShow);

  return (
    <div
      className={cn(
        "flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between",
        className,
      )}
    >
      <div className="space-y-1">
        {visible ? (
          <BackButton
            className="-ml-2 mb-0.5"
            fallbackHref={backFallbackHref}
            forceShow
          />
        ) : null}
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description ? (
          <p className="max-w-2xl text-sm text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {actions ? (
        <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
      ) : null}
    </div>
  );
}
