"use client";

import {
  BookOpen,
  ChevronDown,
  ChevronRight,
  FileText,
  Star,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { SearchInput } from "@/components/search-input";
import { cn } from "@/lib/utils";

import {
  DOC_CATALOG,
  DOC_CATEGORIES,
  type DocEntry,
} from "../lib/doc-catalog";

type DocNavProps = {
  activeId: string;
  loadedIds: Set<string>;
  favorites: string[];
  recent: string[];
  collapsed: string[];
  filter: string;
  onFilterChange: (v: string) => void;
  onSelect: (id: string) => void;
  onToggleFavorite: (id: string) => void;
  onToggleCategory: (category: string) => void;
  onExpandAll: () => void;
  onCollapseAll: () => void;
  /** When set, only these catalog ids are shown (documentation search filter). */
  visibleIds?: Set<string> | null;
};

function DocLink({
  entry,
  active,
  loaded,
  favorited,
  onSelect,
  onToggleFavorite,
}: {
  entry: DocEntry;
  active: boolean;
  loaded: boolean;
  favorited: boolean;
  onSelect: () => void;
  onToggleFavorite: () => void;
}) {
  return (
    <div
      className={cn(
        "group flex items-center gap-0.5 rounded-md",
        active && "bg-accent text-accent-foreground",
      )}
    >
      <button
        type="button"
        onClick={onSelect}
        className={cn(
          "flex min-w-0 flex-1 items-center gap-2 px-2 py-1.5 text-left text-sm",
          !active && "hover:bg-muted/60",
          !loaded && entry.apiKey && "opacity-60",
          entry.unavailableReason && "opacity-70",
        )}
        aria-current={active ? "page" : undefined}
      >
        <FileText className="size-3.5 shrink-0 opacity-70" aria-hidden />
        <span className="truncate">{entry.title}</span>
        {!loaded && entry.apiKey ? (
          <span className="ml-auto text-2xs text-muted-foreground">Empty</span>
        ) : null}
        {entry.unavailableReason ? (
          <span className="ml-auto text-2xs text-muted-foreground">N/A</span>
        ) : null}
      </button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className="size-7 shrink-0 p-0 opacity-0 group-hover:opacity-100 focus:opacity-100"
        onClick={onToggleFavorite}
        aria-label={favorited ? "Remove favorite" : "Add favorite"}
      >
        <Star
          className={cn("size-3.5", favorited && "fill-primary text-primary opacity-100")}
        />
      </Button>
    </div>
  );
}

export function DocNav({
  activeId,
  loadedIds,
  favorites,
  recent,
  collapsed,
  filter,
  onFilterChange,
  onSelect,
  onToggleFavorite,
  onToggleCategory,
  onExpandAll,
  onCollapseAll,
  visibleIds = null,
}: DocNavProps) {
  const q = filter.trim().toLowerCase();

  const matches = (entry: DocEntry) => {
    if (visibleIds && !visibleIds.has(entry.id)) return false;
    return (
      !q ||
      entry.title.toLowerCase().includes(q) ||
      entry.category.toLowerCase().includes(q) ||
      entry.description.toLowerCase().includes(q)
    );
  };

  const favoriteEntries = DOC_CATALOG.filter(
    (d) => favorites.includes(d.id) && matches(d),
  );
  const recentEntries = recent
    .map((id) => DOC_CATALOG.find((d) => d.id === id))
    .filter((d): d is DocEntry => Boolean(d && matches(d)));

  return (
    <nav
      className="flex h-full min-h-0 flex-col border-r bg-card"
      aria-label="Documentation navigation"
    >
      <div className="space-y-2 border-b p-3">
        <div className="flex items-center gap-2 text-sm font-medium">
          <BookOpen className="size-4" aria-hidden />
          Documents
        </div>
        <SearchInput
          value={filter}
          onChange={onFilterChange}
          placeholder="Filter docs…"
          id="doc-nav-filter"
        />
        <div className="flex gap-1">
          <Button type="button" size="sm" variant="ghost" className="h-7 text-xs" onClick={onExpandAll}>
            Expand all
          </Button>
          <Button type="button" size="sm" variant="ghost" className="h-7 text-xs" onClick={onCollapseAll}>
            Collapse all
          </Button>
        </div>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-4 p-2 pb-6">
          {favoriteEntries.length ? (
            <section>
              <h3 className="mb-1 px-2 text-2xs font-medium tracking-wide text-muted-foreground uppercase">
                Favorites
              </h3>
              <ul className="space-y-0.5">
                {favoriteEntries.map((entry) => (
                  <li key={`fav-${entry.id}`}>
                    <DocLink
                      entry={entry}
                      active={activeId === entry.id}
                      loaded={Boolean(entry.apiKey && loadedIds.has(entry.id))}
                      favorited
                      onSelect={() => onSelect(entry.id)}
                      onToggleFavorite={() => onToggleFavorite(entry.id)}
                    />
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {recentEntries.length ? (
            <section>
              <h3 className="mb-1 px-2 text-2xs font-medium tracking-wide text-muted-foreground uppercase">
                Recent
              </h3>
              <ul className="space-y-0.5">
                {recentEntries.map((entry) => (
                  <li key={`recent-${entry.id}`}>
                    <DocLink
                      entry={entry}
                      active={activeId === entry.id}
                      loaded={Boolean(entry.apiKey && loadedIds.has(entry.id))}
                      favorited={favorites.includes(entry.id)}
                      onSelect={() => onSelect(entry.id)}
                      onToggleFavorite={() => onToggleFavorite(entry.id)}
                    />
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {DOC_CATEGORIES.map((category) => {
            const entries = DOC_CATALOG.filter((d) => d.category === category && matches(d));
            if (!entries.length) return null;
            const isCollapsed = collapsed.includes(category);
            return (
              <section key={category}>
                <button
                  type="button"
                  className="mb-1 flex w-full items-center gap-1 px-2 text-2xs font-medium tracking-wide text-muted-foreground uppercase hover:text-foreground"
                  onClick={() => onToggleCategory(category)}
                  aria-expanded={!isCollapsed}
                >
                  {isCollapsed ? (
                    <ChevronRight className="size-3" />
                  ) : (
                    <ChevronDown className="size-3" />
                  )}
                  {category}
                </button>
                {!isCollapsed ? (
                  <ul className="space-y-0.5">
                    {entries.map((entry) => (
                      <li key={entry.id}>
                        <DocLink
                          entry={entry}
                          active={activeId === entry.id}
                          loaded={Boolean(entry.apiKey && loadedIds.has(entry.id))}
                          favorited={favorites.includes(entry.id)}
                          onSelect={() => onSelect(entry.id)}
                          onToggleFavorite={() => onToggleFavorite(entry.id)}
                        />
                      </li>
                    ))}
                  </ul>
                ) : null}
              </section>
            );
          })}

          {(q || visibleIds) && !DOC_CATALOG.some(matches) ? (
            <p className="px-2 text-xs text-muted-foreground">No documents match.</p>
          ) : null}
        </div>
      </ScrollArea>
    </nav>
  );
}
