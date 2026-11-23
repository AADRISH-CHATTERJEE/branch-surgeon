"use client";

import { useVirtualizer } from "@tanstack/react-virtual";
import type { ReactNode } from "react";
import * as React from "react";

import { EmptyState } from "@/components/feedback/empty-state";
import { ListSkeleton } from "@/components/feedback/loading-skeletons";
import { VIRTUALIZE_ROW_THRESHOLD, VIRTUAL_ROW_HEIGHT } from "@/lib/query-limits";
import { cn } from "@/lib/utils";

export type DataTableColumn<T> = {
  id: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  sortable?: boolean;
  sortValue?: (row: T) => string | number | null | undefined;
  className?: string;
  headerClassName?: string;
};

export type DataTableSort = {
  id: string;
  order: "asc" | "desc";
};

type DataTableProps<T> = {
  columns: DataTableColumn<T>[];
  data: T[];
  getRowId: (row: T) => string;
  onRowClick?: (row: T) => void;
  isLoading?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
  emptyActionLabel?: string;
  onEmptyAction?: () => void;
  toolbar?: ReactNode;
  sort?: DataTableSort | null;
  onSortChange?: (sort: DataTableSort) => void;
  selectedId?: string | null;
  className?: string;
  /** Override auto-virtualization threshold */
  virtualizeThreshold?: number;
};

export function DataTable<T>({
  columns,
  data,
  getRowId,
  onRowClick,
  isLoading,
  emptyTitle = "No results",
  emptyDescription,
  emptyActionLabel,
  onEmptyAction,
  toolbar,
  sort,
  onSortChange,
  selectedId,
  className,
  virtualizeThreshold = VIRTUALIZE_ROW_THRESHOLD,
}: DataTableProps<T>) {
  const sorted = React.useMemo(() => {
    if (!sort) return data;
    const col = columns.find((c) => c.id === sort.id);
    if (!col?.sortValue) return data;
    const copy = [...data];
    copy.sort((a, b) => {
      const av = col.sortValue!(a);
      const bv = col.sortValue!(b);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp =
        typeof av === "number" && typeof bv === "number"
          ? av - bv
          : String(av).localeCompare(String(bv));
      return sort.order === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [data, sort, columns]);

  const toggleSort = (columnId: string) => {
    if (!onSortChange) return;
    if (sort?.id === columnId) {
      onSortChange({
        id: columnId,
        order: sort.order === "asc" ? "desc" : "asc",
      });
    } else {
      onSortChange({ id: columnId, order: "desc" });
    }
  };

  const useVirtual = sorted.length > virtualizeThreshold;
  const parentRef = React.useRef<HTMLDivElement>(null);
  // TanStack Virtual is incompatible with React Compiler memoization.
  // eslint-disable-next-line react-hooks/incompatible-library -- intentional virtualization
  const virtualizer = useVirtualizer({
    count: useVirtual ? sorted.length : 0,
    getScrollElement: () => parentRef.current,
    estimateSize: () => VIRTUAL_ROW_HEIGHT,
    overscan: 10,
  });

  return (
    <div className={cn("space-y-3", className)}>
      {toolbar ? <div className="flex flex-wrap items-center gap-2">{toolbar}</div> : null}

      {isLoading ? (
        <ListSkeleton rows={6} />
      ) : !sorted.length ? (
        <EmptyState
          title={emptyTitle}
          description={emptyDescription}
          actionLabel={emptyActionLabel}
          onAction={onEmptyAction}
          className="py-12"
        />
      ) : useVirtual ? (
        <div className="overflow-hidden rounded-lg border">
          <div className="sticky top-0 z-10 grid border-b bg-muted/40 text-left text-xs text-muted-foreground backdrop-blur"
            style={{
              gridTemplateColumns: `repeat(${columns.length}, minmax(0, 1fr))`,
            }}
          >
            {columns.map((col) => (
              <div
                key={col.id}
                className={cn("px-3 py-2 font-medium", col.headerClassName)}
              >
                {col.sortable && onSortChange ? (
                  <button
                    type="button"
                    onClick={() => toggleSort(col.id)}
                    className="inline-flex items-center gap-1 hover:text-foreground"
                  >
                    {col.header}
                    {sort?.id === col.id ? (
                      <span aria-hidden>{sort.order === "asc" ? "↑" : "↓"}</span>
                    ) : null}
                  </button>
                ) : (
                  col.header
                )}
              </div>
            ))}
          </div>
          <div
            ref={parentRef}
            className="max-h-[min(60vh,560px)] overflow-auto"
          >
            <div
              className="relative w-full"
              style={{ height: `${virtualizer.getTotalSize()}px` }}
            >
              {virtualizer.getVirtualItems().map((virtualRow) => {
                const row = sorted[virtualRow.index];
                const id = getRowId(row);
                return (
                  <div
                    key={id}
                    role={onRowClick ? "button" : undefined}
                    tabIndex={onRowClick ? 0 : undefined}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                    onKeyDown={
                      onRowClick
                        ? (e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              onRowClick(row);
                            }
                          }
                        : undefined
                    }
                    className={cn(
                      "absolute top-0 left-0 grid w-full border-b text-sm last:border-0",
                      onRowClick &&
                        "cursor-pointer hover:bg-muted/30 focus-visible:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset",
                      selectedId === id && "bg-muted/50",
                    )}
                    aria-selected={selectedId === id || undefined}
                    style={{
                      height: `${virtualRow.size}px`,
                      transform: `translateY(${virtualRow.start}px)`,
                      gridTemplateColumns: `repeat(${columns.length}, minmax(0, 1fr))`,
                    }}
                  >
                    {columns.map((col) => (
                      <div
                        key={col.id}
                        className={cn(
                          "flex items-center truncate px-3 py-2",
                          col.className,
                        )}
                      >
                        {col.cell(row)}
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 border-b bg-muted/40 text-left text-xs text-muted-foreground backdrop-blur">
              <tr>
                {columns.map((col) => (
                  <th
                    key={col.id}
                    className={cn("px-3 py-2 font-medium", col.headerClassName)}
                  >
                    {col.sortable && onSortChange ? (
                      <button
                        type="button"
                        onClick={() => toggleSort(col.id)}
                        className="inline-flex items-center gap-1 hover:text-foreground"
                      >
                        {col.header}
                        {sort?.id === col.id ? (
                          <span aria-hidden>{sort.order === "asc" ? "↑" : "↓"}</span>
                        ) : null}
                      </button>
                    ) : (
                      col.header
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((row) => {
                const id = getRowId(row);
                return (
                  <tr
                    key={id}
                    className={cn(
                      "border-b last:border-0",
                      onRowClick && "cursor-pointer hover:bg-muted/30",
                      selectedId === id && "bg-muted/50",
                    )}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                  >
                    {columns.map((col) => (
                      <td key={col.id} className={cn("px-3 py-2", col.className)}>
                        {col.cell(row)}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
