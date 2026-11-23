"use client";

import { ListTree } from "lucide-react";

import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

import type { TocHeading } from "../lib/markdown-utils";

type DocTocProps = {
  headings: TocHeading[];
  activeId: string | null;
  onNavigate: (id: string) => void;
};

export function DocToc({ headings, activeId, onNavigate }: DocTocProps) {
  return (
    <aside
      className="hidden h-full min-h-0 flex-col border-l bg-card xl:flex"
      aria-label="On this page"
    >
      <div className="flex items-center gap-2 border-b px-3 py-3 text-sm font-medium">
        <ListTree className="size-4" aria-hidden />
        On this page
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <nav className="p-2 pb-8">
          {!headings.length ? (
            <p className="px-2 py-2 text-xs text-muted-foreground">No headings in this document.</p>
          ) : (
            <ul className="space-y-0.5">
              {headings.map((h) => (
                <li key={h.id}>
                  <button
                    type="button"
                    onClick={() => onNavigate(h.id)}
                    className={cn(
                      "w-full truncate rounded-md px-2 py-1.5 text-left text-xs hover:bg-muted/60",
                      activeId === h.id && "bg-accent font-medium text-accent-foreground",
                    )}
                    style={{ paddingLeft: `${0.5 + (h.level - 1) * 0.55}rem` }}
                    aria-current={activeId === h.id ? "location" : undefined}
                  >
                    {h.text}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </nav>
      </ScrollArea>
    </aside>
  );
}
