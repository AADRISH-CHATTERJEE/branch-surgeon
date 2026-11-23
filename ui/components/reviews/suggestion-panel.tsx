"use client";

import {
  LifecycleBadge,
  LifecycleLegend,
} from "@/components/data-display/lifecycle-badge";
import { StatusBadge } from "@/components/data-display/status-badge";
import { EmptyState } from "@/components/feedback/empty-state";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { ReviewSuggestion, ReviewSuggestionStatus } from "@/types/domain";
import { Check, Copy, FileSearch, Loader2, Ban } from "lucide-react";
import { toast } from "sonner";

type SuggestionPanelProps = {
  suggestions: ReviewSuggestion[];
  selectedFile?: string | null;
  onViewFile?: (file: string) => void;
  /** Focus suggestion file in the review workspace (diff content needs backend). */
  onFocusFile?: (file: string, line?: number) => void;
  onUpdateStatus?: (
    suggestionId: string,
    status: Exclude<ReviewSuggestionStatus, "pending">,
  ) => void;
  updatingSuggestionId?: string | null;
  className?: string;
};

export function SuggestionPanel({
  suggestions,
  selectedFile,
  onViewFile,
  onFocusFile,
  onUpdateStatus,
  updatingSuggestionId = null,
  className,
}: SuggestionPanelProps) {
  const filtered = selectedFile
    ? suggestions.filter((s) => s.file === selectedFile)
    : suggestions;

  if (!filtered.length) {
    return (
      <EmptyState
        className={cn("min-w-0 overflow-hidden rounded-lg border", className)}
        title={selectedFile ? "No findings" : "No suggestions"}
        description={
          selectedFile
            ? "No issues detected for this file."
            : suggestions.length === 0
              ? "No AI suggestions generated."
              : "No findings match the current filter."
        }
      />
    );
  }

  return (
    <div
      className={cn(
        "flex min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border bg-card",
        className,
      )}
    >
      <div className="shrink-0 space-y-2 border-b bg-muted/40 px-3 py-2">
        <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-sm font-semibold">Suggestions ({filtered.length})</h3>
          {selectedFile ? (
            <p className="min-w-0 truncate font-mono text-xs text-muted-foreground">
              {selectedFile}
            </p>
          ) : null}
        </div>
        <LifecycleLegend compact className="rounded-md border bg-background/60 p-2" />
      </div>

      <ScrollArea className="min-h-0 min-w-0 flex-1">
        <ul className="space-y-3 p-3">
          {filtered.map((suggestion) => {
            const status = (suggestion.status || "pending").toLowerCase();
            const busy = updatingSuggestionId === suggestion.id;
            const actionable = status === "pending" && Boolean(onUpdateStatus);

            return (
              <li
                key={suggestion.id}
                className="min-w-0 overflow-hidden rounded-lg border bg-background p-3 text-sm shadow-sm transition-colors hover:border-foreground/15"
              >
                <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                  <StatusBadge label={suggestion.severity || "info"} />
                  {suggestion.category ? (
                    <StatusBadge label={suggestion.category} tone="info" />
                  ) : null}
                  <LifecycleBadge status={status} />
                  {suggestion.confidence != null ? (
                    <StatusBadge
                      label={`${(suggestion.confidence * 100).toFixed(0)}%`}
                      tone="muted"
                    />
                  ) : null}
                </div>

                <h4 className="mt-2 wrap-break-word font-semibold leading-snug">
                  {suggestion.title}
                </h4>

                <p className="mt-1 wrap-break-word font-mono text-xs text-muted-foreground">
                  {suggestion.file}
                  {suggestion.line != null ? `:${suggestion.line}` : ""}
                </p>

                {suggestion.explanation ? (
                  <p className="mt-2 wrap-break-word whitespace-pre-wrap text-muted-foreground">
                    {suggestion.explanation}
                  </p>
                ) : null}

                {suggestion.suggested_fix ? (
                  <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-muted p-2 font-mono text-xs wrap-break-word whitespace-pre-wrap">
                    {suggestion.suggested_fix}
                  </pre>
                ) : null}

                {suggestion.estimated_impact ? (
                  <p className="mt-2 wrap-break-word text-xs text-muted-foreground">
                    <strong>Impact:</strong> {suggestion.estimated_impact}
                  </p>
                ) : null}

                <div className="mt-3 flex min-w-0 flex-col gap-2 border-t pt-3">
                  <div className="flex flex-wrap gap-2">
                    <TooltipProvider>
                      {onViewFile ? (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              size="sm"
                              variant="outline"
                              aria-label={`View ${suggestion.file} in repository explorer`}
                              onClick={() => onViewFile(suggestion.file)}
                            >
                              <FileSearch className="size-3" aria-hidden />
                              View File
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>Open in Repository Explorer</TooltipContent>
                        </Tooltip>
                      ) : null}

                      {onFocusFile ? (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              size="sm"
                              variant="outline"
                              aria-label={`Focus ${suggestion.file} in review workspace`}
                              onClick={() =>
                                onFocusFile(
                                  suggestion.file,
                                  suggestion.line ?? undefined,
                                )
                              }
                            >
                              Focus file
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>
                            Select file in workspace (full diff requires backend)
                          </TooltipContent>
                        </Tooltip>
                      ) : null}

                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            size="sm"
                            variant="ghost"
                            aria-label="Copy suggestion JSON"
                            onClick={() => {
                              void navigator.clipboard.writeText(
                                JSON.stringify(suggestion, null, 2),
                              );
                              toast.success("Copied suggestion to clipboard");
                            }}
                          >
                            <Copy className="size-3" aria-hidden />
                            Copy
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>Copy suggestion JSON</TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>

                  {actionable ? (
                    <div className="flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        aria-label="Ignore suggestion"
                        data-testid="ignore-suggestion"
                        onClick={() => onUpdateStatus?.(suggestion.id, "ignored")}
                      >
                        {busy ? (
                          <Loader2 className="size-3 animate-spin" aria-hidden />
                        ) : (
                          <Ban className="size-3" aria-hidden />
                        )}
                        Ignore
                      </Button>
                      <Button
                        size="sm"
                        disabled={busy}
                        aria-label="Mark suggestion resolved"
                        data-testid="resolve-suggestion"
                        onClick={() => onUpdateStatus?.(suggestion.id, "resolved")}
                      >
                        {busy ? (
                          <Loader2 className="size-3 animate-spin" aria-hidden />
                        ) : (
                          <Check className="size-3" aria-hidden />
                        )}
                        Mark Resolved
                      </Button>
                    </div>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      </ScrollArea>
    </div>
  );
}
