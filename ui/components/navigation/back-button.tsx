"use client";

import { ArrowLeft } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  canUseHistoryBack,
  logicalParentPath,
  shouldShowBack,
} from "@/lib/navigation-back";
import { cn } from "@/lib/utils";

export type BackButtonProps = {
  className?: string;
  /** Override logical parent when history cannot go back. */
  fallbackHref?: string;
  /** Force visibility; default follows feature-page rules (hidden on Dashboard). */
  forceShow?: boolean;
  /** Compact label for dense chrome (breadcrumbs row). */
  compact?: boolean;
};

function currentSearch(): string {
  if (typeof window === "undefined") return "";
  return window.location.search || "";
}

function useNavigateBack(fallbackHref?: string) {
  const router = useRouter();
  const pathname = usePathname() || "/";

  return React.useCallback(() => {
    const parent = fallbackHref || logicalParentPath(pathname, currentSearch());
    if (canUseHistoryBack()) {
      router.back();
      return;
    }
    router.push(parent);
  }, [fallbackHref, pathname, router]);
}

/**
 * In-app Back: `router.back()` when history exists, otherwise the logical parent.
 * Does not call `history.back()` directly so we stay within the Next.js router.
 */
export function BackButton({
  className,
  fallbackHref,
  forceShow,
  compact = false,
}: BackButtonProps) {
  const pathname = usePathname() || "/";
  const visible = forceShow ?? shouldShowBack(pathname);
  const goBack = useNavigateBack(fallbackHref);

  if (!visible) return null;

  return (
    <Button
      type="button"
      variant="ghost"
      size={compact ? "xs" : "sm"}
      onClick={goBack}
      aria-label="Go Back"
      className={cn(
        "shrink-0 gap-1 text-muted-foreground hover:text-foreground",
        "focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
    >
      <ArrowLeft className="size-3.5" aria-hidden />
      Back
    </Button>
  );
}

/**
 * Global Alt+← shortcut. Skips when focus is in editable fields so it does
 * not fight typing; does not call preventDefault on browser-native Back.
 */
export function useBackKeyboardShortcut(enabled = true) {
  const pathname = usePathname() || "/";
  const goBack = useNavigateBack();

  React.useEffect(() => {
    if (!enabled || !shouldShowBack(pathname)) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (!event.altKey || event.key !== "ArrowLeft") return;
      if (event.metaKey || event.ctrlKey || event.shiftKey) return;

      const target = event.target as HTMLElement | null;
      if (target) {
        const tag = target.tagName;
        if (
          tag === "INPUT" ||
          tag === "TEXTAREA" ||
          tag === "SELECT" ||
          target.isContentEditable
        ) {
          return;
        }
      }

      // Intentionally no preventDefault — browser may also handle Alt+Left.
      goBack();
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [enabled, goBack, pathname]);
}
