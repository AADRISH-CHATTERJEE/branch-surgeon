"use client";

import {
  ArrowUp,
  ChevronDown,
  ChevronUp,
  ClipboardCopy,
  Link2,
  Printer,
  Star,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

type DocToolbarProps = {
  title: string;
  docId: string;
  favorited: boolean;
  words: number;
  minutes: number;
  hasContent: boolean;
  rawMarkdown: string;
  onToggleFavorite: () => void;
  onExpandNav: () => void;
  onCollapseNav: () => void;
};

async function copyText(text: string, ok: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(ok);
  } catch {
    toast.error("Could not copy to clipboard");
  }
}

export function DocToolbar({
  title,
  docId,
  favorited,
  words,
  minutes,
  hasContent,
  rawMarkdown,
  onToggleFavorite,
  onExpandNav,
  onCollapseNav,
}: DocToolbarProps) {
  const copyPageLink = () => {
    const url = new URL(window.location.href);
    url.searchParams.set("doc", docId);
    url.hash = "";
    void copyText(url.toString(), "Link copied");
  };

  const copySectionLink = () => {
    const hash = window.location.hash.replace(/^#/, "");
    const url = new URL(window.location.href);
    url.searchParams.set("doc", docId);
    if (hash) url.hash = hash;
    void copyText(url.toString(), hash ? "Section link copied" : "Page link copied (no section active)");
  };

  const openRaw = () => {
    if (!hasContent) {
      toast.message("No Markdown available for this entry");
      return;
    }
    const blob = new Blob([rawMarkdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank", "noopener,noreferrer");
    window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
  };

  const copyMarkdown = () => {
    if (!hasContent) {
      toast.message("No Markdown available for this entry");
      return;
    }
    void copyText(rawMarkdown, "Markdown copied");
  };

  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-background/95 px-3 py-2 backdrop-blur supports-backdrop-filter:bg-background/80">
        <div className="min-w-0">
          <h1 className="truncate text-base font-semibold">{title}</h1>
          <p className="text-2xs text-muted-foreground">
            {hasContent ? (
              <>
                {words.toLocaleString()} words · ~{minutes} min read
                <span className="mx-1.5 opacity-50">·</span>
                From GET /documentation
              </>
            ) : (
              "Content unavailable from Local API"
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1">
          <Action tip="Favorite" onClick={onToggleFavorite}>
            <Star className={favorited ? "size-3.5 fill-primary text-primary" : "size-3.5"} />
          </Action>
          <Action tip="Copy Link" onClick={copyPageLink}>
            <Link2 className="size-3.5" />
          </Action>
          <Action tip="Copy section link" onClick={copySectionLink}>
            <Link2 className="size-3.5 opacity-70" />
          </Action>
          <Action tip="Copy Markdown" onClick={copyMarkdown}>
            <ClipboardCopy className="size-3.5" />
          </Action>
          <Action tip="Expand all categories" onClick={onExpandNav}>
            <ChevronDown className="size-3.5" />
          </Action>
          <Action tip="Collapse all categories" onClick={onCollapseNav}>
            <ChevronUp className="size-3.5" />
          </Action>
          <Action tip="Print" onClick={() => window.print()}>
            <Printer className="size-3.5" />
          </Action>
          <Action tip="Open raw Markdown" onClick={openRaw}>
            <span className="text-2xs font-medium">MD</span>
          </Action>
          <Action
            tip="Back to top"
            onClick={() => {
              document
                .getElementById("doc-reader-scroll")
                ?.scrollTo({ top: 0, behavior: "smooth" });
            }}
          >
            <ArrowUp className="size-3.5" />
          </Action>
        </div>
      </div>
    </TooltipProvider>
  );
}

function Action({
  tip,
  onClick,
  children,
}: {
  tip: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-8 px-2"
          onClick={onClick}
          aria-label={tip}
        >
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{tip}</TooltipContent>
    </Tooltip>
  );
}
