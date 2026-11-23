"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Menu, PanelLeft, Search } from "lucide-react";

import { MetricStrip } from "@/components/data-display/metric-strip";
import { EmptyState } from "@/components/feedback/empty-state";
import { ErrorState } from "@/components/feedback/error-state";
import { ListSkeleton } from "@/components/feedback/loading-skeletons";
import { Unavailable } from "@/components/feedback/unavailable";
import { PageContainer } from "@/components/layout/page-container";
import { MarkdownViewer } from "@/components/markdown-viewer";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useDocumentation } from "@/queries/use-documentation";
import { ApiError } from "@/services/errors";
import { cn } from "@/lib/utils";

import { DocNav } from "./components/doc-nav";
import { DocRelated } from "./components/doc-related";
import { DocSearchPanel } from "./components/doc-search-panel";
import { DocToc } from "./components/doc-toc";
import { DocToolbar } from "./components/doc-toolbar";
import {
  DOC_CATALOG,
  DOC_CATEGORIES,
  countLoadedDocs,
  firstAvailableDocId,
  getDocEntry,
  resolveDocContent,
} from "./lib/doc-catalog";
import {
  extractHeadings,
  readingTimeMinutes,
  searchDocumentation,
  wordCount,
} from "./lib/markdown-utils";
import {
  getCollapsedCategories,
  getFavoriteDocIds,
  getLastOpenedDocId,
  getRecentDocIds,
  pushRecentDocId,
  setCollapsedCategories,
  setLastOpenedDocId,
  toggleFavoriteDocId,
} from "./lib/doc-storage";

export function DocumentationView() {
  const docs = useDocumentation();
  const params = useSearchParams();
  const router = useRouter();

  const [favorites, setFavorites] = React.useState<string[]>(() => getFavoriteDocIds());
  const [recent, setRecent] = React.useState<string[]>(() => getRecentDocIds());
  const [collapsed, setCollapsed] = React.useState<string[]>(() => getCollapsedCategories());
  const [navFilter, setNavFilter] = React.useState("");
  const [searchOpen, setSearchOpen] = React.useState(false);
  const [searchQuery, setSearchQuery] = React.useState("");
  const [mobileNavOpen, setMobileNavOpen] = React.useState(false);
  const [activeHeading, setActiveHeading] = React.useState<string | null>(null);
  const [progress, setProgress] = React.useState(0);
  const readerRef = React.useRef<HTMLDivElement>(null);

  const data = docs.data;
  const loadedCount = countLoadedDocs(data);
  const allEmpty = loadedCount === 0;

  const paramDoc = params.get("doc");
  const activeId = React.useMemo(() => {
    if (paramDoc && getDocEntry(paramDoc)) return paramDoc;
    const lastOpened = getLastOpenedDocId();
    if (lastOpened && getDocEntry(lastOpened)) return lastOpened;
    if (data) return firstAvailableDocId(data);
    return "architecture";
  }, [paramDoc, data]);

  const entry = getDocEntry(activeId) ?? DOC_CATALOG[0];
  const content = resolveDocContent(entry, data);
  const hasContent = Boolean(content.trim());
  const headings = extractHeadings(content);
  const words = wordCount(content);
  const minutes = readingTimeMinutes(words);

  const loadedIds = React.useMemo(() => {
    const set = new Set<string>();
    if (!data) return set;
    for (const d of DOC_CATALOG) {
      if (d.apiKey && data[d.apiKey]?.trim()) set.add(d.id);
    }
    return set;
  }, [data]);

  /** Search corpus for title / heading / body filtering (built when the user searches). */
  const searchableDocs = React.useMemo(() => {
    if (!data || (!searchOpen && !searchQuery.trim())) return [];
    return DOC_CATALOG.filter((d) => d.apiKey).map((d) => ({
      id: d.id,
      title: d.title,
      content: resolveDocContent(d, data),
    }));
  }, [data, searchOpen, searchQuery]);

  const searchHits = React.useMemo(
    () =>
      searchQuery.trim() ? searchDocumentation(searchableDocs, searchQuery) : [],
    [searchableDocs, searchQuery],
  );

  const matchedDocIds = React.useMemo(() => {
    if (!searchQuery.trim()) return null;
    return new Set(searchHits.map((h) => h.docId));
  }, [searchHits, searchQuery]);

  const selectDoc = React.useCallback(
    (id: string, headingId?: string) => {
      const next = new URLSearchParams(params.toString());
      next.set("doc", id);
      const qs = next.toString();
      // Build the target URL once — do NOT read window.location in rAF below.
      // A prior replaceState(pathname + search) raced router.replace and wiped ?doc=.
      const path = qs ? `/documentation?${qs}` : "/documentation";
      router.replace(path, { scroll: false });
      setLastOpenedDocId(id);
      setRecent(pushRecentDocId(id));
      setMobileNavOpen(false);
      setSearchOpen(false);
      setSearchQuery("");
      window.requestAnimationFrame(() => {
        const scroller = readerRef.current;
        if (headingId) {
          const el = document.getElementById(headingId);
          if (el) {
            el.scrollIntoView({ behavior: "smooth", block: "start" });
            history.replaceState(null, "", `${path}#${headingId}`);
            return;
          }
        }
        scroller?.scrollTo({ top: 0 });
        // Clear hash only; keep the doc query we just navigated to.
        history.replaceState(null, "", path);
      });
    },
    [params, router],
  );

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && !e.metaKey && !e.ctrlKey && !e.altKey) {
        const t = e.target as HTMLElement | null;
        const tag = t?.tagName?.toLowerCase();
        if (tag === "input" || tag === "textarea" || t?.isContentEditable) return;
        e.preventDefault();
        setSearchOpen(true);
      }
      if (e.key === "Escape") setSearchOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const headingIds = headings.map((h) => h.id).join("|");

  React.useEffect(() => {
    const el = readerRef.current;
    if (!el) return;

    const ids = headingIds ? headingIds.split("|") : [];

    const onScroll = () => {
      const max = el.scrollHeight - el.clientHeight;
      setProgress(max > 0 ? Math.min(100, (el.scrollTop / max) * 100) : 0);

      const nodes = ids
        .map((id) => document.getElementById(id))
        .filter((n): n is HTMLElement => Boolean(n));
      if (!nodes.length) {
        setActiveHeading(null);
        return;
      }
      const top = el.getBoundingClientRect().top + 96;
      let current = nodes[0].id;
      for (const node of nodes) {
        if (node.getBoundingClientRect().top <= top) current = node.id;
      }
      setActiveHeading(current);
    };

    onScroll();
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [headingIds, content]);

  React.useEffect(() => {
    if (!hasContent) return;
    const hash = typeof window !== "undefined" ? window.location.hash.replace(/^#/, "") : "";
    if (!hash) return;
    const timer = window.setTimeout(() => {
      document.getElementById(hash)?.scrollIntoView({ behavior: "smooth", block: "start" });
      setActiveHeading(hash);
    }, 80);
    return () => window.clearTimeout(timer);
  }, [content, hasContent]);

  const toggleFavorite = (id: string) => setFavorites(toggleFavoriteDocId(id));

  const toggleCategory = (category: string) => {
    const next = collapsed.includes(category)
      ? collapsed.filter((c) => c !== category)
      : [...collapsed, category];
    setCollapsed(next);
    setCollapsedCategories(next);
  };

  const expandAll = () => {
    setCollapsed([]);
    setCollapsedCategories([]);
  };
  const collapseAll = () => {
    const all = [...DOC_CATEGORIES];
    setCollapsed(all);
    setCollapsedCategories(all);
  };

  if (docs.isLoading) {
    return (
      <PageContainer variant="wide" className="space-y-4">
        <PageHeader
          title="Documentation"
          description="Engineering knowledge center from GET /documentation."
        />
        <div className="grid min-h-[28rem] grid-cols-1 overflow-hidden rounded-lg border lg:grid-cols-[16rem_1fr_14rem]">
          <ListSkeleton rows={8} />
          <div className="border-x p-4">
            <ListSkeleton rows={10} />
          </div>
          <ListSkeleton rows={6} />
        </div>
      </PageContainer>
    );
  }

  if (docs.isError) {
    return (
      <PageContainer className="space-y-6">
        <PageHeader
          title="Documentation"
          description="Engineering knowledge center from GET /documentation."
        />
        <ErrorState
          title="Could not load documentation"
          description={docs.error instanceof ApiError ? docs.error.message : undefined}
          onRetry={() => void docs.refetch()}
        />
      </PageContainer>
    );
  }

  if (allEmpty) {
    return (
      <PageContainer className="space-y-6">
        <PageHeader
          title="Documentation"
          description="Engineering knowledge center from GET /documentation."
        />
        <EmptyState
          title="No documentation found for this repository."
          description="Default documentation is created automatically when missing. If you still see this, check that .refactory/ is writable for the linked repository."
        />
      </PageContainer>
    );
  }

  const navProps = {
    activeId: entry.id,
    loadedIds,
    favorites,
    recent,
    collapsed,
    filter: navFilter,
    onFilterChange: setNavFilter,
    onSelect: (id: string) => selectDoc(id),
    onToggleFavorite: toggleFavorite,
    onToggleCategory: toggleCategory,
    onExpandAll: expandAll,
    onCollapseAll: collapseAll,
    // When searching, hide docs that do not match title/headings/body.
    visibleIds: matchedDocIds,
  };

  return (
    <PageContainer variant="wide" className="space-y-4 print:max-w-none">
      <PageHeader
        title="Documentation"
        description="Engineering knowledge center — company Markdown from GET /documentation."
        actions={
          <div className="flex w-full max-w-md flex-wrap items-center gap-2 sm:w-auto">
            <Button
              size="sm"
              variant="outline"
              className="lg:hidden"
              onClick={() => setMobileNavOpen(true)}
            >
              <Menu className="size-4" />
              Docs
            </Button>
            <div className="relative min-w-[12rem] flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <input
                type="search"
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setSearchOpen(true);
                }}
                onFocus={() => setSearchOpen(true)}
                placeholder="Search docs…"
                aria-label="Search documentation"
                className="h-8 w-full rounded-md border bg-background pl-8 pr-2 text-sm outline-none ring-offset-background placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
              />
            </div>
            <kbd className="hidden rounded border px-1.5 text-2xs text-muted-foreground sm:inline">
              /
            </kbd>
          </div>
        }
      />

      <MetricStrip
        items={[
          { key: "loaded", label: "Loaded docs", value: `${loadedCount}/4`, hint: "API Markdown blobs" },
          { key: "catalog", label: "Catalog entries", value: DOC_CATALOG.length, hint: "Includes soft gaps" },
          { key: "words", label: "Active words", value: hasContent ? words : "—", hint: entry.title },
          { key: "read", label: "Read time", value: hasContent ? `~${minutes}m` : "—", hint: "~200 wpm" },
        ]}
      />

      <div className="relative overflow-hidden rounded-lg border bg-card">
        {/* Reading progress */}
        <div
          className="pointer-events-none absolute inset-x-0 top-0 z-30 h-0.5 bg-muted"
          aria-hidden
        >
          <div
            className="h-full bg-primary transition-[width] duration-150"
            style={{ width: `${progress}%` }}
          />
        </div>

        <DocSearchPanel
          open={searchOpen}
          query={searchQuery}
          onQueryChange={(v) => {
            setSearchQuery(v);
            setSearchOpen(true);
          }}
          hits={searchHits}
          onClose={() => {
            setSearchOpen(false);
            setSearchQuery("");
          }}
          onSelect={(hit) => selectDoc(hit.docId, hit.headingId)}
        />

        <div className="grid min-h-[min(70vh,52rem)] grid-cols-1 lg:grid-cols-[16rem_minmax(0,1fr)] xl:grid-cols-[16rem_minmax(0,1fr)_14rem]">
          <div className="hidden min-h-0 lg:block">
            <DocNav {...navProps} />
          </div>

          <div className="flex min-h-0 min-w-0 flex-col">
            <DocToolbar
              title={entry.title}
              docId={entry.id}
              favorited={favorites.includes(entry.id)}
              words={words}
              minutes={minutes}
              hasContent={hasContent}
              rawMarkdown={content}
              onToggleFavorite={() => toggleFavorite(entry.id)}
              onExpandNav={expandAll}
              onCollapseNav={collapseAll}
            />

            <div
              id="doc-reader-scroll"
              ref={readerRef}
              className={cn(
                "min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6",
                "print:overflow-visible",
              )}
              tabIndex={0}
              aria-label={`${entry.title} document`}
            >
              {entry.unavailableReason ? (
                <Unavailable
                  title={`${entry.title} unavailable`}
                  reason={entry.unavailableReason}
                  description={entry.description}
                />
              ) : !hasContent ? (
                <EmptyState
                  className="py-12"
                  title="This document is empty"
                  description={`${entry.title} has no Markdown from GET /documentation yet. Add the matching .refactory/*.md file.`}
                />
              ) : (
                <>
                  <MarkdownViewer
                    key={entry.id}
                    active={hasContent && !entry.unavailableReason}
                    content={content}
                    searchQuery={searchQuery.trim() ? searchQuery : undefined}
                  />
                  <DocRelated entry={entry} onSelectDoc={(id) => selectDoc(id)} />
                </>
              )}
            </div>
          </div>

          <DocToc
            headings={headings}
            activeId={activeHeading}
            onNavigate={(id) => {
              const el = document.getElementById(id);
              if (el) {
                el.scrollIntoView({ behavior: "smooth", block: "start" });
                history.replaceState(null, "", `#${id}`);
                setActiveHeading(id);
              }
            }}
          />
        </div>
      </div>

      <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
        <SheetContent side="left" className="w-[min(100%,20rem)] p-0">
          <SheetHeader className="sr-only">
            <SheetTitle>Documentation navigation</SheetTitle>
          </SheetHeader>
          <div className="flex items-center gap-2 border-b px-3 py-3 text-sm font-medium lg:hidden">
            <PanelLeft className="size-4" />
            Browse docs
          </div>
          <div className="h-[calc(100%-3rem)]">
            <DocNav {...navProps} />
          </div>
        </SheetContent>
      </Sheet>
    </PageContainer>
  );
}
