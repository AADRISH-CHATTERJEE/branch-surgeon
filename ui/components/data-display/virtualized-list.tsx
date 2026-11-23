"use client";

import { useVirtualizer } from "@tanstack/react-virtual";
import * as React from "react";

import { VIRTUAL_ROW_HEIGHT } from "@/lib/query-limits";
import { cn } from "@/lib/utils";

type VirtualizedListProps<T> = {
  items: T[];
  getItemKey: (item: T, index: number) => string;
  estimateSize?: number;
  className?: string;
  heightClassName?: string;
  renderItem: (item: T, index: number) => React.ReactNode;
  /** Scroll this index into view when it changes (selection / keyboard). */
  scrollToIndex?: number | null;
};

/** Windowed list for large datasets (repository files, etc.). */
export function VirtualizedList<T>({
  items,
  getItemKey,
  estimateSize = VIRTUAL_ROW_HEIGHT,
  className,
  heightClassName = "h-[min(70vh,640px)]",
  renderItem,
  scrollToIndex = null,
}: VirtualizedListProps<T>) {
  const parentRef = React.useRef<HTMLDivElement>(null);

  // TanStack Virtual is incompatible with React Compiler memoization.
  // eslint-disable-next-line react-hooks/incompatible-library -- intentional virtualization
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => estimateSize,
    overscan: 12,
  });

  const lastScrollIndex = React.useRef<number | null>(null);
  React.useEffect(() => {
    if (scrollToIndex == null || scrollToIndex < 0 || scrollToIndex >= items.length) {
      return;
    }
    // Only scroll when the target index changes — avoid fighting user clicks
    // when the virtualizer instance identity churns across renders.
    if (lastScrollIndex.current === scrollToIndex) return;
    lastScrollIndex.current = scrollToIndex;
    virtualizer.scrollToIndex(scrollToIndex, { align: "auto" });
  }, [scrollToIndex, items.length, virtualizer]);

  // Remeasure when items arrive — first paint can leave zero virtual rows.
  React.useEffect(() => {
    if (!items.length) return;
    virtualizer.measure();
  }, [items.length, virtualizer]);

  // Small lists: skip virtualization so the file panel always paints rows.
  if (items.length > 0 && items.length <= 80) {
    return (
      <div
        className={cn("overflow-auto rounded-lg border", heightClassName, className)}
        tabIndex={0}
      >
        <ul className="divide-y">
          {items.map((item, index) => (
            <li key={getItemKey(item, index)} className="min-h-9">
              {renderItem(item, index)}
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div
      ref={parentRef}
      className={cn("overflow-auto rounded-lg border", heightClassName, className)}
      tabIndex={0}
    >
      <div
        className="relative w-full"
        style={{ height: `${virtualizer.getTotalSize()}px` }}
      >
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const item = items[virtualRow.index];
          return (
            <div
              key={getItemKey(item, virtualRow.index)}
              className="absolute top-0 left-0 w-full border-b last:border-0"
              style={{
                height: `${virtualRow.size}px`,
                transform: `translateY(${virtualRow.start}px)`,
              }}
            >
              {renderItem(item, virtualRow.index)}
            </div>
          );
        })}
      </div>
    </div>
  );
}
