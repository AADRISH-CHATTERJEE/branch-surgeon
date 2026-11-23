"use client";

import * as React from "react";
import Link from "next/link";
import { Copy, Download, Plus, Trash2, Upload, Wand2 } from "lucide-react";
import { toast } from "sonner";

import { DataTable } from "@/components/data-display/data-table";
import { StatusBadge } from "@/components/data-display/status-badge";
import { ErrorState } from "@/components/feedback/error-state";
import { DetailDrawer } from "@/components/shared/detail-drawer";
import { DetailSection } from "@/components/shared/detail-section";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SearchInput } from "@/components/search-input";
import { ApiError } from "@/services/errors";
import type { OrganizationRule, RuleCondition } from "@/types/domain";
import {
  useCreateOrganizationRule,
  useDeleteOrganizationRule,
  useDuplicateOrganizationRule,
  useExportOrganizationRules,
  useImportOrganizationRules,
  useOrganizationRules,
  usePreviewOrgRule,
  useToggleOrganizationRule,
  useUpdateOrganizationRule,
} from "@/queries/use-organization-rules";

const RULE_TYPES = [
  "branch_naming",
  "commit_message",
  "pull_request",
  "file_path",
  "file_pattern",
  "code_pattern",
  "documentation",
  "testing",
  "security",
  "architecture",
  "custom",
] as const;

const SEVERITIES = ["blocker", "critical", "error", "warning", "info"] as const;
const OPERATORS = [
  "equals",
  "contains",
  "matches",
  "not_matches",
  "starts_with",
  "ends_with",
  "greater_than",
  "less_than",
  "exists",
  "missing",
] as const;

type Draft = {
  name: string;
  description: string;
  category: string;
  severity: string;
  enabled: boolean;
  rule_type: string;
  message: string;
  documentation_url: string;
  blocking: boolean;
  condition_logic: "and" | "or";
  conditions: RuleCondition[];
};

const emptyDraft = (): Draft => ({
  name: "",
  description: "",
  category: "custom",
  severity: "warning",
  enabled: true,
  rule_type: "custom",
  message: "",
  documentation_url: "",
  blocking: false,
  condition_logic: "and",
  conditions: [{ field: "branch_name", operator: "matches", pattern: "", value: "" }],
});

function fromRule(r: OrganizationRule): Draft {
  return {
    name: r.name,
    description: r.description || "",
    category: r.category || "custom",
    severity: r.severity || "warning",
    enabled: r.enabled !== false,
    rule_type: r.rule_type || "custom",
    message: r.message || "",
    documentation_url: r.documentation_url || "",
    blocking: Boolean(r.blocking),
    condition_logic: (r.condition_logic as "and" | "or") || "and",
    conditions: (r.conditions?.length
      ? r.conditions
      : [{ field: "", operator: "matches", pattern: "" }]
    ).map((c) => ({
      field: c.field || "",
      operator: c.operator || "matches",
      pattern: c.pattern || "",
      value: c.value ?? "",
    })),
  };
}

export function OrganizationRulesPanel() {
  const [search, setSearch] = React.useState("");
  const [severityFilter, setSeverityFilter] = React.useState<string>("all");
  const [enabledFilter, setEnabledFilter] = React.useState<string>("all");
  const [blockingFilter, setBlockingFilter] = React.useState<string>("all");
  const [categoryFilter, setCategoryFilter] = React.useState<string>("all");
  const list = useOrganizationRules(search);
  const create = useCreateOrganizationRule();
  const update = useUpdateOrganizationRule();
  const remove = useDeleteOrganizationRule();
  const duplicate = useDuplicateOrganizationRule();
  const toggle = useToggleOrganizationRule();
  const preview = usePreviewOrgRule();
  const exportRules = useExportOrganizationRules();
  const importRules = useImportOrganizationRules();
  const fileRef = React.useRef<HTMLInputElement>(null);

  const [editorOpen, setEditorOpen] = React.useState(false);
  const [editingId, setEditingId] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState<Draft>(emptyDraft);
  const [previewResult, setPreviewResult] = React.useState<string | null>(null);

  const categories = React.useMemo(() => {
    const set = new Set(
      (list.data ?? [])
        .map((r) => r.category || r.rule_type)
        .filter((c): c is string => Boolean(c)),
    );
    return [...set].sort();
  }, [list.data]);

  const filteredRows = React.useMemo(() => {
    return (list.data ?? []).filter((r) => {
      if (severityFilter !== "all" && r.severity !== severityFilter) return false;
      if (enabledFilter === "enabled" && r.enabled === false) return false;
      if (enabledFilter === "disabled" && r.enabled !== false) return false;
      if (blockingFilter === "blocking" && !r.blocking) return false;
      if (blockingFilter === "advisory" && r.blocking) return false;
      if (categoryFilter !== "all") {
        const cat = r.category || r.rule_type || "";
        if (cat !== categoryFilter) return false;
      }
      return true;
    });
  }, [list.data, severityFilter, enabledFilter, blockingFilter, categoryFilter]);

  const openCreate = () => {
    setEditingId(null);
    setDraft(emptyDraft());
    setPreviewResult(null);
    setEditorOpen(true);
  };

  const openEdit = (r: OrganizationRule) => {
    setEditingId(r.id);
    setDraft(fromRule(r));
    setPreviewResult(null);
    setEditorOpen(true);
  };

  const save = () => {
    const body = {
      ...draft,
      category: draft.category || draft.rule_type,
    };
    if (editingId) {
      update.mutate(
        { id: editingId, body },
        { onSuccess: () => setEditorOpen(false) },
      );
    } else {
      create.mutate(body, { onSuccess: () => setEditorOpen(false) });
    }
  };

  const runPreview = () => {
    preview.mutate(
      { rule: { ...draft, category: draft.category || draft.rule_type } },
      {
        onSuccess: (data) => {
          const n = data.violations?.length ?? 0;
          setPreviewResult(
            data.passed
              ? `Passed — ${data.rules_evaluated} rule(s) evaluated, no violations.`
              : `Failed — ${n} violation(s). ${JSON.stringify(data.violations?.[0] ?? {})}`,
          );
        },
      },
    );
  };

  const onImportFile = async (file: File) => {
    try {
      const text = await file.text();
      const parsed = JSON.parse(text) as { rules?: unknown };
      const rules = Array.isArray(parsed) ? parsed : parsed.rules;
      if (!Array.isArray(rules)) {
        toast.error("JSON must include a rules array");
        return;
      }
      importRules.mutate({ rules: rules as never[], replace: false });
    } catch {
      toast.error("Invalid JSON file");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput
          className="lg:max-w-xs"
          value={search}
          onChange={setSearch}
          placeholder="Search organization rules…"
        />
        <Select value={severityFilter} onValueChange={setSeverityFilter}>
          <SelectTrigger className="w-[9rem]" aria-label="Filter by severity">
            <SelectValue placeholder="Severity" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All severities</SelectItem>
            {SEVERITIES.map((s) => (
              <SelectItem key={s} value={s}>
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={enabledFilter} onValueChange={setEnabledFilter}>
          <SelectTrigger className="w-[8.5rem]" aria-label="Filter by enabled">
            <SelectValue placeholder="Enabled" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All enabled</SelectItem>
            <SelectItem value="enabled">Enabled</SelectItem>
            <SelectItem value="disabled">Disabled</SelectItem>
          </SelectContent>
        </Select>
        <Select value={blockingFilter} onValueChange={setBlockingFilter}>
          <SelectTrigger className="w-[8.5rem]" aria-label="Filter by blocking">
            <SelectValue placeholder="Blocking" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All modes</SelectItem>
            <SelectItem value="blocking">Blocking</SelectItem>
            <SelectItem value="advisory">Advisory</SelectItem>
          </SelectContent>
        </Select>
        <Select value={categoryFilter} onValueChange={setCategoryFilter}>
          <SelectTrigger className="w-[10rem]" aria-label="Filter by category">
            <SelectValue placeholder="Category" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All categories</SelectItem>
            {categories.map((c) => (
              <SelectItem key={c} value={c}>
                {c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button size="sm" onClick={openCreate}>
          <Plus className="size-3" aria-hidden />
          Create Rule
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={exportRules.isPending}
          onClick={() => exportRules.mutate()}
        >
          <Download className="size-3" aria-hidden />
          Export JSON
        </Button>
        <Button size="sm" variant="outline" onClick={() => fileRef.current?.click()}>
          <Upload className="size-3" aria-hidden />
          Import JSON
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept="application/json,.json"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void onImportFile(f);
            e.target.value = "";
          }}
        />
      </div>

      {list.isError ? (
        <ErrorState
          title="Could not load organization rules"
          description={list.error instanceof ApiError ? list.error.message : undefined}
          onRetry={() => void list.refetch()}
        />
      ) : (
        <DataTable
          columns={[
            {
              id: "name",
              header: "Name",
              className: "font-medium",
              cell: (r: OrganizationRule) => r.name,
            },
            {
              id: "type",
              header: "Type",
              cell: (r) => r.rule_type || r.category,
            },
            {
              id: "severity",
              header: "Severity",
              cell: (r) => <StatusBadge label={r.severity} />,
            },
            {
              id: "blocking",
              header: "Blocking",
              cell: (r) => (r.blocking ? "Yes" : "No"),
            },
            {
              id: "enabled",
              header: "Enabled",
              cell: (r) => (
                <StatusBadge
                  label={r.enabled === false ? "disabled" : "enabled"}
                  tone={r.enabled === false ? "muted" : "success"}
                />
              ),
            },
            {
              id: "source",
              header: "Source",
              cell: () => <StatusBadge label="Organization" tone="info" />,
            },
          ]}
          data={filteredRows}
          getRowId={(r) => r.id}
          onRowClick={(r) => openEdit(r)}
          isLoading={list.isLoading}
          emptyTitle="No organization rules"
          emptyDescription="Create a policy or import a JSON catalog."
          emptyActionLabel="Create Rule"
          onEmptyAction={openCreate}
        />
      )}

      <DetailDrawer
        open={editorOpen}
        onOpenChange={setEditorOpen}
        title={editingId ? "Edit organization rule" : "Create organization rule"}
        description="Persisted company policy — additive to built-in rules"
        badges={<StatusBadge label="Organization" tone="info" />}
        footer={
          <div className="flex w-full flex-wrap gap-2">
            <Button size="sm" onClick={save} disabled={create.isPending || update.isPending}>
              {editingId ? "Save" : "Create"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={runPreview}
              disabled={preview.isPending}
            >
              <Wand2 className="size-3" aria-hidden />
              {preview.isPending ? "Running…" : "Run Rule"}
            </Button>
            {editingId ? (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    toggle.mutate({
                      id: editingId,
                      enabled: draft.enabled === false,
                    })
                  }
                >
                  {draft.enabled === false ? "Enable" : "Disable"}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    duplicate.mutate(editingId, {
                      onSuccess: () => setEditorOpen(false),
                    })
                  }
                >
                  <Copy className="size-3" aria-hidden />
                  Duplicate
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() =>
                    remove.mutate(editingId, { onSuccess: () => setEditorOpen(false) })
                  }
                >
                  <Trash2 className="size-3" aria-hidden />
                  Delete
                </Button>
              </>
            ) : null}
          </div>
        }
      >
        <div className="space-y-4">
          <DetailSection title="Basics">
            <div className="grid gap-3">
              <Field label="Name">
                <Input
                  value={draft.name}
                  onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                />
              </Field>
              <Field label="Description">
                <Textarea
                  value={draft.description}
                  onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
                  rows={2}
                />
              </Field>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Rule type">
                  <Select
                    value={draft.rule_type}
                    onValueChange={(v) =>
                      setDraft((d) => ({ ...d, rule_type: v, category: v }))
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {RULE_TYPES.map((t) => (
                        <SelectItem key={t} value={t}>
                          {t}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Severity">
                  <Select
                    value={draft.severity}
                    onValueChange={(v) =>
                      setDraft((d) => ({
                        ...d,
                        severity: v,
                        blocking: v === "blocker" || v === "critical" ? true : d.blocking,
                      }))
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {SEVERITIES.map((s) => (
                        <SelectItem key={s} value={s}>
                          {s}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
              </div>
              <Field label="Error message">
                <Textarea
                  value={draft.message}
                  onChange={(e) => setDraft((d) => ({ ...d, message: e.target.value }))}
                  rows={2}
                />
              </Field>
              <Field label="Documentation link">
                <Input
                  value={draft.documentation_url}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, documentation_url: e.target.value }))
                  }
                  placeholder="/documentation?doc=branching"
                />
                {draft.documentation_url ? (
                  <Button size="sm" variant="link" className="h-auto px-0" asChild>
                    <Link href={draft.documentation_url}>Open documentation</Link>
                  </Button>
                ) : null}
              </Field>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={draft.blocking}
                  onChange={(e) => setDraft((d) => ({ ...d, blocking: e.target.checked }))}
                />
                Blocking (stops patch apply / merge gates)
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={draft.enabled}
                  onChange={(e) => setDraft((d) => ({ ...d, enabled: e.target.checked }))}
                />
                Enabled
              </label>
            </div>
          </DetailSection>

          <DetailSection title="Condition builder">
            <div className="mb-2 flex items-center gap-2">
              <Label>Logic</Label>
              <Select
                value={draft.condition_logic}
                onValueChange={(v) =>
                  setDraft((d) => ({ ...d, condition_logic: v as "and" | "or" }))
                }
              >
                <SelectTrigger className="w-28">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="and">AND</SelectItem>
                  <SelectItem value="or">OR</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-3">
              {draft.conditions.map((c, i) => (
                <div key={i} className="grid gap-2 rounded-md border p-2 sm:grid-cols-4">
                  <Input
                    placeholder="field"
                    value={c.field}
                    onChange={(e) =>
                      setDraft((d) => {
                        const conditions = [...d.conditions];
                        conditions[i] = { ...conditions[i], field: e.target.value };
                        return { ...d, conditions };
                      })
                    }
                  />
                  <Select
                    value={c.operator || "matches"}
                    onValueChange={(v) =>
                      setDraft((d) => {
                        const conditions = [...d.conditions];
                        conditions[i] = { ...conditions[i], operator: v };
                        return { ...d, conditions };
                      })
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {OPERATORS.map((op) => (
                        <SelectItem key={op} value={op}>
                          {op}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Input
                    placeholder="pattern / value"
                    value={String(c.pattern || c.value || "")}
                    onChange={(e) =>
                      setDraft((d) => {
                        const conditions = [...d.conditions];
                        conditions[i] = {
                          ...conditions[i],
                          pattern: e.target.value,
                          value: e.target.value,
                        };
                        return { ...d, conditions };
                      })
                    }
                    className="sm:col-span-2"
                  />
                </div>
              ))}
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  setDraft((d) => ({
                    ...d,
                    conditions: [
                      ...d.conditions,
                      { field: "", operator: "matches", pattern: "" },
                    ],
                  }))
                }
              >
                Add condition
              </Button>
            </div>
          </DetailSection>

          <DetailSection title="Preview">
            <p className="text-xs text-muted-foreground mb-2">
              Runs this rule against the configured repository (does not save).
            </p>
            {previewResult ? (
              <p className="whitespace-pre-wrap text-sm">{previewResult}</p>
            ) : (
              <p className="text-sm text-muted-foreground">No preview yet.</p>
            )}
          </DetailSection>
        </div>
      </DetailDrawer>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <Label>{label}</Label>
      {children}
    </div>
  );
}
