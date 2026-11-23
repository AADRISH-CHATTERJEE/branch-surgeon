"use client";

import { usePathname } from "next/navigation";

import { breadcrumbsForPath } from "@/lib/navigation";

/** Announces route changes to screen readers without visual chrome. */
export function RouteAnnouncer() {
  const pathname = usePathname();
  const crumbs = breadcrumbsForPath(pathname);
  const label = crumbs.map((c) => c.label).join(" / ") || "Refactory";

  return (
    <div className="sr-only" aria-live="polite" aria-atomic="true">
      {`Navigated to ${label}`}
    </div>
  );
}
