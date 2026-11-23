import Link from "next/link";

import { cn } from "@/lib/utils";

export type RankedListItem = {
  id: string;
  label: string;
  value: string | number;
  meta?: string;
  href?: string;
};

type RankedListProps = {
  title?: string;
  items: RankedListItem[];
  empty?: string;
  onSelect?: (id: string) => void;
  className?: string;
  maxHeightClassName?: string;
};

export function RankedList({
  title,
  items,
  empty = "No items",
  onSelect,
  className,
  maxHeightClassName = "max-h-40",
}: RankedListProps) {
  return (
    <div className={cn("space-y-1.5", className)}>
      {title ? (
        <h4 className="text-2xs font-medium tracking-wide text-muted-foreground uppercase">
          {title}
        </h4>
      ) : null}
      {!items.length ? (
        <p className="text-xs text-muted-foreground">{empty}</p>
      ) : (
        <ul className={cn("space-y-0.5 overflow-auto", maxHeightClassName)}>
          {items.map((item) => {
            const classNameRow = cn(
              "flex w-full items-center justify-between gap-2 rounded-md px-1.5 py-1 text-left text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              (onSelect || item.href) && "hover:bg-muted/60",
            );
            const body = (
              <>
                <span className="min-w-0">
                  <span className="block truncate font-mono">{item.label}</span>
                  {item.meta ? (
                    <span className="text-2xs text-muted-foreground">{item.meta}</span>
                  ) : null}
                </span>
                <span className="shrink-0 tabular-nums text-muted-foreground">
                  {item.value}
                </span>
              </>
            );
            return (
              <li key={item.id}>
                {item.href ? (
                  <Link href={item.href} className={classNameRow}>
                    {body}
                  </Link>
                ) : onSelect ? (
                  <button type="button" onClick={() => onSelect(item.id)} className={classNameRow}>
                    {body}
                  </button>
                ) : (
                  <div className={classNameRow}>{body}</div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
