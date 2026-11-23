"use client";

import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";
import {
  Ban,
  Check,
  Copy,
  GitBranch,
  LayoutGrid,
  List,
  Loader2,
  Wand2,
} from "lucide-react";

import { DataTable } from "@/components/data-display/data-table";
import {
  LifecycleBadge,
  LifecycleLegend,
} from "@/components/data-display/lifecycle-badge";
import { StatusBadge } from "@/components/data-display/status-badge";
import { EmptyState } from "@/components/feedback/empty-state";
import { ErrorState } from "@/components/feedback/error-state";
import { CardGridSkeleton } from "@/components/feedback/loading-skeletons";
import { FilterBar } from "@/components/filter-bar";
import { PageContainer } from "@/components/layout/page-container";
import { PageHeader } from "@/components/page-header";
import { PatchPreview } from "@/components/recommendations/patch-preview";
import { RecommendationCard } from "@/components/recommendations/recommendation-card";
import { RecommendationSummary } from "@/components/recommendations/recommendation-summary";
import { SearchInput } from "@/components/search-input";
import { DetailDrawer } from "@/components/shared/detail-drawer";
import { DetailSection } from "@/components/shared/detail-section";
import { RunReviewDialog } from "@/components/shared/run-review-dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { STORAGE_KEYS } from "@/lib/constants";
import { formatRelativeTime } from "@/lib/format";
import { useListFilters } from "@/hooks/use-list-filters";
import {
  useApplyRecommendationPatch,
  useGenerateRecommendationPatch,
  useGenerateRecommendations,
  useIgnoreRecommendation,
  useRecommendationPatches,
  useRecommendationStats,
  useRecommendations,
  useResolveRecommendation,
  useRollbackRecommendationPatch,
  useUpdateRecommendationNotes,
} from "@/queries/use-recommendations";
import { ApiError } from "@/services/errors";
import type {
  PatchApplyResult,
  PersistedRecommendation,
  RecommendationPatch,
} from "@/types/domain";

const PRIORITIES = ["critical", "high", "medium", "low"].map((v) => ({
  value: v,
  label: v,
}));

type ViewMode = "cards" | "table";

export function RecommendationsView() {
  const params = useSearchParams();
  const router = useRouter();
  const list = useRecommendations({ limit: 200 });
  const stats = useRecommendationStats();
  const generate = useGenerateRecommendations();
  const generatePatch = useGenerateRecommendationPatch();
  const applyPatch = useApplyRecommendationPatch();
  const rollbackPatch = useRollbackRecommendationPatch();
  const resolveRec = useResolveRecommendation();
  const ignoreRec = useIgnoreRecommendation();
  const saveNotes = useUpdateRecommendationNotes();
  const [drawerId, setDrawerId] = React.useState<string | null>(params.get("id"));
  const [notesDraft, setNotesDraft] = React.useState("");
  const [reviewOpen, setReviewOpen] = React.useState(false);
  const [patchState, setPatchState] = React.useState<{
    key: string;
    patch: RecommendationPatch | null;
    error: string | null;
  }>({ key: "", patch: null, error: null });
  const [applyState, setApplyState] = React.useState<{
    key: string;
    result: PatchApplyResult | null;
    error: string | null;
  }>({ key: "", result: null, error: null });
  const { filters, setSearch, setPriority, setCategory, setExtra } = useListFilters({
    storageKey: STORAGE_KEYS.recommendationsView,
    storageField: "view",
    defaults: {
      priority: params.get("priority"),
      extra: { view: "table" },
    },
  });
  const q = filters.search;
  const priority = filters.priority;
  const category = filters.category;
  const viewMode = (filters.extra.view as ViewMode) || "table";

  const selected: PersistedRecommendation | null = React.useMemo(() => {
    const id = drawerId ?? params.get("id");
    if (!id || !list.data) return null;
    return list.data.find((r) => r.id === id) ?? null;
  }, [drawerId, params, list.data]);

  const selectedId = selected?.id ?? null;

  React.useEffect(() => {
    setNotesDraft(selected?.resolution_notes ?? "");
  }, [selected?.id, selected?.resolution_notes]);

  const priorPatches = useRecommendationPatches(selectedId);
  const activePatch =
    selectedId && patchState.key === selectedId ? patchState.patch : null;
  const patchError =
    selectedId && patchState.key === selectedId ? patchState.error : null;

  const displayedPatch =
    activePatch ??
    (priorPatches.data?.[0] as RecommendationPatch | undefined) ??
    null;

  const applyResult =
    selectedId && applyState.key === selectedId ? applyState.result : null;
  const applyError =
    selectedId && applyState.key === selectedId ? applyState.error : null;

  const runGeneratePatch = () => {
    if (!selectedId) return;
    setPatchState({ key: selectedId, patch: null, error: null });
    setApplyState({ key: selectedId, result: null, error: null });
    generatePatch.mutate(selectedId, {
      onSuccess: (data) =>
        setPatchState({ key: selectedId, patch: data, error: null }),
      onError: (err) => {
        let message =
          err instanceof ApiError
            ? err.errors[0] || err.message || "Unable to generate patch"
            : "Unable to generate patch";
        if (err instanceof ApiError && err.status === 404) {
          message =
            "Patch API not found. Restart the Local API (uvicorn on port 8741) to load POST /recommendations/{id}/patch.";
        }
        setPatchState({ key: selectedId, patch: null, error: message });
      },
    });
  };

  const runApplyPatch = () => {
    if (!selectedId || !displayedPatch?.id) return;
    setApplyState({ key: selectedId, result: null, error: null });
    applyPatch.mutate(
      { recommendationId: selectedId, patchId: displayedPatch.id },
      {
        onSuccess: (data) =>
          setApplyState({ key: selectedId, result: data, error: null }),
        onError: (err) => {
          let message =
            err instanceof ApiError
              ? err.errors[0] || err.message || "Unable to apply patch"
              : "Unable to apply patch";
          if (err instanceof ApiError) {
            const lower = message.toLowerCase();
            if (err.status === 409) {
              if (lower.includes("outdated")) {
                message = err.errors[0] || "Patch outdated — generate a new patch.";
              } else if (lower.includes("dirty")) {
                message = err.errors[0] || "Dirty working tree — resolve conflicts first.";
              } else if (lower.includes("organization")) {
                message = err.errors[0] || "Blocked by organization policy.";
              } else {
                message =
                  err.errors[0] ||
                  "Patch conflict — the repository changed. Generate a new patch.";
              }
            } else if (err.status === 422 && lower.includes("validation")) {
              message = err.errors[0] || "Validation failed — changes were rolled back.";
            } else if (err.status === 404) {
              message =
                "Apply API not found. Restart the Local API to load POST /recommendations/{id}/apply.";
            }
          }
          setApplyState({ key: selectedId, result: null, error: message });
        },
      },
    );
  };

  const runRollbackPatch = () => {
    if (!selectedId || !displayedPatch?.id) return;
    rollbackPatch.mutate(
      { recommendationId: selectedId, patchId: displayedPatch.id },
      {
        onSuccess: (data) =>
          setApplyState({ key: selectedId, result: data, error: null }),
        onError: (err) => {
          const message =
            err instanceof ApiError
              ? err.errors[0] || err.message || "Unable to roll back patch"
              : "Unable to roll back patch";
          setApplyState({ key: selectedId, result: null, error: message });
        },
      },
    );
  };

  const categories = React.useMemo(() => {
    const set = new Set((list.data ?? []).map((r) => r.type).filter(Boolean));
    return [...set].sort().map((v) => ({ value: v, label: v }));
  }, [list.data]);

  const filtered = React.useMemo(() => {
    return (list.data ?? []).filter((r) => {
      if (priority && r.priority !== priority) return false;
      if (category && r.type !== category) return false;
      if (q) {
        const hay = `${r.title} ${r.description}`.toLowerCase();
        if (!hay.includes(q.toLowerCase())) return false;
      }
      return true;
    });
  }, [list.data, priority, category, q]);

  const counts = React.useMemo(() => {
    const s = stats.data;
    return {
      critical: s?.critical ?? 0,
      high: s?.high ?? 0,
      medium: s?.medium ?? 0,
      low: s?.low ?? 0,
      pending: s?.pending ?? 0,
      applied: s?.applied ?? 0,
      resolved: s?.resolved ?? 0,
      ignored: s?.ignored ?? 0,
    };
  }, [stats.data]);

  const openDrawer = (id: string) => {
    setDrawerId(id);
    router.replace(`/recommendations?id=${id}`);
  };

  const toggleViewMode = (mode: ViewMode) => {
    setExtra("view", mode);
  };

  const columns = React.useMemo(
    () => [
      {
        id: "title",
        header: "Title",
        cell: (r: PersistedRecommendation) => (
          <span className="font-medium">{r.title}</span>
        ),
      },
      {
        id: "priority",
        header: "Priority",
        cell: (r: PersistedRecommendation) => <StatusBadge label={r.priority} />,
      },
      {
        id: "type",
        header: "Type",
        className: "text-muted-foreground",
        cell: (r: PersistedRecommendation) => r.type,
      },
      {
        id: "status",
        header: "Status",
        cell: (r: PersistedRecommendation) => (
          <LifecycleBadge status={r.status} />
        ),
      },
      {
        id: "when",
        header: "When",
        className: "text-xs text-muted-foreground",
        cell: (r: PersistedRecommendation) => formatRelativeTime(r.created_at),
      },
    ],
    [],
  );

  return (
    <PageContainer className="space-y-6">
      <PageHeader
        title="Recommendations"
        description="AI-generated engineering recommendations as an actionable backlog."
        actions={
          <Button size="sm" disabled={generate.isPending} onClick={() => generate.mutate({})}>
            Generate
          </Button>
        }
      />

      <RecommendationSummary
        critical={counts.critical}
        high={counts.high}
        medium={counts.medium}
        low={counts.low}
        pending={counts.pending}
        applied={counts.applied}
        resolved={counts.resolved}
        ignored={counts.ignored}
        selectedPriority={priority}
        onSelectPriority={setPriority}
        caption="Repository totals from RecommendationStatsService (same source as Branch Surgeon)."
        summaryMeta={stats.data ?? null}
      />

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-1 flex-col gap-3 lg:flex-row lg:items-center">
          <SearchInput
            className="lg:max-w-xs"
            value={q}
            onChange={setSearch}
            placeholder="Search…"
          />
          <FilterBar
            options={PRIORITIES}
            value={priority}
            onChange={setPriority}
            allLabel="All priorities"
          />
          <FilterBar
            options={categories}
            value={category}
            onChange={setCategory}
            allLabel="All types"
          />
        </div>
        <div className="flex gap-1 rounded-lg border p-1">
          <Button
            size="sm"
            variant={viewMode === "table" ? "secondary" : "ghost"}
            onClick={() => toggleViewMode("table")}
          >
            <List className="size-4" />
          </Button>
          <Button
            size="sm"
            variant={viewMode === "cards" ? "secondary" : "ghost"}
            onClick={() => toggleViewMode("cards")}
          >
            <LayoutGrid className="size-4" />
          </Button>
        </div>
      </div>

      {list.isError ? (
        <ErrorState
          title="Could not load recommendations"
          description={list.error instanceof ApiError ? list.error.message : undefined}
          onRetry={() => void list.refetch()}
        />
      ) : viewMode === "cards" ? (
        list.isLoading ? (
          <CardGridSkeleton />
        ) : !filtered.length ? (
          <EmptyState
            title="No recommendations"
            description="Generate recommendations or clear filters."
            actionLabel="Generate"
            onAction={() => generate.mutate({})}
          />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((r) => (
              <RecommendationCard
                key={r.id}
                recommendation={r}
                onClick={() => openDrawer(r.id)}
              />
            ))}
          </div>
        )
      ) : (
        <DataTable
          columns={columns}
          data={filtered}
          getRowId={(r) => r.id}
          onRowClick={(r) => openDrawer(r.id)}
          isLoading={list.isLoading}
          emptyTitle="No recommendations"
          emptyDescription="Generate recommendations or clear filters."
          emptyActionLabel="Generate"
          onEmptyAction={() => generate.mutate({})}
          selectedId={drawerId}
        />
      )}

      <DetailDrawer
        open={Boolean(selected)}
        onOpenChange={(o) => {
          if (!o) {
            setDrawerId(null);
            router.replace("/recommendations");
          }
        }}
        title={selected?.title ?? ""}
        description="Recommendation detail"
        badges={
          selected ? (
            <>
              <StatusBadge label={selected.priority} />
              <StatusBadge label={selected.type} tone="info" />
              <LifecycleBadge status={selected.status} />
            </>
          ) : null
        }
        footer={
          selected ? (
            <div className="flex w-full flex-col gap-2">
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  disabled={generatePatch.isPending}
                  onClick={runGeneratePatch}
                  aria-label="Generate AI patch for recommendation"
                >
                  <Wand2 className="size-3" aria-hidden />
                  {generatePatch.isPending ? "Generating…" : "Generate Patch"}
                </Button>
                <Button size="sm" variant="outline" onClick={() => router.push("/transform")}>
                  <GitBranch className="size-3" aria-hidden />
                  Open Transform
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label="Copy recommendation JSON"
                  onClick={() => {
                    void navigator.clipboard.writeText(JSON.stringify(selected, null, 2));
                    toast.success("Copied recommendation to clipboard");
                  }}
                >
                  <Copy className="size-3" aria-hidden />
                  Copy
                </Button>
              </div>
              {["pending", "applied", "rolled_back"].includes(
                (selected.status || "").toLowerCase(),
              ) ? (
                <div className="flex flex-wrap gap-2 border-t pt-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={ignoreRec.isPending || resolveRec.isPending}
                    data-testid="ignore-recommendation"
                    onClick={() => ignoreRec.mutate(selected.id)}
                  >
                    {ignoreRec.isPending ? (
                      <Loader2 className="size-3 animate-spin" aria-hidden />
                    ) : (
                      <Ban className="size-3" aria-hidden />
                    )}
                    Ignore
                  </Button>
                  <Button
                    size="sm"
                    disabled={resolveRec.isPending || ignoreRec.isPending}
                    data-testid="resolve-recommendation"
                    onClick={() => resolveRec.mutate(selected.id)}
                  >
                    {resolveRec.isPending ? (
                      <Loader2 className="size-3 animate-spin" aria-hidden />
                    ) : (
                      <Check className="size-3" aria-hidden />
                    )}
                    Mark Resolved
                  </Button>
                </div>
              ) : null}
            </div>
          ) : null
        }
      >
        {selected ? (
          <div className="space-y-4">
            <LifecycleLegend className="rounded-md border bg-muted/20 p-2" />
            <DetailSection title="Description">
              <p className="whitespace-pre-wrap text-foreground">
                {selected.description || "—"}
              </p>
            </DetailSection>
            <DetailSection title="Reasoning">
              <p className="whitespace-pre-wrap text-foreground">
                {selected.reasoning?.trim() ||
                  selected.description?.trim() ||
                  "No reasoning captured for this recommendation."}
              </p>
            </DetailSection>
            <DetailSection title="Affected Files">
              {(selected.affected_files?.length
                ? selected.affected_files
                : displayedPatch?.changed_files) ? (
                <div className="flex flex-wrap gap-1.5">
                  {(selected.affected_files?.length
                    ? selected.affected_files
                    : displayedPatch?.changed_files || []
                  ).map((f) => (
                    <button
                      key={f}
                      type="button"
                      className="rounded-md border bg-muted/40 px-2 py-1 font-mono text-xs transition-colors hover:bg-muted"
                      onClick={() =>
                        router.push(`/repository?file=${encodeURIComponent(f)}`)
                      }
                    >
                      {f}
                    </button>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No affected files recorded. Generate a patch to discover targets.
                </p>
              )}
            </DetailSection>
            <DetailSection title="Impact Assessment">
              {selected.impact?.length ? (
                <div className="flex flex-wrap gap-1.5">
                  {selected.impact.map((tag) => (
                    <StatusBadge key={tag} label={tag} tone="info" />
                  ))}
                </div>
              ) : (
                <StatusBadge label={selected.type || "Maintainability"} tone="info" />
              )}
            </DetailSection>
            <DetailSection title="Effort & Confidence">
              <div className="flex flex-wrap gap-3 text-sm">
                <div>
                  <p className="text-xs text-muted-foreground">Effort</p>
                  <p className="font-semibold tabular-nums">
                    {selected.effort || "—"}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Confidence</p>
                  <p className="font-semibold tabular-nums">
                    {selected.confidence != null
                      ? `${Math.round(selected.confidence * 100)}%`
                      : "—"}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Verification</p>
                  <p className="font-semibold capitalize">
                    {selected.verification_status || "unverified"}
                  </p>
                </div>
              </div>
            </DetailSection>
            <DetailSection title="Notes">
              <Textarea
                value={notesDraft}
                onChange={(e) => setNotesDraft(e.target.value)}
                placeholder="Fixed in commit abc123 / False positive / Not applicable"
                rows={3}
                className="text-sm"
              />
              <Button
                size="sm"
                className="mt-2"
                variant="outline"
                disabled={
                  saveNotes.isPending ||
                  notesDraft === (selected.resolution_notes ?? "")
                }
                onClick={() =>
                  saveNotes.mutate({
                    id: selected.id,
                    resolution_notes: notesDraft,
                  })
                }
              >
                {saveNotes.isPending ? (
                  <Loader2 className="size-3 animate-spin" aria-hidden />
                ) : null}
                Save notes
              </Button>
            </DetailSection>

            <DetailSection title="Patch History">
              {priorPatches.isLoading ? (
                <p className="text-sm text-muted-foreground">Loading patches…</p>
              ) : priorPatches.data?.length ? (
                <ul className="space-y-2">
                  {[...priorPatches.data]
                    .slice()
                    .reverse()
                    .map((p, idx, arr) => {
                      const version = arr.length - idx;
                      return (
                        <li
                          key={p.id}
                          className="rounded-md border px-3 py-2 text-sm"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-medium">Patch v{version}</span>
                            <StatusBadge label={p.status || "generated"} />
                            {p.applied_by ? (
                              <span className="text-xs text-muted-foreground">
                                by {p.applied_by}
                              </span>
                            ) : null}
                          </div>
                          <p className="mt-1 text-xs text-muted-foreground">
                            Created {formatRelativeTime(p.created_at ?? null)}
                            {p.applied_at
                              ? ` · Applied ${formatRelativeTime(p.applied_at)}`
                              : ""}
                          </p>
                        </li>
                      );
                    })}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No patches yet. Generate a patch to start history.
                </p>
              )}
            </DetailSection>

            <PatchPreview
              patch={
                generatePatch.isPending || patchError ? null : displayedPatch
              }
              isLoading={generatePatch.isPending}
              isError={Boolean(patchError)}
              errorMessage={patchError ?? undefined}
              onRetry={runGeneratePatch}
              isApplying={applyPatch.isPending}
              isRollingBack={rollbackPatch.isPending}
              applyResult={applyResult}
              applyError={applyError}
              recommendationStatus={selected.status}
              onApply={runApplyPatch}
              onRollback={runRollbackPatch}
              onOpenFile={(filePath) =>
                router.push(`/repository?file=${encodeURIComponent(filePath)}`)
              }
              onOpenRepository={() => router.push("/repository")}
              onViewChanges={() =>
                router.push(
                  `/repository?file=${encodeURIComponent(
                    displayedPatch?.changed_files?.[0] || "",
                  )}`,
                )
              }
              onRunReviewAgain={() => setReviewOpen(true)}
              onGenerateRecommendation={() => generate.mutate({})}
            />

            <p className="text-2xs text-muted-foreground">
              Created {formatRelativeTime(selected.created_at)}
              {selected.updated_at
                ? ` · Updated ${formatRelativeTime(selected.updated_at)}`
                : ""}
              {selected.updated_by ? ` · by ${selected.updated_by}` : ""}
            </p>
          </div>
        ) : null}
      </DetailDrawer>

      <RunReviewDialog
        open={reviewOpen}
        onOpenChange={setReviewOpen}
        description="Re-run the existing review pipeline against the updated working tree (POST /review)."
      />
    </PageContainer>
  );
}
