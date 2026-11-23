"use client";

import * as React from "react";
import {
  Copy,
  Download,
  FileCode2,
  FolderGit2,
  RefreshCw,
  RotateCcw,
  Wand2,
} from "lucide-react";
import { toast } from "sonner";

import { DiffViewer } from "@/components/diff-viewer";
import { StatusBadge } from "@/components/data-display/status-badge";
import { ErrorState } from "@/components/feedback/error-state";
import { ListSkeleton } from "@/components/feedback/loading-skeletons";
import { DetailSection } from "@/components/shared/detail-section";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { countDiffLines } from "@/lib/diff-stats";
import type { PatchApplyResult, RecommendationPatch } from "@/types/domain";

type PatchPreviewProps = {
  patch: RecommendationPatch | null;
  isLoading?: boolean;
  isError?: boolean;
  errorMessage?: string;
  onRetry?: () => void;
  isApplying?: boolean;
  isRollingBack?: boolean;
  applyResult?: PatchApplyResult | null;
  applyError?: string | null;
  recommendationStatus?: string | null;
  onApply?: () => void;
  onRollback?: () => void;
  onOpenFile?: (filePath: string) => void;
  onOpenRepository?: () => void;
  onViewChanges?: () => void;
  onRunReviewAgain?: () => void;
  onGenerateRecommendation?: () => void;
};

export function PatchPreview({
  patch,
  isLoading,
  isError,
  errorMessage,
  onRetry,
  isApplying,
  isRollingBack,
  applyResult,
  applyError,
  recommendationStatus,
  onApply,
  onRollback,
  onOpenFile,
  onOpenRepository,
  onViewChanges,
  onRunReviewAgain,
  onGenerateRecommendation,
}: PatchPreviewProps) {
  const [confirmOpen, setConfirmOpen] = React.useState(false);

  if (isLoading) {
    return (
      <DetailSection title="AI Patch">
        <ListSkeleton rows={4} />
      </DetailSection>
    );
  }

  if (isError) {
    return (
      <DetailSection title="AI Patch">
        <ErrorState
          title="Unable to generate patch"
          description={errorMessage}
          onRetry={onRetry}
        />
      </DetailSection>
    );
  }

  if (!patch) {
    return (
      <DetailSection title="AI Patch">
        <p className="text-sm text-muted-foreground">
          Generate an AI patch for this recommendation, then apply it to the working tree.
        </p>
        {onRetry ? (
          <Button size="sm" className="mt-2" onClick={onRetry}>
            <Wand2 className="size-3" aria-hidden />
            Generate Patch
          </Button>
        ) : null}
      </DetailSection>
    );
  }

  const applyAvailable = patch.apply_available !== false;
  const applied =
    applyResult?.applied === true ||
    applyResult?.status === "applied" ||
    recommendationStatus === "applied" ||
    patch.status === "applied";
  const rolledBack = applyResult?.status === "rolled_back";
  const primaryFile = patch.changed_files?.[0];
  const diffStats = countDiffLines(patch.unified_diff);
  const riskLabel =
    diffStats.added + diffStats.removed > 80
      ? "high"
      : diffStats.added + diffStats.removed > 25
        ? "medium"
        : "low";

  const copyPatch = async () => {
    try {
      await navigator.clipboard.writeText(patch.unified_diff || "");
      toast.success("Patch copied");
    } catch {
      toast.error("Unable to copy patch");
    }
  };

  const downloadPatch = () => {
    const blob = new Blob([patch.unified_diff || ""], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `patch-${patch.id || "recommendation"}.diff`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const confirmApply = () => {
    setConfirmOpen(false);
    onApply?.();
  };

  return (
    <DetailSection title="AI Patch">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge
            label={applied ? "Applied" : rolledBack ? "Rolled back" : "Ready"}
            tone={applied ? "success" : rolledBack ? "warn" : "info"}
          />
          {typeof patch.confidence === "number" ? (
            <StatusBadge
              label={`${Math.round(patch.confidence * 100)}% confidence`}
              tone="muted"
            />
          ) : null}
          {applyResult?.git_commit ? (
            <StatusBadge
              label={`HEAD ${applyResult.git_commit.slice(0, 8)}`}
              tone="muted"
            />
          ) : null}
          {applyResult?.applied_by ? (
            <StatusBadge label={`by ${applyResult.applied_by}`} tone="muted" />
          ) : null}
        </div>

        {patch.explanation ? (
          <p className="text-sm text-muted-foreground">{patch.explanation}</p>
        ) : null}

        <div className="grid gap-2 sm:grid-cols-4">
          <div className="rounded-md border px-2 py-1.5">
            <p className="text-2xs text-muted-foreground">Files</p>
            <p className="text-sm font-semibold tabular-nums">
              {(patch.changed_files ?? []).length}
            </p>
          </div>
          <div className="rounded-md border px-2 py-1.5">
            <p className="text-2xs text-muted-foreground">Added</p>
            <p className="text-sm font-semibold tabular-nums text-emerald-500">
              +{diffStats.added}
            </p>
          </div>
          <div className="rounded-md border px-2 py-1.5">
            <p className="text-2xs text-muted-foreground">Removed</p>
            <p className="text-sm font-semibold tabular-nums text-rose-500">
              −{diffStats.removed}
            </p>
          </div>
          <div className="rounded-md border px-2 py-1.5">
            <p className="text-2xs text-muted-foreground">Risk</p>
            <p className="text-sm font-semibold capitalize">{riskLabel}</p>
          </div>
        </div>

        <div>
          <p className="mb-1 text-xs font-medium text-muted-foreground">Changed files</p>
          {(patch.changed_files ?? []).length ? (
            <ul className="space-y-0.5">
              {patch.changed_files.map((f) => (
                <li key={f}>
                  <button
                    type="button"
                    className="font-mono text-xs text-foreground underline-offset-2 hover:underline"
                    onClick={() => onOpenFile?.(f)}
                  >
                    {f}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">None returned</p>
          )}
        </div>

        <div>
          <p className="mb-1 text-xs font-medium text-muted-foreground">
            Unified diff
          </p>
          <DiffViewer value={patch.unified_diff || ""} height="280px" />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="outline" onClick={copyPatch} aria-label="Copy patch">
            <Copy className="size-3" aria-hidden />
            Copy Patch
          </Button>
          <Button size="sm" variant="outline" onClick={downloadPatch} aria-label="Download patch">
            <Download className="size-3" aria-hidden />
            Download Patch
          </Button>
          {!applied ? (
            <Button
              size="sm"
              disabled={!applyAvailable || isApplying || !onApply || rolledBack}
              onClick={() => setConfirmOpen(true)}
              aria-label="Apply patch to repository"
            >
              {isApplying ? "Applying…" : "Apply Patch"}
            </Button>
          ) : null}
        </div>

        {applyError ? (
          <ErrorState
            title="Unable to apply patch"
            description={applyError}
            onRetry={onApply}
          />
        ) : null}

        {(applied || rolledBack) && applyResult ? (
          <div className="space-y-2 rounded-md border border-border/60 bg-muted/30 p-3">
            <p className="text-sm font-medium text-foreground">
              {applyResult.message ||
                (applied ? "Patch applied successfully." : "Patch rolled back.")}
            </p>
            <p className="text-xs text-muted-foreground">
              {applyResult.changed_files.length} file(s)
              {applyResult.git_commit
                ? ` · git ${applyResult.git_commit.slice(0, 8)}`
                : ""}
              {applyResult.applied_at
                ? ` · ${new Date(applyResult.applied_at).toLocaleString()}`
                : ""}
              {applyResult.recommendation_status
                ? ` · status ${applyResult.recommendation_status}`
                : ""}
              {applyResult.index_updated ? " · index refreshed" : ""}
              {applyResult.graph_updated ? " · graph refreshed" : ""}
            </p>
            <div className="flex flex-wrap gap-2">
              {onViewChanges ? (
                <Button size="sm" variant="outline" onClick={onViewChanges}>
                  <FileCode2 className="size-3" aria-hidden />
                  View changes
                </Button>
              ) : null}
              {applied && onRollback ? (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={isRollingBack}
                  onClick={onRollback}
                >
                  <RotateCcw className="size-3" aria-hidden />
                  {isRollingBack ? "Rolling back…" : "Rollback"}
                </Button>
              ) : null}
              {onOpenRepository ? (
                <Button size="sm" variant="outline" onClick={onOpenRepository}>
                  <FolderGit2 className="size-3" aria-hidden />
                  Open Repository
                </Button>
              ) : null}
              {primaryFile && onOpenFile ? (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onOpenFile(primaryFile)}
                >
                  <FileCode2 className="size-3" aria-hidden />
                  Open File
                </Button>
              ) : null}
              {onRunReviewAgain ? (
                <Button size="sm" variant="outline" onClick={onRunReviewAgain}>
                  <RefreshCw className="size-3" aria-hidden />
                  Run Review Again
                </Button>
              ) : null}
              {onGenerateRecommendation ? (
                <Button size="sm" variant="outline" onClick={onGenerateRecommendation}>
                  <Wand2 className="size-3" aria-hidden />
                  Generate New Recommendation
                </Button>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Apply patch to working tree?</DialogTitle>
            <DialogDescription>
              This writes modified files into the configured repository root via the
              service layer (GitService). Changes are not staged or committed. If
              validation fails, files are rolled back.
            </DialogDescription>
          </DialogHeader>
          {(patch.changed_files ?? []).length ? (
            <ul className="max-h-32 space-y-0.5 overflow-auto font-mono text-xs">
              {patch.changed_files.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          ) : null}
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button onClick={confirmApply} disabled={isApplying}>
              {isApplying ? "Applying…" : "Apply Patch"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </DetailSection>
  );
}
