"use client";

import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { ArrowLeft, FileCode, LayoutGrid, List } from "lucide-react";

import { DataTable, type DataTableSort } from "@/components/data-display/data-table";
import { ReviewMetrics } from "@/components/data-display/review-metrics";
import { RiskSummary } from "@/components/data-display/risk-summary";
import { StatusBadge } from "@/components/data-display/status-badge";
import { EmptyState } from "@/components/feedback/empty-state";
import { ErrorState } from "@/components/feedback/error-state";
import { ListSkeleton, MetricSkeleton } from "@/components/feedback/loading-skeletons";
import { Unavailable } from "@/components/feedback/unavailable";
import { PageContainer } from "@/components/layout/page-container";
import { MarkdownViewer } from "@/components/markdown-viewer";
import { PageHeader } from "@/components/page-header";
import { ReviewCard } from "@/components/reviews/review-card";
import { FileExplorer } from "@/components/reviews/file-explorer";
import { SuggestionPanel } from "@/components/reviews/suggestion-panel";
import { RunReviewDialog } from "@/components/shared/run-review-dialog";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { STORAGE_KEYS } from "@/lib/constants";
import { formatRelativeTime } from "@/lib/format";
import {
  reviewCriticalCount,
  reviewFileCount,
  reviewOverallScore,
  reviewSuggestionCount,
  reviewWarningCount,
} from "@/lib/review-metrics";
import { useListFilters } from "@/hooks/use-list-filters";
import {
  useReview,
  useReviews,
  useUpdateReviewSuggestionStatus,
} from "@/queries/use-reviews";
import { ApiError } from "@/services/errors";
import type { PersistedReview } from "@/types/domain";

type ViewMode = "table" | "cards";

export function ReviewsView() {
  const params = useSearchParams();
  const router = useRouter();
  const list = useReviews(100);
  const selectedId = params.get("id");
  const detail = useReview(selectedId);
  const updateSuggestion = useUpdateReviewSuggestionStatus();
  const [open, setOpen] = React.useState(false);
  const [sort, setSort] = React.useState<DataTableSort>({ id: "date", order: "desc" });
  const [userSelectedFile, setUserSelectedFile] = React.useState<string | null>(null);
  const { filters, setExtra } = useListFilters({
    storageKey: STORAGE_KEYS.reviewsView,
    storageField: "view",
    defaults: { extra: { view: "table" } },
  });
  const viewMode = (filters.extra.view as ViewMode) || "table";

  const listPreview = React.useMemo(
    () =>
      selectedId
        ? (list.data ?? []).find(
            (r) => r.id === selectedId || String(r.pr_number) === selectedId,
          )
        : undefined,
    [list.data, selectedId],
  );

  const suggestions = detail.data?.suggestions;
  const changedFiles = React.useMemo(() => {
    if (!suggestions) return [];
    const fileMap = new Map<string, number>();
    suggestions.forEach((s) => {
      if (s.file) fileMap.set(s.file, (fileMap.get(s.file) ?? 0) + 1);
    });
    return Array.from(fileMap.entries()).map(([path, count]) => ({
      path,
      suggestionCount: count,
    }));
  }, [suggestions]);

  // Derive selection: prefer user pick when still valid; else first changed file.
  const selectedFile = React.useMemo(() => {
    if (!selectedId || !detail.data || changedFiles.length === 0) return null;
    if (userSelectedFile && changedFiles.some((f) => f.path === userSelectedFile)) {
      return userSelectedFile;
    }
    return changedFiles[0]?.path ?? null;
  }, [selectedId, detail.data, changedFiles, userSelectedFile]);

  const selectReview = (id: string) => {
    router.replace(`/reviews?id=${id}`);
    setUserSelectedFile(null);
  };

  const backToList = () => {
    router.replace("/reviews");
    setUserSelectedFile(null);
  };

  const setView = (mode: ViewMode) => {
    setExtra("view", mode);
  };

  const activeReview: PersistedReview | undefined = detail.data ?? listPreview;

  const riskScores = React.useMemo(() => {
    if (!activeReview) return {};
    // Only overall is produced from persisted risk — hide empty category cards.
    return {
      overall: reviewOverallScore(activeReview.risk),
    };
  }, [activeReview]);

  const columns = React.useMemo(
    () => [
      {
        id: "date",
        header: "Review",
        sortable: true,
        sortValue: (r: PersistedReview) => new Date(r.created_at ?? 0).getTime(),
        cell: (r: PersistedReview) => (
          <span className="font-medium">
            {r.pr_number != null ? `PR #${r.pr_number}` : r.id.slice(0, 8)}
          </span>
        ),
      },
      {
        id: "risk",
        header: "Risk",
        sortable: true,
        sortValue: (r: PersistedReview) => {
          const order: Record<string, number> = {
            critical: 3,
            high: 2,
            medium: 1,
            low: 0,
          };
          return order[r.risk] ?? -1;
        },
        cell: (r: PersistedReview) => <StatusBadge label={r.risk || "unknown"} />,
      },
      {
        id: "suggestions",
        header: "Suggestions",
        sortable: true,
        sortValue: (r: PersistedReview) => reviewSuggestionCount(r),
        className: "tabular-nums",
        cell: (r: PersistedReview) => reviewSuggestionCount(r),
      },
      {
        id: "summary",
        header: "Summary",
        className: "max-w-md",
        cell: (r: PersistedReview) => (
          <p className="line-clamp-2 text-muted-foreground">{r.summary}</p>
        ),
      },
      {
        id: "when",
        header: "Date",
        className: "text-xs text-muted-foreground",
        cell: (r: PersistedReview) => formatRelativeTime(r.created_at),
      },
    ],
    [],
  );

  // ── Detail (progressive loading: chrome stays, data skeletons) ─────────
  if (selectedId) {
    const title =
      activeReview?.pr_number != null
        ? `PR #${activeReview.pr_number}`
        : activeReview
          ? `Review ${activeReview.id.slice(0, 8)}`
          : "Review detail";
    const loadingDetail = detail.isLoading && !detail.data;

    if (detail.isError && !detail.data) {
      return (
        <PageContainer variant="wide" className="space-y-4">
          <PageHeader
            title="Review detail"
            description="Could not load this review."
            actions={
              <Button variant="ghost" size="sm" onClick={backToList}>
                <ArrowLeft className="size-4" />
                Back to Reviews
              </Button>
            }
          />
          <ErrorState
            title="Review unavailable"
            description={
              detail.error instanceof ApiError ? detail.error.message : undefined
            }
            onRetry={() => void detail.refetch()}
          />
        </PageContainer>
      );
    }

    return (
      <PageContainer variant="wide" className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="ghost" size="sm" onClick={backToList}>
            <ArrowLeft className="size-4" />
            Back to Reviews
          </Button>
          <div className="min-w-0 flex-1">
            <h1 className="text-xl font-bold sm:text-2xl">{title}</h1>
            <p className="text-sm text-muted-foreground">
              {activeReview ? (
                <>
                  {formatRelativeTime(activeReview.created_at)} · {activeReview.provider}{" "}
                  · {activeReview.model}
                </>
              ) : (
                "Loading persisted review…"
              )}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {activeReview ? (
              <>
                <StatusBadge label={activeReview.risk || "unknown"} />
                <StatusBadge
                  label={`confidence ${Number(activeReview.confidence ?? 0).toFixed(2)}`}
                  tone="info"
                />
              </>
            ) : null}
            <Button
              size="sm"
              variant="outline"
              onClick={() => router.push("/repository")}
            >
              View Repository
            </Button>
          </div>
        </div>

        {loadingDetail ? (
          <div className="grid gap-3 sm:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <MetricSkeleton key={i} />
            ))}
          </div>
        ) : activeReview ? (
          <>
            <RiskSummary scores={riskScores} />
            <ReviewMetrics
              filesReviewed={
                detail.data
                  ? reviewFileCount(detail.data)
                  : reviewFileCount(activeReview)
              }
              suggestionsCount={reviewSuggestionCount(
                detail.data ?? activeReview,
              )}
              criticalCount={reviewCriticalCount(detail.data ?? activeReview)}
              warningCount={reviewWarningCount(detail.data ?? activeReview)}
            />
          </>
        ) : null}

        <Card className="p-4">
          <h3 className="mb-2 text-sm font-semibold">Summary</h3>
          {loadingDetail ? (
            <ListSkeleton rows={3} />
          ) : (
            <MarkdownViewer
              content={detail.data?.summary || activeReview?.summary || "_No summary_"}
            />
          )}
        </Card>

        {loadingDetail ? (
          <ListSkeleton rows={6} />
        ) : (
          <div className="grid min-w-0 gap-4 lg:grid-cols-[200px_minmax(0,1fr)] xl:grid-cols-[180px_minmax(240px,0.85fr)_minmax(380px,1.25fr)]">
            <FileExplorer
              files={changedFiles}
              selectedFile={selectedFile}
              onSelectFile={setUserSelectedFile}
              className="h-[min(40vh,320px)] min-w-0 lg:h-[600px]"
            />
            <Card className="order-last h-[min(40vh,280px)] min-w-0 overflow-hidden xl:order-none xl:h-[600px]">
              <div className="flex h-full min-w-0 flex-col">
                <div className="border-b bg-muted/40 px-4 py-2">
                  <h3 className="truncate text-sm font-semibold">
                    {selectedFile
                      ? selectedFile
                      : changedFiles.length
                        ? "Loading file…"
                        : "No changes to review"}
                  </h3>
                </div>
                <ScrollArea className="min-w-0 flex-1 p-4">
                  {!changedFiles.length ? (
                    <EmptyState
                      title="No changes to review"
                      description={
                        detail.data?.summary === "No changes to review"
                          ? "This PR has an empty base→head diff. Working-tree files are not reviewed."
                          : "No changed files were analyzed for this review."
                      }
                    />
                  ) : selectedFile ? (
                    <div className="min-w-0 space-y-3">
                      <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm text-muted-foreground">
                        <FileCode className="size-4 shrink-0" aria-hidden />
                        <span className="min-w-0 font-mono text-xs break-all">
                          {selectedFile}
                        </span>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            router.push(
                              `/repository?file=${encodeURIComponent(selectedFile)}`,
                            )
                          }
                        >
                          Open in Repository
                        </Button>
                      </div>
                      {(detail.data?.suggestions ?? []).filter(
                        (s) => s.file === selectedFile,
                      ).length === 0 ? (
                        <EmptyState
                          title="No findings"
                          description="No issues detected for this file."
                        />
                      ) : (
                        <Unavailable
                          title="Diff viewer unavailable"
                          reason="Requires Backend Support — Local API does not expose PR/file diff content for reviews."
                          actionLabel="Open in Repository Explorer"
                          onAction={() =>
                            router.push(
                              `/repository?file=${encodeURIComponent(selectedFile)}`,
                            )
                          }
                        />
                      )}
                    </div>
                  ) : (
                    <EmptyState
                      title="No changes to review"
                      description="Select a changed file or re-run the PR review."
                    />
                  )}
                </ScrollArea>
              </div>
            </Card>
            <SuggestionPanel
              suggestions={detail.data?.suggestions ?? []}
              selectedFile={selectedFile}
              onViewFile={(file) => {
                router.push(`/repository?file=${encodeURIComponent(file)}`);
              }}
              onFocusFile={(file) => {
                setUserSelectedFile(file);
              }}
              updatingSuggestionId={
                updateSuggestion.isPending
                  ? updateSuggestion.variables?.suggestionId ?? null
                  : null
              }
              onUpdateStatus={(suggestionId, status) => {
                const reviewId = detail.data?.id ?? selectedId;
                if (!reviewId) return;
                updateSuggestion.mutate({
                  reviewId,
                  cacheIds: [selectedId, detail.data?.id].filter(
                    (id): id is string => Boolean(id),
                  ),
                  suggestionId,
                  status,
                });
              }}
              className="h-[min(70vh,640px)] min-w-0 lg:col-span-1 xl:h-[600px]"
            />
          </div>
        )}
      </PageContainer>
    );
  }

  return (
    <PageContainer className="space-y-6">
      <PageHeader
        title="Reviews"
        description="AI-assisted code review history and detailed findings."
        actions={
          <div className="flex gap-2">
            <div className="flex gap-1 rounded-lg border p-1">
              <Button
                size="sm"
                variant={viewMode === "table" ? "secondary" : "ghost"}
                onClick={() => setView("table")}
              >
                <List className="size-4" />
              </Button>
              <Button
                size="sm"
                variant={viewMode === "cards" ? "secondary" : "ghost"}
                onClick={() => setView("cards")}
              >
                <LayoutGrid className="size-4" />
              </Button>
            </div>
            <Button size="sm" onClick={() => setOpen(true)}>
              Run Review
            </Button>
          </div>
        }
      />

      {list.isError ? (
        <ErrorState
          title="Could not load reviews"
          description={list.error instanceof ApiError ? list.error.message : undefined}
          onRetry={() => void list.refetch()}
        />
      ) : viewMode === "cards" ? (
        list.isLoading ? (
          <ListSkeleton rows={6} />
        ) : !(list.data ?? []).length ? (
          <EmptyState
            title="No reviews yet"
            description="Run a review to persist results for this repository."
            actionLabel="Run Review"
            onAction={() => setOpen(true)}
          />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {(list.data ?? []).map((r) => (
              <ReviewCard key={r.id} review={r} onClick={() => selectReview(r.id)} />
            ))}
          </div>
        )
      ) : (
        <DataTable
          columns={columns}
          data={list.data ?? []}
          getRowId={(r) => r.id}
          onRowClick={(r) => selectReview(r.id)}
          isLoading={list.isLoading}
          emptyTitle="No reviews yet"
          emptyDescription="Run a review to persist results for this repository."
          emptyActionLabel="Run Review"
          onEmptyAction={() => setOpen(true)}
          sort={sort}
          onSortChange={setSort}
          selectedId={selectedId}
        />
      )}

      <RunReviewDialog open={open} onOpenChange={setOpen} />
    </PageContainer>
  );
}
