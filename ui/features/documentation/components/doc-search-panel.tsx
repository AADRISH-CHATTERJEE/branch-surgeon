"use client";

import { Search } from "lucide-react";

import { EmptyState } from "@/components/feedback/empty-state";
import { Button } from "@/components/ui/button";
import { SearchInput } from "@/components/search-input";
import { cn } from "@/lib/utils";

import { splitHighlight, type DocSearchHit } from "../lib/markdown-utils";

type DocSearchPanelProps = {
  open: boolean;
  query: string;
  onQueryChange: (v: string) => void;
  hits: DocSearchHit[];
  onSelect: (hit: DocSearchHit) => void;
  onClose: () => void;
};

export function DocSearchPanel({
  open,
  query,
  onQueryChange,
  hits,
  onSelect,
  onClose,
}: DocSearchPanelProps) {
  if (!open) return null;

  return (
    <div
      className="absolute inset-x-0 top-0 z-20 border-b bg-background/95 p-3 shadow-sm backdrop-blur"
      role="search"
      aria-label="Documentation search"
    >
      <div className="mx-auto flex max-w-2xl flex-col gap-2">
        <div className="flex items-center gap-2">
          <SearchInput
            id="doc-center-search"
            value={query}
            onChange={onQueryChange}
            placeholder="Search documents and headings…"
            className="flex-1"
          />
          <Button type="button" size="sm" variant="outline" onClick={onClose}>
            Esc
          </Button>
        </div>
        <p className="text-2xs text-muted-foreground">
          Tip: Ctrl/Cmd+K opens the global command palette with Documentation jumps.
        </p>
        <div className="max-h-64 overflow-auto rounded-md border">
          {!query.trim() ? (
            <p className="p-3 text-xs text-muted-foreground">Type to search titles, headings, and body text.</p>
          ) : !hits.length ? (
            <EmptyState
              className="py-8"
              icon={Search}
              title="No matches"
              description="Try a different term or clear filters."
            />
          ) : (
            <ul className="divide-y">
              {hits.map((hit, i) => (
                <li key={`${hit.docId}-${hit.headingId ?? "doc"}-${i}`}>
                  <button
                    type="button"
                    className="flex w-full flex-col gap-0.5 px-3 py-2 text-left text-sm hover:bg-muted/50"
                    onClick={() => onSelect(hit)}
                  >
                    <span className="font-medium">
                      {hit.kind === "heading" ? hit.headingText : hit.title}
                    </span>
                    <span className="text-2xs text-muted-foreground">
                      {hit.kind === "heading" ? `${hit.title} · heading` : "document"}
                    </span>
                    {hit.snippet ? (
                      <span className="text-xs text-muted-foreground">
                        {splitHighlight(hit.snippet, query).map((part, j) => (
                          <span
                            key={j}
                            className={cn(part.match && "rounded bg-primary/20 text-foreground")}
                          >
                            {part.text}
                          </span>
                        ))}
                      </span>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
