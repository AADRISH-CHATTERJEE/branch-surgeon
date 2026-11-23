"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { useApiOptions } from "@/hooks/use-api-options";
import { gateRepoQuery } from "@/queries/repo-query-gate";
import { queryKeys } from "@/queries/keys";
import { ApiError } from "@/services/errors";
import {
  createOrganizationRule,
  deleteOrganizationRule,
  disableOrganizationRule,
  duplicateOrganizationRule,
  enableOrganizationRule,
  exportOrganizationRules,
  fetchOrganizationRules,
  importOrganizationRules,
  previewOrganizationRule,
  updateOrganizationRule,
  type OrgRuleWriteBody,
} from "@/services/organization-rules";

export function useOrganizationRules(search?: string) {
  const opts = useApiOptions();
  return gateRepoQuery(
    opts.hydrated,
    useQuery({
      queryKey: [
        ...queryKeys.repo(opts.repoRoot ?? "default"),
        "organization-rules",
        search ?? "",
      ],
      queryFn: ({ signal }) =>
        fetchOrganizationRules({ ...opts, signal }, { search: search || undefined }),
      enabled: opts.hydrated,
      staleTime: 15_000,
    }),
  );
}

function invalidateOrgRules(qc: ReturnType<typeof useQueryClient>, repoRoot: string) {
  void qc.invalidateQueries({
    queryKey: [...queryKeys.repo(repoRoot), "organization-rules"],
  });
  void qc.invalidateQueries({ queryKey: queryKeys.rules(repoRoot) });
  void qc.invalidateQueries({ queryKey: queryKeys.activityRoot(repoRoot) });
  void qc.invalidateQueries({ queryKey: queryKeys.historyRoot(repoRoot) });
}

export function useCreateOrganizationRule() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  const repo = opts.repoRoot ?? "default";
  return useMutation({
    mutationFn: (body: OrgRuleWriteBody) => createOrganizationRule(body, opts),
    onSuccess: () => {
      toast.success("Organization rule created");
      invalidateOrgRules(qc, repo);
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Create failed"),
  });
}

export function useUpdateOrganizationRule() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  const repo = opts.repoRoot ?? "default";
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: OrgRuleWriteBody }) =>
      updateOrganizationRule(id, body, opts),
    onSuccess: () => {
      toast.success("Organization rule updated");
      invalidateOrgRules(qc, repo);
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Update failed"),
  });
}

export function useDeleteOrganizationRule() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  const repo = opts.repoRoot ?? "default";
  return useMutation({
    mutationFn: (id: string) => deleteOrganizationRule(id, opts),
    onSuccess: () => {
      toast.success("Organization rule deleted");
      invalidateOrgRules(qc, repo);
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Delete failed"),
  });
}

export function useDuplicateOrganizationRule() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  const repo = opts.repoRoot ?? "default";
  return useMutation({
    mutationFn: (id: string) => duplicateOrganizationRule(id, opts),
    onSuccess: () => {
      toast.success("Organization rule duplicated");
      invalidateOrgRules(qc, repo);
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Duplicate failed"),
  });
}

export function useToggleOrganizationRule() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  const repo = opts.repoRoot ?? "default";
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      enabled ? enableOrganizationRule(id, opts) : disableOrganizationRule(id, opts),
    onSuccess: (_data, vars) => {
      toast.success(vars.enabled ? "Rule enabled" : "Rule disabled");
      invalidateOrgRules(qc, repo);
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Toggle failed"),
  });
}

export function usePreviewOrgRule() {
  const opts = useApiOptions();
  return useMutation({
    mutationFn: (body: Parameters<typeof previewOrganizationRule>[0]) =>
      previewOrganizationRule(body, opts),
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Preview failed"),
  });
}

export function useExportOrganizationRules() {
  const opts = useApiOptions();
  return useMutation({
    mutationFn: () => exportOrganizationRules(opts),
    onSuccess: (data) => {
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "organization-rules.json";
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Organization rules exported");
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Export failed"),
  });
}

export function useImportOrganizationRules() {
  const opts = useApiOptions();
  const qc = useQueryClient();
  const repo = opts.repoRoot ?? "default";
  return useMutation({
    mutationFn: (body: { rules: OrgRuleWriteBody[]; replace?: boolean }) =>
      importOrganizationRules(body, opts),
    onSuccess: (data) => {
      toast.success(`Imported ${data.total} rule(s)`);
      invalidateOrgRules(qc, repo);
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Import failed"),
  });
}
