import { apiRequest, type ApiClientOptions } from "@/services/client";
import { endpoints } from "@/services/endpoints";
import type { OrganizationRule, RuleItem } from "@/types/domain";

export type OrgRuleWriteBody = {
  name: string;
  description?: string;
  category?: string;
  severity?: string;
  enabled?: boolean;
  rule_type?: string;
  conditions?: RuleItem["conditions"];
  condition_logic?: string;
  message?: string;
  documentation_url?: string;
  blocking?: boolean;
};

export function fetchOrganizationRules(
  options: ApiClientOptions = {},
  params: { enabled?: boolean; search?: string } = {},
) {
  const sp = new URLSearchParams();
  if (params.enabled !== undefined) sp.set("enabled", String(params.enabled));
  if (params.search) sp.set("search", params.search);
  const q = sp.toString();
  return apiRequest<OrganizationRule[]>(
    `${endpoints.organizationRules}${q ? `?${q}` : ""}`,
    options,
  );
}

export function createOrganizationRule(
  body: OrgRuleWriteBody,
  options: ApiClientOptions = {},
) {
  return apiRequest<OrganizationRule>(endpoints.organizationRules, {
    ...options,
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateOrganizationRule(
  id: string,
  body: OrgRuleWriteBody,
  options: ApiClientOptions = {},
) {
  return apiRequest<OrganizationRule>(endpoints.organizationRule(id), {
    ...options,
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function deleteOrganizationRule(id: string, options: ApiClientOptions = {}) {
  return apiRequest<{ id: string; deleted: boolean }>(endpoints.organizationRule(id), {
    ...options,
    method: "DELETE",
  });
}

export function duplicateOrganizationRule(id: string, options: ApiClientOptions = {}) {
  return apiRequest<OrganizationRule>(endpoints.organizationRuleDuplicate(id), {
    ...options,
    method: "POST",
  });
}

export function enableOrganizationRule(id: string, options: ApiClientOptions = {}) {
  return apiRequest<OrganizationRule>(endpoints.organizationRuleEnable(id), {
    ...options,
    method: "POST",
  });
}

export function disableOrganizationRule(id: string, options: ApiClientOptions = {}) {
  return apiRequest<OrganizationRule>(endpoints.organizationRuleDisable(id), {
    ...options,
    method: "POST",
  });
}

export function previewOrganizationRule(
  body: {
    rule?: OrgRuleWriteBody | null;
    rule_id?: string | null;
    branch?: string | null;
    commit?: string | null;
    changed_files?: string[] | null;
  },
  options: ApiClientOptions = {},
) {
  return apiRequest<{
    passed: boolean;
    rules_evaluated: number;
    violations: Array<Record<string, unknown>>;
    context?: Record<string, unknown>;
  }>(endpoints.organizationRulesPreview, {
    ...options,
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function exportOrganizationRules(options: ApiClientOptions = {}) {
  return apiRequest<{
    version: string;
    type: string;
    rules: OrganizationRule[];
  }>(endpoints.organizationRulesExport, options);
}

export function importOrganizationRules(
  body: { rules: OrgRuleWriteBody[]; replace?: boolean },
  options: ApiClientOptions = {},
) {
  return apiRequest<{ created: number; updated: number; total: number }>(
    endpoints.organizationRulesImport,
    {
      ...options,
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}
