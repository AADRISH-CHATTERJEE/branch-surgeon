"use client";

import * as React from "react";

import { DiffViewer } from "@/components/diff-viewer";
import { StatusBadge } from "@/components/data-display/status-badge";
import { EmptyState } from "@/components/feedback/empty-state";
import { PageContainer } from "@/components/layout/page-container";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { formatRelativeTime } from "@/lib/format";
import {
  useApplyTransform,
  usePlanTransform,
  usePreviewTransform,
  useRecentTransforms,
  useRollbackTransformById,
} from "@/queries/use-transform";
import type { TransformBody } from "@/services/transform";
import { toast } from "sonner";

const TYPES = [
  { value: "rename_symbol", label: "Rename Symbol" },
  { value: "rename_function", label: "Rename Function" },
  { value: "rename_class", label: "Rename Class" },
  { value: "rename_variable", label: "Rename Variable" },
  { value: "rename_file", label: "Rename File" },
  { value: "extract_method", label: "Extract Method" },
  { value: "inline_method", label: "Inline Method" },
  { value: "move_symbol", label: "Move Symbol" },
  { value: "change_signature", label: "Change Signature" },
  { value: "ai_plan", label: "AI Plan (natural language)" },
] as const;

export function TransformView() {
  const [targetFile, setTargetFile] = React.useState("");
  const [targetSymbol, setTargetSymbol] = React.useState("");
  const [type, setType] = React.useState<string>("rename_symbol");
  const [newName, setNewName] = React.useState("");
  const [methodName, setMethodName] = React.useState("extracted_method");
  const [startLine, setStartLine] = React.useState("");
  const [endLine, setEndLine] = React.useState("");
  const [destinationFile, setDestinationFile] = React.useState("");
  const [paramOrder, setParamOrder] = React.useState("");
  const [naturalLanguage, setNaturalLanguage] = React.useState("");
  const [scope, setScope] = React.useState<string>("repository");

  const plan = usePlanTransform();
  const preview = usePreviewTransform();
  const apply = useApplyTransform();
  const rollbackById = useRollbackTransformById();
  const recent = useRecentTransforms(5);

  const isRename =
    type.startsWith("rename_") || type === "change_signature";

  const body = React.useMemo((): TransformBody => {
    const payload: TransformBody = {
      target_file: targetFile.trim(),
      target_symbol: targetSymbol.trim(),
      transformation_type: type,
      parameters: {},
      scope,
      natural_language: naturalLanguage.trim() || undefined,
      ai_assisted: Boolean(naturalLanguage.trim()) || type === "ai_plan",
    };
    if (isRename) {
      if (newName.trim()) payload.new_name = newName.trim();
    }
    if (type === "extract_method") {
      if (methodName.trim()) payload.method_name = methodName.trim();
      const start = Number(startLine);
      const end = Number(endLine);
      if (Number.isFinite(start) && start > 0) payload.start_line = start;
      if (Number.isFinite(end) && end > 0) payload.end_line = end;
    }
    if (type === "move_symbol" && destinationFile.trim()) {
      payload.destination_file = destinationFile.trim();
    }
    if (type === "rename_file" && destinationFile.trim()) {
      payload.new_name = destinationFile.trim();
    }
    if (type === "change_signature" && paramOrder.trim()) {
      payload.param_order = paramOrder
        .split(",")
        .map((p) => p.trim())
        .filter(Boolean);
    }
    return payload;
  }, [
    destinationFile,
    endLine,
    isRename,
    methodName,
    naturalLanguage,
    newName,
    paramOrder,
    scope,
    startLine,
    targetFile,
    targetSymbol,
    type,
  ]);

  const planData = plan.data;
  const previewData = preview.data;
  const result = apply.data ?? rollbackById.data;

  const planPanel = planData ?? previewData?.plan ?? null;
  const operations = planPanel?.operations ?? previewData?.operations ?? [];
  const affectedFiles =
    planPanel?.affected_files ??
    previewData?.files_modified ??
    [];
  const risk = planPanel?.estimated_risk ?? previewData?.risk;
  const confidence =
    planPanel?.estimated_confidence ?? previewData?.confidence;
  const goal = planPanel?.goal ?? previewData?.goal ?? previewData?.description;

  function requireTargetOrNl(): boolean {
    if (naturalLanguage.trim() || type === "ai_plan") {
      if (!naturalLanguage.trim()) {
        toast.error("Describe the refactoring in natural language.");
        return false;
      }
      return true;
    }
    if (!targetFile.trim() && scope === "file") {
      toast.error("Target file is required for file scope.");
      return false;
    }
    if (
      isRename &&
      type !== "rename_file" &&
      !targetSymbol.trim() &&
      !naturalLanguage.trim()
    ) {
      toast.error("Target symbol is required for rename.");
      return false;
    }
    return true;
  }

  function runPlan() {
    if (!requireTargetOrNl()) return;
    plan.mutate(body);
  }

  function runPreview() {
    if (!requireTargetOrNl()) return;
    preview.mutate(body);
  }

  function runApply() {
    if (!requireTargetOrNl()) return;
    apply.mutate(body);
  }

  return (
    <PageContainer className="space-y-6">
      <PageHeader
        title="Branch Surgeon · Transformations"
        description="Repository-wide refactors with an AI planner — preview, apply, then roll back from history."
      />

      <div className="grid gap-4 rounded-lg border p-4 md:grid-cols-2">
        <div className="space-y-2 md:col-span-2">
          <Label htmlFor="nl-goal">Natural language goal (AI planner)</Label>
          <Textarea
            id="nl-goal"
            className="min-h-[72px] font-mono text-sm"
            placeholder='e.g. Rename login() to authenticate() — or Split auth.py into auth.py and security.py'
            value={naturalLanguage}
            onChange={(e) => setNaturalLanguage(e.target.value)}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="file">Target file (optional for repo-wide rename)</Label>
          <Input
            id="file"
            className="font-mono text-sm"
            placeholder="path/to/file.py"
            value={targetFile}
            onChange={(e) => setTargetFile(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="symbol">Target symbol</Label>
          <Input
            id="symbol"
            className="font-mono text-sm"
            placeholder="login"
            value={targetSymbol}
            onChange={(e) => setTargetSymbol(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label>Transformation type</Label>
          <Select value={type} onValueChange={setType}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TYPES.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label>Scope</Label>
          <Select value={scope} onValueChange={setScope}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="repository">Repository-wide</SelectItem>
              <SelectItem value="file">Single file</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {isRename && type !== "rename_file" ? (
          <div className="space-y-2">
            <Label htmlFor="new-name">New name</Label>
            <Input
              id="new-name"
              className="font-mono text-sm"
              placeholder="authenticate"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
          </div>
        ) : null}

        {type === "extract_method" ? (
          <>
            <div className="space-y-2">
              <Label htmlFor="method-name">New method name</Label>
              <Input
                id="method-name"
                className="font-mono text-sm"
                value={methodName}
                onChange={(e) => setMethodName(e.target.value)}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="start-line">Start line (optional)</Label>
                <Input
                  id="start-line"
                  type="number"
                  min={1}
                  value={startLine}
                  onChange={(e) => setStartLine(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="end-line">End line (optional)</Label>
                <Input
                  id="end-line"
                  type="number"
                  min={1}
                  value={endLine}
                  onChange={(e) => setEndLine(e.target.value)}
                />
              </div>
            </div>
            <p className="text-xs text-muted-foreground md:col-span-2">
              If lines are omitted, the body of the target function is extracted.
            </p>
          </>
        ) : null}

        {type === "move_symbol" || type === "rename_file" ? (
          <div className="space-y-2 md:col-span-2">
            <Label htmlFor="dest-file">
              {type === "rename_file" ? "New file path" : "Destination file"}
            </Label>
            <Input
              id="dest-file"
              className="font-mono text-sm"
              placeholder="path/to/destination.py"
              value={destinationFile}
              onChange={(e) => setDestinationFile(e.target.value)}
            />
          </div>
        ) : null}

        {type === "change_signature" ? (
          <div className="space-y-2 md:col-span-2">
            <Label htmlFor="param-order">Param order (comma-separated, optional)</Label>
            <Input
              id="param-order"
              className="font-mono text-sm"
              placeholder="password, user"
              value={paramOrder}
              onChange={(e) => setParamOrder(e.target.value)}
            />
          </div>
        ) : null}

        <div className="flex flex-wrap gap-2 md:col-span-2">
          <Button size="sm" variant="secondary" disabled={plan.isPending} onClick={runPlan}>
            Build Plan
          </Button>
          <Button size="sm" disabled={preview.isPending} onClick={runPreview}>
            Preview
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={apply.isPending}
            onClick={runApply}
          >
            Apply
          </Button>
        </div>
      </div>

      {planPanel || operations.length > 0 ? (
        <section className="space-y-3 rounded-lg border p-4">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-medium">Transformation Plan</h2>
            {risk ? <StatusBadge label={`Risk: ${risk}`} /> : null}
            {typeof confidence === "number" ? (
              <StatusBadge
                label={`Confidence: ${Math.round(confidence * 100)}%`}
                tone="muted"
              />
            ) : null}
          </div>
          <p className="text-sm text-muted-foreground">{goal || "No goal"}</p>
          <div>
            <h3 className="mb-1 text-2xs font-medium uppercase tracking-wide text-muted-foreground">
              Operations
            </h3>
            {operations.length === 0 ? (
              <p className="text-sm text-muted-foreground">No operations listed.</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {operations.map((op, i) => (
                  <li key={`${op.op}-${i}`} className="flex flex-wrap items-center gap-2">
                    <StatusBadge label={op.op} tone="info" />
                    <span>{op.description || op.target || op.op}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <h3 className="mb-1 text-2xs font-medium uppercase tracking-wide text-muted-foreground">
              Affected files
            </h3>
            <div className="flex flex-wrap gap-1">
              {affectedFiles.length === 0 ? (
                <span className="text-sm text-muted-foreground">None yet</span>
              ) : (
                affectedFiles.map((f) => (
                  <StatusBadge key={f} label={f} tone="muted" />
                ))
              )}
            </div>
          </div>
        </section>
      ) : null}

      {previewData ? (
        <section className="space-y-3 rounded-lg border p-4">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-medium">Preview</h2>
            {previewData.risk ? <StatusBadge label={previewData.risk} /> : null}
            {typeof previewData.confidence === "number" ? (
              <StatusBadge
                label={`${Math.round(previewData.confidence * 100)}% confidence`}
                tone="muted"
              />
            ) : null}
            {previewData.rollback_available !== false ? (
              <StatusBadge label="Rollback available" tone="success" />
            ) : null}
          </div>
          <dl className="grid gap-2 text-sm sm:grid-cols-3">
            <div className="rounded-md border px-3 py-2">
              <dt className="text-2xs uppercase text-muted-foreground">Estimated changes</dt>
              <dd className="font-medium tabular-nums">
                {(previewData.additions ?? 0) + (previewData.deletions ?? 0)}
              </dd>
            </div>
            <div className="rounded-md border px-3 py-2">
              <dt className="text-2xs uppercase text-muted-foreground">Lines added</dt>
              <dd className="font-medium tabular-nums text-emerald-600 dark:text-emerald-400">
                +{previewData.additions ?? 0}
              </dd>
            </div>
            <div className="rounded-md border px-3 py-2">
              <dt className="text-2xs uppercase text-muted-foreground">Lines removed</dt>
              <dd className="font-medium tabular-nums text-rose-600 dark:text-rose-400">
                −{previewData.deletions ?? 0}
              </dd>
            </div>
          </dl>
          <p className="text-sm text-muted-foreground">
            {previewData.description || "No description"}
          </p>
          <div className="flex flex-wrap gap-1">
            {(previewData.files_modified ?? []).map((f) => (
              <StatusBadge key={f} label={f} tone="muted" />
            ))}
          </div>
          <DiffViewer value={previewData.diff_preview ?? ""} />
        </section>
      ) : (
        <EmptyState
          title="No preview yet"
          description="Build a plan, then Preview to generate a unified diff from the Local API."
        />
      )}

      {result ? (
        <section className="rounded-lg border p-4 text-sm">
          <h2 className="mb-2 font-medium">Result</h2>
          <div className="flex flex-wrap gap-2">
            {result.status ? <StatusBadge label={result.status} /> : null}
            {result.id ? <StatusBadge label={result.id} tone="muted" /> : null}
          </div>
          <ul className="mt-2 list-inside list-disc text-muted-foreground">
            {(result.files_modified ?? []).map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="space-y-3 rounded-lg border p-4">
        <h2 className="text-sm font-medium">Recent Transformations</h2>
        {(recent.data ?? []).length === 0 ? (
          <EmptyState
            className="py-8"
            title="No applied transformations yet"
            description="Apply a preview to populate this list."
          />
        ) : (
          <div className="overflow-x-auto rounded-md border">
            <div className="grid min-w-[44rem] grid-cols-[7rem_1fr_1fr_6rem_9.5rem] gap-2 border-b bg-muted/40 px-3 py-2 text-2xs font-medium uppercase tracking-wide text-muted-foreground">
              <span>Time</span>
              <span>Operation</span>
              <span>File</span>
              <span>Status</span>
              <span>Rollback Available</span>
            </div>
            <ul className="divide-y">
              {(recent.data ?? []).map((item) => {
                const rolledBack =
                  item.rolled_back === true ||
                  String(item.status || "").toLowerCase() === "rolled_back";
                const canRollback =
                  item.canRollback ??
                  item.can_rollback ??
                  (!rolledBack && String(item.status || "").toLowerCase() === "applied");
                const operation =
                  item.transformation_type ||
                  item.description ||
                  "transform";
                const file =
                  item.target_file || (item.files_modified ?? [])[0] || "—";
                return (
                  <li
                    key={item.id}
                    className="grid min-w-[44rem] grid-cols-[7rem_1fr_1fr_6rem_9.5rem] items-center gap-2 px-3 py-2.5 text-sm"
                  >
                    <span className="truncate text-xs text-muted-foreground">
                      {formatRelativeTime(
                        rolledBack
                          ? item.rolled_back_at || item.created_at
                          : item.created_at,
                      )}
                    </span>
                    <span className="truncate font-medium" title={operation}>
                      {operation}
                    </span>
                    <span className="truncate font-mono text-xs" title={file}>
                      {file}
                    </span>
                    <span>
                      {rolledBack ? (
                        <StatusBadge label="Rolled Back" tone="success" />
                      ) : (
                        <StatusBadge label={item.status || "applied"} tone="muted" />
                      )}
                    </span>
                    <span>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!canRollback || rollbackById.isPending}
                        title={
                          canRollback
                            ? "Restore files to the pre-transformation snapshot"
                            : "This transformation has already been rolled back."
                        }
                        onClick={() => {
                          if (!canRollback) {
                            return;
                          }
                          rollbackById.mutate(item.id);
                        }}
                      >
                        {canRollback ? "Rollback" : "Already rolled back"}
                      </Button>
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </section>
    </PageContainer>
  );
}
