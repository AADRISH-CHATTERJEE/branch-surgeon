"use client";

import * as React from "react";
import type { ReactNode } from "react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

type DetailDrawerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  badges?: ReactNode;
  metadata?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  className?: string;
  /** Default sm:max-w-lg */
  widthClassName?: string;
};

/**
 * Side drawer. Esc closes via Radix Sheet.
 * On close, focus returns to the element that opened the drawer (or main).
 */
export function DetailDrawer({
  open,
  onOpenChange,
  title,
  description,
  badges,
  metadata,
  children,
  footer,
  className,
  widthClassName = "sm:max-w-lg",
}: DetailDrawerProps) {
  const triggerRef = React.useRef<HTMLElement | null>(null);

  React.useEffect(() => {
    if (open) {
      const active = document.activeElement;
      if (active instanceof HTMLElement) {
        triggerRef.current = active;
      }
    }
  }, [open]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        className={cn("flex w-full flex-col overflow-hidden p-0", widthClassName, className)}
        onCloseAutoFocus={(e) => {
          e.preventDefault();
          const trigger = triggerRef.current;
          if (trigger && document.contains(trigger)) {
            trigger.focus();
            return;
          }
          document
            .getElementById("main-content")
            ?.focus({ preventScroll: true });
          window.scrollTo(0, 0);
        }}
      >
        <SheetHeader className="shrink-0 border-b px-4 py-4 text-left">
          <SheetTitle>{title}</SheetTitle>
          {description ? <SheetDescription>{description}</SheetDescription> : null}
          {badges ? <div className="mt-2 flex flex-wrap gap-2">{badges}</div> : null}
          {metadata ? <div className="mt-2 text-xs text-muted-foreground">{metadata}</div> : null}
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">{children}</div>
        {footer ? (
          <SheetFooter className="shrink-0 border-t px-4 py-3 sm:justify-start">
            {footer}
          </SheetFooter>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
